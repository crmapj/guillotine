from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any

RESULT_PREFIX = "__GUILLOTINE_RESULT__"

# Per-stream capture cap. Agent code printing in a loop must not OOM the host before
# the timeout fires; past the cap we keep draining the pipe but discard the bytes.
MAX_CAPTURE_BYTES = 4 * 1024 * 1024
# Post-kill drain bound: a detached grandchild holding the pipe must not block forever.
DRAIN_GRACE_SECONDS = 3.0


@dataclass(frozen=True)
class ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    result: Any = None
    timed_out: bool = False
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "result": self.result,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
        }


class _CappedReader(threading.Thread):
    """Drains a byte stream into a capped buffer, discarding overflow so the child
    never blocks on a full pipe."""

    def __init__(self, stream: Any, cap: int = MAX_CAPTURE_BYTES) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._cap = cap
        self._chunks: list[bytes] = []
        self._size = 0
        self.truncated = False

    def run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(65536)
                if not chunk:
                    break
                if self._size < self._cap:
                    room = self._cap - self._size
                    self._chunks.append(chunk[:room])
                    self._size += min(len(chunk), room)
                    if len(chunk) > room:
                        self.truncated = True
                else:
                    self.truncated = True
        except (ValueError, OSError):
            # Stream closed underneath us during a kill/drain; stop cleanly.
            pass

    def text(self) -> str:
        data = b"".join(self._chunks).decode("utf-8", errors="replace")
        if self.truncated:
            data += f"\n[output truncated at {self._cap} bytes]"
        return data


def execute(
    code: str,
    *,
    extra_paths: list[str | Path] | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> ExecutionResult:
    """Execute agent code in a short-lived Python subprocess.

    This is the v0 local executor. It provides NO sandboxing: the code runs with the
    full privileges of the calling process (filesystem, network, and subprocesses).
    It is intentionally small and pluggable; hosted or untrusted deployments must
    replace it with a real isolation boundary while keeping this result contract.

    The one bound it does enforce is the timeout, which kills the whole child process
    group so detached grandchildren cannot outlive the call.
    """
    extra_paths = [str(Path(p)) for p in (extra_paths or [])]
    wrapper = _wrapper_source(code, extra_paths)
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(("PYTHON", "PATH", "LANG", "LC_", "GUILLOTINE_"))
    }
    child_env.update(env or {})
    with tempfile.TemporaryDirectory(prefix="guillotine-exec-") as tmp:
        script = Path(tmp) / "run.py"
        script.write_text(wrapper, encoding="utf-8")
        # start_new_session puts the child in its own process group so a timeout can
        # kill the whole tree, not just the direct child.
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=tmp,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        out_reader = _CappedReader(proc.stdout)
        err_reader = _CappedReader(proc.stderr)
        out_reader.start()
        err_reader.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_group(proc)

        # Bound the drain so a grandchild holding the pipe write-end can't hang us.
        out_reader.join(DRAIN_GRACE_SECONDS)
        err_reader.join(DRAIN_GRACE_SECONDS)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()

    stdout_text = out_reader.text()
    stderr_text = err_reader.text()
    truncated = out_reader.truncated or err_reader.truncated

    if timed_out:
        return ExecutionResult(
            returncode=124,
            stdout=stdout_text,
            stderr=stderr_text + f"\nTimed out after {timeout}s; process group killed.",
            timed_out=True,
            truncated=truncated,
        )

    stdout, result = _split_result(stdout_text)
    return ExecutionResult(
        proc.returncode,
        stdout,
        stderr_text,
        result=result,
        truncated=truncated,
    )


def _kill_process_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        # No process group (e.g. Windows) or already gone: fall back to the child.
        proc.kill()


def _wrapper_source(code: str, extra_paths: list[str]) -> str:
    return dedent(
        f"""
            from __future__ import annotations

            import json
            import sys

            sys.path[:0] = {extra_paths!r}

            def _safe(value):
                try:
                    json.dumps(value)
                    return value
                except TypeError:
                    if hasattr(value, "head"):
                        try:
                            return value.head(10)
                        except Exception:
                            pass
                    return repr(value)

            ns = {{}}
            code = {code!r}
            exec(compile(code, "<guillotine-exec>", "exec"), ns, ns)
            if "result" in ns:
                print("{RESULT_PREFIX}" + json.dumps(_safe(ns["result"]), default=str))
            """
    ).lstrip()


def _split_result(stdout: str) -> tuple[str, Any]:
    lines = stdout.splitlines()
    result = None
    kept: list[str] = []
    for line in lines:
        if line.startswith(RESULT_PREFIX):
            payload = line[len(RESULT_PREFIX) :]
            try:
                result = json.loads(payload)
            except json.JSONDecodeError:
                result = payload
        else:
            kept.append(line)
    suffix = "\n" if stdout.endswith("\n") and kept else ""
    return "\n".join(kept) + suffix, result
