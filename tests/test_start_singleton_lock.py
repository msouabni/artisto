from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import start


def test_start_singleton_lock_blocks_second_process(tmp_path: Path):
    lock_path = tmp_path / "start.lock"
    repo_root = Path(__file__).resolve().parents[1]

    child_code = textwrap.dedent(
        f"""
        import time
        from pathlib import Path
        import start

        lock_path = Path({str(lock_path)!r})
        ok = start._acquire_singleton_lock(lock_path)
        print("LOCKED" if ok else "FAILED", flush=True)
        time.sleep(2.5)
        start._release_singleton_lock()
        """
    ).strip()

    p = subprocess.Popen(
        [sys.executable, "-c", child_code],
        cwd=str(repo_root),
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Attendre que le child tienne le lock.
        t0 = time.time()
        line = ""
        while time.time() - t0 < 5:
            if p.stdout is None:
                break
            line = (p.stdout.readline() or "").strip()
            if line:
                break
        assert line == "LOCKED", f"child output was: {line!r}"

        assert start._acquire_singleton_lock(lock_path) is False
    finally:
        try:
            start._release_singleton_lock()
        except Exception:
            pass
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()


def test_start_singleton_lock_reacquire_after_release(tmp_path: Path):
    lock_path = tmp_path / "start.lock"
    assert start._acquire_singleton_lock(lock_path) is True
    start._release_singleton_lock()
    assert start._acquire_singleton_lock(lock_path) is True
    start._release_singleton_lock()
