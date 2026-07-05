from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from guillotine.runtime import execute

FIXTURE = Path(__file__).parent / "fixtures" / "todo_openapi.yaml"


def _run_cli(*cli_args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    return subprocess.run(
        [sys.executable, "-m", "guillotine", *cli_args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_cli_build_writes_all_projection_dirs(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "guillotine",
            "build",
            str(FIXTURE),
            "-o",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "acme_tasks" / "__init__.py").exists()
    assert (tmp_path / "skills" / "tasks" / "SKILL.md").exists()
    assert (tmp_path / "mcp" / "server.py").exists()


def test_cli_inspect_reports_compiler_surface() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "guillotine",
            "inspect",
            str(FIXTURE),
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["package_name"] == "acme_tasks"
    assert report["resources"] == 2
    assert report["operations"] == 5
    assert report["delete_operations"] == 1
    assert report["paginated_operations"] == 1
    assert report["estimated_static_reduction"] > 1


def test_runtime_execute_returns_result(tmp_path: Path) -> None:
    code = "result = {'ok': True, 'n': 3}"

    result = execute(code, extra_paths=[tmp_path])

    assert result.returncode == 0
    assert result.result == {"ok": True, "n": 3}


def test_runtime_execute_times_out() -> None:
    result = execute("import time; time.sleep(10)", timeout=0.5)

    assert result.timed_out is True
    assert result.returncode == 124


def test_cli_missing_spec_prints_clean_error(tmp_path: Path) -> None:
    proc = _run_cli("build", str(tmp_path / "nonexistent.yaml"))

    assert proc.returncode == 2
    assert "error:" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_malformed_yaml_prints_clean_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("openapi: 3.0.0\npaths: [unclosed\n", encoding="utf-8")

    proc = _run_cli("build", str(bad))

    assert proc.returncode == 2
    assert "error:" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_runtime_execute_caps_unbounded_output() -> None:
    # Child prints far more than the cap; must finish promptly with truncated output.
    code = (
        "import sys\n"
        "line = 'x' * 1000 + '\\n'\n"
        "for _ in range(20000):\n"
        "    sys.stdout.write(line)\n"
    )

    start = time.monotonic()
    result = execute(code, timeout=30.0)
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert result.truncated is True
    assert len(result.stdout.encode("utf-8")) < 5 * 1024 * 1024
    assert elapsed < 20.0


def test_runtime_execute_small_output_unchanged() -> None:
    result = execute("print('hello'); result = {'ok': True}")

    assert result.returncode == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.result == {"ok": True}
    assert result.truncated is False


def test_runtime_execute_timeout_does_not_hang_on_detached_child() -> None:
    # Detached child inherits stdout and outlives the kill; the post-kill drain must
    # be bounded, so execute() returns within timeout + a small grace, not forever.
    code = (
        "import subprocess, time\n"
        "subprocess.Popen(['sleep', '30'])\n"  # inherits stdout, holds the pipe
        "time.sleep(30)\n"
    )

    start = time.monotonic()
    result = execute(code, timeout=1.0)
    elapsed = time.monotonic() - start

    assert result.timed_out is True
    assert result.returncode == 124
    assert elapsed < 10.0


def test_generated_mcp_wrapper_does_not_expose_token_argument(tmp_path: Path) -> None:
    from guillotine.build import build

    build(FIXTURE, output_dir=tmp_path)

    server_source = (tmp_path / "mcp" / "server.py").read_text(encoding="utf-8")
    readme = (tmp_path / "mcp" / "README.md").read_text(encoding="utf-8")
    assert "token:" not in server_source
    assert "TOKEN" not in server_source
    assert "token=None" not in readme
