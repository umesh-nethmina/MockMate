"""Test harness that runs INSIDE the sandbox container (never in the API process).

Reads {"code", "function", "tests", "per_test_seconds"} as JSON on stdin, runs the candidate's function on each
test's arguments and prints one result line, prefixed with a marker, on the real stdout. The candidate's own
prints are captured per test so they cannot forge the result line by accident.
"""

import contextlib
import copy
import io
import json
import math
import os
import signal
import sys
import time
import traceback

MARKER = "__MOCKMATE_RESULT__"
MAIN_PID = os.getpid()
REAL_STDOUT = sys.stdout
MAX_CAPTURE = 2000
SKIPPED = "Not run: time budget used up"


class TestTimeLimit(BaseException):  # BaseException so `except Exception` in user code cannot swallow it
    pass


def emit(obj):
    if os.getpid() != MAIN_PID:  # a forked child must not report
        os._exit(0)
    REAL_STDOUT.write("\n" + MARKER + json.dumps(obj) + "\n")
    REAL_STDOUT.flush()


def describe(exc):
    line = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == "solution.py":
            line = frame.lineno
    if isinstance(exc, SyntaxError):
        return f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})"
    text = f"{type(exc).__name__}: {exc}".strip()
    return f"{text} (line {line})" if line else text


def normalise(value):
    return json.loads(json.dumps(value, default=repr))  # tuples -> lists, unknown objects -> repr strings


def equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    return a == b


def on_timer(signum, frame):
    raise TestTimeLimit()


def arm(seconds):
    """CPU-time limit per test, plus a looser wall-clock one so sleep() cannot hang the run."""
    signal.setitimer(signal.ITIMER_PROF, seconds)
    signal.setitimer(signal.ITIMER_REAL, seconds * 2)


def main():
    payload = json.loads(sys.stdin.read())
    sys.stdin = io.StringIO("")
    limit = float(payload.get("per_test_seconds", 2))
    budget = float(payload.get("budget_seconds", 4))  # stop before the container's hard CPU limit
    signal.signal(signal.SIGPROF, on_timer)
    signal.signal(signal.SIGALRM, on_timer)

    namespace = {"__name__": "solution"}
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            arm(limit)
            exec(compile(payload["code"], "solution.py", "exec"), namespace)
            arm(0)
    except TestTimeLimit:
        emit({"compile_error": "Your code took too long to load (is there an infinite loop at the top level?)"})
        return
    except BaseException as exc:
        arm(0)
        emit({"compile_error": describe(exc)})
        return

    fn = namespace.get(payload["function"])
    if not callable(fn):
        emit({"compile_error": f"Define a function named {payload['function']}"})
        return

    results = []
    for test in payload["tests"]:
        if time.process_time() > budget:
            results.append({"ok": False, "output": None, "stdout": "", "error": SKIPPED, "ms": 0})
            continue
        out = io.StringIO()
        error, output, ok = None, None, False
        start = time.perf_counter()
        try:
            with contextlib.redirect_stdout(out):
                arm(limit)
                got = fn(*copy.deepcopy(test["args"]))
                arm(0)
            output = normalise(got)
            ok = equal(output, test["expected"])
        except TestTimeLimit:
            error = f"Time limit exceeded ({limit:g} s)"
        except RecursionError:
            arm(0)
            error = "RecursionError: maximum recursion depth exceeded"
        except BaseException as exc:
            arm(0)
            error = describe(exc)
        results.append(
            {
                "ok": ok,
                "output": output,
                "stdout": out.getvalue()[:MAX_CAPTURE],
                "error": error,
                "ms": round((time.perf_counter() - start) * 1000, 1),
            }
        )
    emit({"results": results})


main()
