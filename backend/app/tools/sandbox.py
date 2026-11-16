"""Code sandbox tool (FR-31, NFR-07): runs candidate code against test cases in a throw-away Docker container.

Each run gets a fresh container with no network, a read-only file system, a CPU-time limit, a memory limit,
a process limit and a non-root user, and is killed after a wall-clock timeout. The candidate's code and the
tests go in on stdin; a small harness inside the container (app/tools/harness) runs the tests and prints one
marked JSON result line. Nothing from the candidate ever runs in the API process.
"""

import json
import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from app.config import get_settings

log = logging.getLogger(__name__)

Language = Literal["python", "javascript"]
Status = Literal["ok", "compile_error", "time_limit", "memory_limit", "output_limit", "runtime_error"]

MARKER = "__MOCKMATE_RESULT__"
HARNESS_DIR = Path(__file__).parent / "harness"
EXIT_SIGKILL = 137  # OOM killer (or our own kill after the wall-clock timeout)
EXIT_SIGXCPU = 152  # CPU-time ulimit reached

STATUS_MESSAGES: dict[str, str] = {
    "time_limit": "Your code used more than {cpu} s of CPU time in total. Look for an infinite loop or a slower "
    "algorithm than needed.",
    "wall_limit": "Your code took too long to finish (is it waiting or sleeping?).",
    "memory_limit": "Your code used more than {mem} MB of memory.",
    "output_limit": "Your code printed too much output.",
    "runtime_error": "Your code crashed the test runner.",
}


class SandboxUnavailable(Exception):
    """Docker is not reachable or too busy; nothing was run (HTTP 503)."""

    user_message = "The code runner is not available right now. Please try again in a minute."


@dataclass
class TestOutcome:
    __test__ = False  # not a pytest test class

    ok: bool
    output: Any = None
    stdout: str = ""
    error: str | None = None
    ms: float | None = None


@dataclass
class RunResult:
    status: Status
    results: list[TestOutcome] = field(default_factory=list)
    message: str | None = None  # compile error or limit explanation
    duration_ms: int = 0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok)


class Sandbox(Protocol):
    def run(self, language: Language, code: str, function: str, tests: list[dict]) -> RunResult: ...

    def available(self) -> bool: ...


@dataclass(frozen=True)
class _Runtime:
    image: str
    command: list[str]


def _runtimes() -> dict[str, _Runtime]:
    s = get_settings()
    py = (HARNESS_DIR / "runner.py").read_text(encoding="utf-8")
    js = (HARNESS_DIR / "runner.js").read_text(encoding="utf-8")
    heap = max(32, s.sandbox_memory_mb - 32)
    return {
        "python": _Runtime(s.sandbox_python_image, ["python", "-I", "-B", "-c", py]),
        "javascript": _Runtime(s.sandbox_node_image, ["node", f"--max-old-space-size={heap}", "-e", js]),
    }


def docker_args(name: str, runtime: _Runtime) -> list[str]:
    s = get_settings()
    return [
        "docker", "run", "--rm", "-i", "--name", name,
        "--network", "none",  # no network access
        "--read-only",  # read-only root file system
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=8m",
        "--memory", f"{s.sandbox_memory_mb}m", "--memory-swap", f"{s.sandbox_memory_mb}m",
        "--cpus", "1",
        "--pids-limit", str(s.sandbox_pids_limit),  # stops fork bombs
        "--ulimit", f"cpu={s.sandbox_cpu_seconds}:{s.sandbox_cpu_seconds}",
        "--ulimit", "nofile=64:64",
        "--ulimit", "fsize=1048576:1048576",
        "--user", "65534:65534",  # nobody
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--ipc", "none",
        "-e", "HOME=/tmp",
        "-w", "/tmp",
        runtime.image,
        *runtime.command,
    ]


class _Reader(threading.Thread):
    """Reads a pipe up to `limit` bytes; flags overflow so the caller can stop the container."""

    def __init__(self, pipe, limit: int) -> None:
        super().__init__(daemon=True)
        self.pipe, self.limit = pipe, limit
        self.data = bytearray()
        self.overflow = threading.Event()

    def run(self) -> None:
        while chunk := self.pipe.read(65536):
            if len(self.data) < self.limit:
                self.data += chunk[: self.limit - len(self.data)]
            else:
                self.overflow.set()  # keep draining so the writer never blocks on a full pipe


