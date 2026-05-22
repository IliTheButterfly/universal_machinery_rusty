"""Subprocess wrapper around the rusty (``plc``) compiler.

Used by the test suite to validate that ST emitted by the parent's
``universal_machinery.emitters.st.emit_program`` parses through
the rusty compiler -- the same shape as the parent's matiec
round-trip harness in ``tests/test_matiec_roundtrip.py``.

Not part of ``RustyBackend.write()`` itself: the backend just
emits ST.  Compile-time validation is a separate concern that
needs the binary on PATH; tests skip cleanly when it isn't.

Install hint::

    # Ubuntu 24.04+ (rusty pre-built needs glibc 2.36+):
    curl -sL https://github.com/PLC-lang/rusty/releases/latest/download/plc-compiler_0.5.0-1_amd64.deb -o /tmp/plc.deb
    sudo dpkg -i /tmp/plc.deb

    # Or download the static-ish binary directly:
    curl -sL https://github.com/PLC-lang/rusty/releases/latest/download/plc-linux-x86_64 -o ~/.local/bin/plc
    chmod +x ~/.local/bin/plc

Honours ``RUSTY_BIN`` env var if set; otherwise looks for ``plc``
on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def find_rusty_bin() -> str | None:
    """Resolve the rusty binary path.

    Returns ``None`` if not found.  Honours ``RUSTY_BIN`` env var
    so users with a non-PATH install (or who want to pin a
    specific version for cert testing) can override.
    """
    return os.environ.get("RUSTY_BIN") or shutil.which("plc")


def run_rusty(
    st_source: str,
    *,
    extra_args: tuple[str, ...] = (),
    timeout: int = 30,
) -> tuple[int, str, str]:
    """Invoke rusty against an ST source string, return
    ``(returncode, stdout, stderr)``.

    Compiles to a transient output file inside a temp dir so we
    don't litter the filesystem; the caller only sees the parse-
    accept signal (returncode + stderr).  ``extra_args`` lets
    callers pass rusty-specific flags (``--check``, ``-o ...``,
    etc.) when those become useful.

    Raises ``FileNotFoundError`` if the binary isn't resolvable;
    callers (typically pytest's ``skipif``) should check
    ``find_rusty_bin()`` first.
    """
    bin_path = find_rusty_bin()
    if bin_path is None:
        raise FileNotFoundError(
            "rusty binary not found; set RUSTY_BIN or put `plc` on PATH"
        )

    with tempfile.TemporaryDirectory() as td:
        st_file = Path(td) / "program.st"
        st_file.write_text(st_source, encoding="utf-8")
        out_file = Path(td) / "program.out"
        cmd: list[str] = [
            bin_path,
            str(st_file),
            "-o", str(out_file),
            *extra_args,
        ]
        result = subprocess.run(
            cmd,
            cwd=td,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
