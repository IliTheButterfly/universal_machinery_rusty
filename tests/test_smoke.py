"""Smoke + round-trip tests for rusty_backend.

API-shape tests run unconditionally.  The subprocess round-trip
tests against the ``plc`` binary skip cleanly when the binary
isn't on PATH (matches the parent project's matiec harness).
"""
from __future__ import annotations

import pytest


# -----------------------------------------------------------------------------
# Public API surface (runs unconditionally; no rusty install needed)
# -----------------------------------------------------------------------------


def test_package_imports_cleanly():
    import rusty_backend
    assert rusty_backend.__all__ == ["RustyBackend"]


def test_version_exported():
    import rusty_backend
    assert isinstance(rusty_backend.__version__, str)
    assert rusty_backend.__version__


def test_backend_class_instantiable():
    from rusty_backend import RustyBackend
    backend = RustyBackend()
    assert backend is not None


def test_backend_advertises_name():
    from rusty_backend import RustyBackend
    assert RustyBackend.name == "rusty"


def test_backend_capabilities_includes_oop():
    """Headline capability difference vs the ``openplc`` backend:
    rusty accepts 3rd-edition OOP.  This pins that the capability
    set explicitly advertises the OOP capabilities -- consumers
    checking ``backend.supports("methods")`` etc. need this to
    answer truthfully."""
    from rusty_backend import RustyBackend
    assert isinstance(RustyBackend.capabilities, frozenset)
    for cap in ("methods", "interfaces", "extends", "implements", "abstract"):
        assert cap in RustyBackend.capabilities, (
            f"RustyBackend must advertise {cap!r} (the headline "
            f"difference vs matiec/openplc backends)"
        )


def test_backend_registered_in_universal_machinery():
    """``@register('rusty')`` makes the backend discoverable via
    ``get_backend('rusty')`` after package import."""
    import rusty_backend  # noqa: F401  (side-effect: registers)
    from universal_machinery.backends import get_backend, registered_names
    assert "rusty" in registered_names()
    backend = get_backend("rusty")
    assert backend.__class__.__name__ == "RustyBackend"


def test_write_xml_rejected_with_pointer_to_openplc(tmp_path):
    """rusty's input language is ST, not XML.  Rather than silently
    producing the wrong format, ``.xml`` raises ``ValueError`` with
    a pointer to the ``openplc`` backend (which does support XML)."""
    from rusty_backend import RustyBackend
    from universal_machinery.builders import program, prog
    backend = RustyBackend()
    out = tmp_path / "prog.xml"
    with pytest.raises(ValueError, match="openplc"):
        backend.write(program(subroutines=[prog("Main", main=True)]), str(out))


def test_read_raises_not_implemented(tmp_path):
    """No full-program ST parser upstream yet; rejecting cleanly
    beats silently returning an empty Program."""
    from rusty_backend import RustyBackend
    out = tmp_path / "prog.st"
    out.write_text("PROGRAM Main\nEND_PROGRAM\n")
    backend = RustyBackend()
    with pytest.raises(NotImplementedError):
        backend.read(str(out))


# -----------------------------------------------------------------------------
# rusty subprocess round-trip -- skipped when ``plc`` isn't on PATH
# -----------------------------------------------------------------------------


from rusty_backend.runner import find_rusty_bin

rusty_skip = pytest.mark.skipif(
    find_rusty_bin() is None,
    reason=(
        "rusty (`plc`) binary not found.  Install from "
        "https://github.com/PLC-lang/rusty/releases or set RUSTY_BIN; "
        "needs glibc 2.36+ on Linux (Ubuntu 24.04+)."
    ),
)


