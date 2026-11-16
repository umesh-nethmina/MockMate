"""Sandbox (FR-31, NFR-07). Output parsing is unit-tested; the security tests run real Docker containers and
are skipped when Docker is not available."""

import json
import shutil
import subprocess

import pytest

from app import coding
from app.tools import sandbox as sb
from app.tools.sandbox import MARKER, DockerSandbox, parse_output


def line(obj) -> str:
    return f"noise\n{MARKER}{json.dumps(obj)}\n"


def test_parse_ok_results():
    out = line({"results": [{"ok": True, "output": 3, "stdout": "", "error": None, "ms": 1.0}]})
    r = parse_output(out, 0, False, False)
    assert r.status == "ok" and r.passed == 1 and r.results[0].output == 3


def test_parse_uses_last_marker_line():
    out = line({"results": []}) + line({"compile_error": "SyntaxError: bad (line 2)"})
    r = parse_output(out, 0, False, False)
    assert r.status == "compile_error" and "line 2" in r.message


@pytest.mark.parametrize(
    ("exit_code", "timed_out", "overflow", "status"),
    [(152, False, False, "time_limit"), (None, True, False, "time_limit"), (137, False, False, "memory_limit"),
     (0, False, True, "output_limit"), (1, False, False, "runtime_error")],
)
def test_parse_limits(exit_code, timed_out, overflow, status):
    r = parse_output("", exit_code, timed_out, overflow, stderr="Traceback\nKilled")
    assert r.status == status and r.message and r.results == []


def test_docker_args_apply_every_limit():
    args = sb.docker_args("x", sb._Runtime("img", ["python"]))
    joined = " ".join(args)
    for flag in ["--network none", "--read-only", "--memory 128m", "--memory-swap 128m", "--pids-limit 64",
                 "--ulimit cpu=5:5", "--user 65534:65534", "--cap-drop ALL", "no-new-privileges"]:
        assert flag in joined
    assert args[-2:] == ["img", "python"]


def test_unavailable_when_disabled(monkeypatch):
    monkeypatch.setattr(sb.get_settings(), "sandbox_enabled", False)
    box = DockerSandbox()
    assert box.available() is False
    with pytest.raises(sb.SandboxUnavailable):
        box.run("python", "x", "f", [])


def test_missing_docker_cli_is_unavailable(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(sb.subprocess, "Popen", boom)
    monkeypatch.setattr(sb.subprocess, "run", boom)
    box = DockerSandbox()
    assert box.available() is False
    with pytest.raises(sb.SandboxUnavailable):
        box.run("python", "x", "f", [])


# ---------- real containers ----------

def _docker_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


docker = pytest.mark.skipif(not _docker_up(), reason="Docker is not running")
TESTS = [{"args": [[2, 7, 11, 15], 9], "expected": [0, 1]}, {"args": [[3, 2, 4], 6], "expected": [1, 2]}]


@pytest.fixture(scope="module")
def box():
    b = DockerSandbox()
    b.prepare()
    return b


def py(body: str) -> str:
    return "def f(nums, target):\n" + "\n".join("    " + ln for ln in body.splitlines()) + "\n"


@docker
def test_real_python_solution_passes(box):
    code = py("seen = {}\nfor i, n in enumerate(nums):\n    if target - n in seen:\n"
              "        return (seen[target - n], i)\n    seen[n] = i")
    r = box.run("python", code, "f", TESTS)
    assert r.status == "ok" and r.passed == 2  # tuple compared as a list


@docker
def test_real_javascript_solution_and_no_require(box):
    code = "function f(nums, target) { console.log('hi'); return [0, 1]; }"
    r = box.run("javascript", code, "f", TESTS)
    assert r.status == "ok" and [x.ok for x in r.results] == [True, False] and r.results[0].stdout == "hi\n"
    r = box.run("javascript", "function f() { return require('fs').readdirSync('/') }", "f", TESTS[:1])
    assert "require is not defined" in r.results[0].error


@docker
def test_real_compile_error_and_missing_function(box):
    assert box.run("python", "def f(:\n", "f", TESTS).message == "SyntaxError: invalid syntax (line 1)"
    assert "Define a function named f" in box.run("python", "x = 1\n", "f", TESTS).message


@docker
def test_network_is_blocked(box):
    r = box.run("python", py("import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=3)"), "f", TESTS[:1])
    assert "Network unreachable" in r.results[0].error or "OSError" in r.results[0].error


@docker
def test_file_system_is_read_only_and_user_is_not_root(box):
    r = box.run("python", py("open('/etc/evil', 'w')"), "f", TESTS[:1])
    assert "Read-only file system" in r.results[0].error
    r = box.run("python", py("import os\nreturn [os.getuid(), os.getgid()]"), "f", TESTS[:1])
    assert r.results[0].output == [65534, 65534]


@docker
def test_infinite_loop_hits_per_test_and_total_time_limits(box):
    r = box.run("python", py("while True:\n    pass"), "f", TESTS * 3)
    assert r.status == "ok" and r.passed == 0
    assert r.results[0].error.startswith("Time limit exceeded")
    assert r.results[-1].error == "Not run: time budget used up"
    assert r.duration_ms < 15_000


@docker
def test_sleep_cannot_hang_the_runner(box):
    r = box.run("python", py("import time\ntime.sleep(60)"), "f", TESTS[:1])
    assert r.results[0].error.startswith("Time limit exceeded")


@docker
def test_memory_bomb_is_killed(box):
    r = box.run("python", py("x = []\nwhile True:\n    x.append(' ' * 10**6)"), "f", TESTS[:1])
    assert r.status == "memory_limit"


@docker
def test_fork_bomb_is_contained(box):
    r = box.run("python", py("import os\nwhile True:\n    os.fork()"), "f", TESTS[:1])
    assert r.passed == 0  # the process limit stops it; the runner still reports
    assert r.status in ("ok", "runtime_error", "memory_limit", "time_limit")


@docker
def test_output_flood_is_cut_off(box):
    r = box.run("python", py("import os\nwhile True:\n    os.write(1, b'x' * 65536)"), "f", TESTS[:1])
    assert r.status == "output_limit"


@docker
def test_seeded_reference_solutions_pass_their_tests(box):
    problems = json.loads(coding.SEED_FILE.read_text(encoding="utf-8"))
    for p in problems:
        errors = coding.validate_reference(box, p["function_name"], p["reference_solution"], p["tests"])
        assert errors == [], p["title"]
