"""rusty backend: emit IEC §3 Structured Text for the rusty compiler.

rusty (https://github.com/PLC-lang/rusty) is an IEC 61131-3 -> LLVM
compiler in Rust.  Unlike matiec it accepts 3rd-edition language
features (METHOD / INTERFACE / EXTENDS / IMPLEMENTS / ABSTRACT),
which closes the OOP doubly-blocked gap in the parent project's
cert-conformance posture: see
``docs/IEC_CONFORMANCE.md`` in the parent for the background.

This backend is a thin dispatcher around the parent's existing ST
emitter; compilation itself happens by invoking the ``plc`` binary
out-of-band (see ``rusty_backend.runner`` and the tests).  The
backend's ``write()`` just lowers IL -> .st text; passing the
result through ``plc`` is a separate concern handled by the test
suite when the binary is available.

PLCopen XML output is intentionally not supported here: rusty's
input language is ST, not XML.  Users wanting XML should target
the ``openplc`` backend instead.
"""

from __future__ import annotations

from pathlib import Path

from universal_machinery.backends import Backend, register
from universal_machinery.emitters.st import emit_program
from universal_machinery.il import Program
from universal_machinery.parsers.st_text import parse_program


@register("rusty")
class RustyBackend(Backend):
    """Lower a ``universal_machinery.il.Program`` into a .st file
    that the rusty (PLC-lang) compiler can consume.

    Output format:
      ``.st``   IEC §3 Structured Text

    Capability set is bounded by what rusty's parser accepts;
    notably it includes IEC 3rd-edition OOP, which matiec rejects.
    See ``tests/test_smoke.py`` for the validated corpus.
    """

    name = "rusty"
    #: Capabilities that rusty's compiler parser-accepts via our
    #: ST emit.  Headline difference vs the ``openplc`` backend:
    #: rusty accepts 3rd-edition OOP -- ``methods``, ``interfaces``,
    #: ``extends``, ``implements``, ``abstract``.  See
    #: ``docs/IEC_CONFORMANCE.md`` (parent) for the OOP doubly-blocked
    #: posture that rusty unblocks on its compiler axis.
    capabilities = frozenset({
        "ld",
        "st",
        "sfc",
        "timers",
        "counters",
        "compare",
        "math",
        "call",
        "functions",
        "function_blocks",
        "jump",
        "parallel",
        # 3rd-edition OOP -- accepted by rusty, rejected by matiec.
        "methods",
        "interfaces",
        "extends",
        "implements",
        "abstract",
    })

    def write(self, program: Program, path: str) -> None:
        """Lower ``program`` and write Structured Text to ``path``.

        Only ``.st`` is accepted -- rusty's input language is ST,
        not XML.  Use the ``openplc`` backend for PLCopen TC6 XML
        output.
        """
        p = Path(path)
        suffix = p.suffix.lower()
        if suffix == ".st":
            p.write_text(emit_program(program), encoding="utf-8")
        else:
            raise ValueError(
                f"RustyBackend.write: unsupported suffix {suffix!r} "
                f"for {p}; rusty consumes .st only.  Use the "
                f"``openplc`` backend for .xml output."
            )

    def read(self, path: str) -> Program:
        """Parse a ``.st`` file and return an IL ``Program``.

        Routes through the parent's full-program ST parser
        (``universal_machinery.parsers.st_text.parse_program``,
        added in universal_machinery PR #84).  Scope (v1):
        PROGRAM / FUNCTION / FUNCTION_BLOCK with VAR_INPUT /
        VAR_OUTPUT / VAR_IN_OUT / VAR (LOCAL) blocks + body.

        Out-of-scope shapes (VAR_EXTERNAL / VAR_TEMP /
        VAR_GLOBAL, AT clauses, TYPE blocks, CONFIGURATION, OOP,
        SFC text) raise ``StParseError`` from the parser side
        with a focused message pointing at the missing slice.
        """
        p = Path(path)
        suffix = p.suffix.lower()
        if suffix == ".st":
            return parse_program(p.read_text(encoding="utf-8"))
        else:
            raise ValueError(
                f"RustyBackend.read: unsupported suffix {suffix!r} "
                f"for {p}; rusty consumes .st only.  Use the "
                f"``openplc`` backend for .xml input."
            )
