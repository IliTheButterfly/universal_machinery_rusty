"""rusty_backend -- emit IEC §3 Structured Text for the rusty PLC compiler.

rusty (https://github.com/PLC-lang/rusty) is an open-source IEC 61131-3
compiler written in Rust, targeting LLVM.  Unlike matiec it accepts
3rd-edition language features: ``METHOD`` / ``INTERFACE`` / ``EXTENDS``
/ ``IMPLEMENTS`` / ``ABSTRACT``.

This backend wires the parent ``universal_machinery`` project's ST
emitter into the project's ``Backend`` ABC so callers can target the
rusty compiler the same way they'd target any other vendor.

Status: ALPHA.  The backend emits ST and registers as ``"rusty"``;
end-to-end compile validation via the ``plc`` subprocess is exercised
by the test suite when the binary is on PATH.

Public API::

    from rusty_backend import RustyBackend
    backend = RustyBackend()
    backend.write(program, "myprog.st")     # Structured Text

Via the parent registry::

    import rusty_backend  # registers as a side-effect
    from universal_machinery.backends import get_backend
    backend = get_backend("rusty")
"""
from .backend import RustyBackend

__all__ = ["RustyBackend"]
__version__ = "0.1.0"