def parse_output(stdout: str, exit_code: int | None, timed_out: bool, overflow: bool, stderr: str = "") -> RunResult:
    """Turn the container's output into a RunResult. Pure, so it is unit-tested without Docker."""
    s = get_settings()
    fmt = {"cpu": s.sandbox_cpu_seconds, "mem": s.sandbox_memory_mb}

    def limit(status: Status) -> RunResult:
        return RunResult(status, message=STATUS_MESSAGES[status].format(**fmt))

    if overflow:
        return limit("output_limit")
    if exit_code == EXIT_SIGXCPU:
        return limit("time_limit")
    if timed_out:
        return RunResult("time_limit", message=STATUS_MESSAGES["wall_limit"])

    line = next((ln for ln in reversed(stdout.splitlines()) if ln.startswith(MARKER)), None)
    if line is None:
        if exit_code == EXIT_SIGKILL:
            return limit("memory_limit")
        tail = stderr.strip().splitlines()[-1:] or [""]
        msg = STATUS_MESSAGES["runtime_error"].format(**fmt)
        return RunResult("runtime_error", message=f"{msg} {tail[0][:300]}".strip())

    data = json.loads(line[len(MARKER):])
    if "compile_error" in data:
        return RunResult("compile_error", message=str(data["compile_error"])[:1000])
    return RunResult("ok", results=[TestOutcome(**r) for r in data["results"]])


class DockerSandbox:
    def __init__(self) -> None:
        s = get_settings()
        self._slots = threading.BoundedSemaphore(s.sandbox_max_concurrent)
        self._available: tuple[float, bool] | None = None

    def available(self) -> bool:
        """Cached for a minute: is the Docker daemon reachable?"""
        now = time.monotonic()
        if self._available and now - self._available[0] < 60:
            return self._available[1]
        ok = False
        if get_settings().sandbox_enabled:
            try:
                ok = subprocess.run(
                    ["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=10
                ).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
        self._available = (now, ok)
        return ok

    def prepare(self) -> None:
        """Pull the runtime images if missing, so the first run is not slowed down by a download."""
        if not self.available():
            return
        for runtime in _runtimes().values():
            inspect = subprocess.run(["docker", "image", "inspect", runtime.image], capture_output=True)
            if inspect.returncode != 0:
                log.info("pulling sandbox image %s", runtime.image)
                subprocess.run(["docker", "pull", "-q", runtime.image], capture_output=True, timeout=600)

    def run(self, language: Language, code: str, function: str, tests: list[dict]) -> RunResult:
        s = get_settings()
        if not s.sandbox_enabled:
            raise SandboxUnavailable()
        if not self._slots.acquire(timeout=s.sandbox_queue_seconds):
            raise SandboxUnavailable()
        try:
            return self._run(_runtimes()[language], code, function, tests)
        finally:
            self._slots.release()

    def _run(self, runtime: _Runtime, code: str, function: str, tests: list[dict]) -> RunResult:
        s = get_settings()
        name = f"mockmate-run-{uuid.uuid4().hex[:12]}"
        payload = json.dumps(
            {
                "code": code,
                "function": function,
                "tests": tests,
                "per_test_seconds": s.sandbox_test_seconds,
                "budget_seconds": max(1.0, s.sandbox_cpu_seconds - 1.0),
            }
        ).encode()
        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                docker_args(name, runtime), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except OSError as err:
            raise SandboxUnavailable() from err

        out, err = _Reader(proc.stdout, s.sandbox_max_output_bytes), _Reader(proc.stderr, 64 * 1024)
        out.start()
        err.start()
        try:
            proc.stdin.write(payload)  # type: ignore[union-attr]
            proc.stdin.close()  # type: ignore[union-attr]
        except OSError:
            pass  # container died early; the exit code tells us why

        timed_out = False
        deadline = started + s.sandbox_wall_seconds
        while proc.poll() is None:
            if out.overflow.is_set():
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            time.sleep(0.02)
        if proc.poll() is None:
            proc.kill()
            try:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
            except subprocess.TimeoutExpired:
                log.error("could not remove sandbox container %s", name)
        proc.wait(timeout=30)
        out.join(timeout=5)
        err.join(timeout=5)

        stderr = err.data.decode("utf-8", "replace")
        if proc.returncode == 125 or "Cannot connect to the Docker daemon" in stderr:  # docker itself failed
            log.error("sandbox docker error: %s", stderr[-500:])
            self._available = None
            raise SandboxUnavailable()

        result = parse_output(
            out.data.decode("utf-8", "replace"), proc.returncode, timed_out, out.overflow.is_set(), stderr
        )
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result


_sandbox: DockerSandbox | None = None


def get_sandbox() -> Sandbox:
    """FastAPI dependency; tests override it with a fake."""
    global _sandbox
    if _sandbox is None:
        _sandbox = DockerSandbox()
    return _sandbox