def _representative_program():
    """A small program exercising LD + ST + FUNCTION + TON so the
    subprocess round-trip covers the headline IL surface in one
    shot."""
    from universal_machinery.builders import (
        assign, coil, fn, no, prog, program, rung, ton, var, var_in,
    )
    from universal_machinery.il import NamedType, TagType
    from universal_machinery.il.ast import Var, VarDirection
    return program(subroutines=[
        fn("Doubled",
           return_type=TagType.INT,
           inputs=[var_in("x", TagType.INT)],
           st_body=[assign("Doubled", "x")]),
        prog("Main", main=True,
             local_vars=[
                 var("trigger", TagType.BOOL),
                 var("done", TagType.BOOL),
                 Var(name="t1", data_type=NamedType("TON"),
                     direction=VarDirection.LOCAL),
             ],
             rungs=[
                 rung(no("trigger"),
                       ton("t1", 1000, done_bit="done")),
                 rung(no("done"), coil("done")),
             ]),
    ])


def _oop_program():
    """A 3rd-edition OOP program: an FB with a METHOD and an
    INTERFACE that the FB IMPLEMENTS.  The point: matiec rejects
    this whole shape; rusty should accept it.  This is the
    cert-grade signal that rusty unlocks the OOP doubly-blocked
    posture in the parent project."""
    from universal_machinery.builders import (
        abstract_method, fb, interface, method, prog, program, var_in, var_out,
    )
    from universal_machinery.il import TagType
    return program(
        interfaces=[interface(
            name="IDoubler",
            methods=[abstract_method(
                "Compute",
                inputs=[var_in("x", TagType.INT)],
                outputs=[var_out("y", TagType.INT)],
            )],
        )],
        subroutines=[fb(
            "Doubler",
            implements=["IDoubler"],
            methods=[method(
                "Compute",
                inputs=[var_in("x", TagType.INT)],
                outputs=[var_out("y", TagType.INT)],
            )],
        ), prog("Main", main=True)],
    )


@rusty_skip
def test_rusty_accepts_basic_ld_st_function_program():
    """Headline round-trip: a representative LD + TON + FUNCTION
    program emitted by the parent's ST emitter compiles cleanly
    through rusty's ``plc -c``.  ``need_stdlib=True`` pulls in
    the IEC §2.5 stdlib declarations so ``TON`` resolves.  Returns
    the same parse-accept signal as the matiec harness in the
    parent project."""
    from rusty_backend import RustyBackend
    from rusty_backend.runner import find_rusty_stdlib, run_rusty
    from universal_machinery.emitters.st import emit_program
    if find_rusty_stdlib() is None:
        pytest.skip(
            "rusty stdlib include dir not found; can't resolve TON.  "
            "Install ``plc-stdlib`` (.deb companion package on the "
            "rusty release page)"
        )
    st_source = emit_program(_representative_program())
    rc, stdout, stderr = run_rusty(st_source, need_stdlib=True)
    assert rc == 0, (
        f"rusty rejected the basic LD+ST+FUNCTION program:\n"
        f"--- stderr ---\n{stderr}\n--- stdout ---\n{stdout}"
    )
    # Backend instance shouldn't be unused; touch it so import
    # side-effects (registry registration) get exercised.
    assert RustyBackend.name == "rusty"


@rusty_skip
def test_rusty_accepts_3rd_edition_oop():
    """The cert-grade reason this backend exists: rusty accepts
    IEC 3rd-edition OOP (``METHOD`` / ``INTERFACE`` / ``IMPLEMENTS``)
    that matiec rejects at the parser level.  A clean compile of
    the OOP shape moves the parent project's ``METHOD`` /
    ``INTERFACE`` rows in ``docs/IEC_CONFORMANCE.md`` from
    "doubly-blocked" (no v2.02 XSD + matiec rejects) to
    "blocked on XSD only" (rusty validates the ST-emit path).

    See the parent's
    ``tests/test_matiec_roundtrip.py`` for the matiec-rejection
    side of the asymmetry.

    No stdlib needed -- the OOP shape doesn't reference any
    standard-library FBs."""
    from rusty_backend.runner import run_rusty
    from universal_machinery.emitters.st import emit_program
    st_source = emit_program(_oop_program())
    rc, stdout, stderr = run_rusty(st_source)
    assert rc == 0, (
        f"rusty rejected the OOP program (METHOD/INTERFACE/"
        f"IMPLEMENTS shape):\n"
        f"--- stderr ---\n{stderr}\n--- stdout ---\n{stdout}\n"
        f"--- emitted ST ---\n{st_source}"
    )
