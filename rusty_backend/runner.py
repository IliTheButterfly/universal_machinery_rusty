"""Subprocess wrapper around the rusty (``plc``) compiler.

Used by the test suite to validate that ST emitted by the parent's
``universal_machinery.emitters.st.emit_program`` survives the
rusty compiler -- the same shape as the parent's matiec
round-trip harness in ``tests/test_matiec_roundtrip.py``.

The wrapper invokes ``plc -c`` (compile to object, no link) by
default.  The cert-grade signal we care about is "rusty's parser
+ type checker accepts our ST", not "rusty produces a runnable
executable" -- skipping the linker keeps the test surface
focused and avoids needing a working ``main`` / startup code.

Not part of ``RustyBackend.write()`` itself: the backend just
emits ST.  Compile-time validation is a separate concern that
needs the binary on PATH; tests skip cleanly when it isn't.

Install hints
-------------

Ubuntu 24.04+ (rusty pre-built needs glibc 2.36+)::

    sudo apt install ./plc-compiler_0.5.0-1_amd64.deb
    sudo apt install ./plc-stdlib_0.5.0-1_amd64.deb

Or download the static-ish binary directly::

    sudo curl -sSL \
      https://github.com/PLC-lang/rusty/releases/download/v0.5.0/plc-linux-x86_64 \
      -o /usr/local/bin/plc
    sudo chmod +x /usr/local/bin/plc

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


#: Candidate locations for rusty's stdlib include directory.
#: ``plc-stdlib`` (.deb) drops the IEC §2.5 standard-library
#: declarations (``timers.st``, ``counters.st``, ``flanks.st``,
#: ``bistable_functionblocks.st``, etc.) at
#: ``/usr/share/plc/include/`` by default.  We probe a few common
#: prefixes in case the user installed from source.
_RUSTY_STDLIB_CANDIDATES = (
    "/usr/share/plc/include",
    "/usr/local/share/plc/include",
    # Source-build / install-prefix variants
    "/opt/plc/share/include",
)


def find_rusty_stdlib() -> Path | None:
    """Find the rusty stdlib include dir, if any.

    Returns ``None`` if no candidate exists -- the caller should
    invoke ``plc`` without the stdlib include files, which still
    parses simple programs but fails on any reference to a
    standard-library FB (``TON``, ``CTU``, ``R_TRIG``, etc.).
    Tests that exercise the standard library should set
    ``need_stdlib=True`` so the runner fails loudly when it can't
    resolve the include dir.
    """
    for c in _RUSTY_STDLIB_CANDIDATES:
        p = Path(c)
        if p.is_dir() and any(p.glob("*.st")):
            return p
    return None


def run_rusty(
    st_source: str,
    *,
    need_stdlib: bool = False,
    extra_args: tuple[str, ...] = (),
    timeout: int = 60,
) -> tuple[int, str, str]:
    """Invoke rusty against an ST source string, return
    ``(returncode, stdout, stderr)``.

    Compiles with ``-c`` (compile to object, no link) so the test
    doesn't need a ``main`` / startup glue to succeed -- the
    cert-grade signal we want is parse + compile acceptance.

    When ``need_stdlib=True``, the runner looks up the stdlib
    include directory via ``find_rusty_stdlib()`` and adds every
    ``.st`` file under it as an additional input.  Without that,
    references to ``TON`` / ``CTU`` / etc. fail with ``Unknown
    type``.

    ``extra_args`` lets callers pass rusty-specific flags
    (optimisation level, ``--ir`` output mode, etc.) when those
    become useful.

    Raises ``FileNotFoundError`` if the binary isn't resolvable;
    callers (typically pytest's ``skipif``) should check
    ``find_rusty_bin()`` first.  Raises ``LookupError`` if
    ``need_stdlib=True`` but no stdlib include dir is resolvable.
    """
    bin_path = find_rusty_bin()
    if bin_path is None:
        raise FileNotFoundError(
            "rusty binary not found; set RUSTY_BIN or put `plc` on PATH"
        )

    stdlib_files: list[str] = []
    if need_stdlib:
        stdlib = find_rusty_stdlib()
        if stdlib is None:
            raise LookupError(
                "rusty stdlib include dir not found.  Install "
                "``plc-stdlib`` (the .deb companion package on "
                "the rusty release page) or set up an equivalent "
                "install prefix."
            )
        stdlib_files = sorted(str(f) for f in stdlib.glob("*.st"))

    with tempfile.TemporaryDirectory() as td:
        st_file = Path(td) / "program.st"
        st_file.write_text(st_source, encoding="utf-8")
        out_file = Path(td) / "program.o"
        cmd: list[str] = [
            bin_path,
            "-c",                 # compile to object, no link
            str(st_file),
            *stdlib_files,        # IEC standard-library declarations
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
