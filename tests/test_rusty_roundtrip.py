"""rusty (``plc -c``) subprocess round-trip for the parent's ST emitter.

Mirrors the parent project's ``tests/test_matiec_roundtrip.py``
corpus (32 cases as of universal_machinery PR #75).  Every shape
matiec parser-accepts should also compile through rusty's ``plc
-c`` -- and the 3rd-edition OOP shapes matiec rejects should
compile through rusty (covered separately in ``test_smoke.py``).

Skip behaviour
--------------

If ``plc`` (the rusty binary) isn't on ``PATH`` and ``RUSTY_BIN``
isn't set, the whole module skips with an install hint.  Local
machines on Ubuntu 22.04 (glibc 2.35) can't run the v0.5.0
pre-built binary; CI on Ubuntu 24.04 (glibc 2.39) does.

Cases that reference standard-library FBs (``TON``, ``CTU``,
``R_TRIG``, ``SR``, ``ABS`` ...) set ``need_stdlib=True`` so the
runner pulls in the ``.st`` declarations dropped by
``plc-stdlib`` under ``/usr/share/plc/include/``.  Without the
stdlib package those cases fail with ``Unknown type``; with it,
they should resolve cleanly.
"""

from __future__ import annotations

import pytest

from rusty_backend.runner import find_rusty_bin, find_rusty_stdlib, run_rusty
from universal_machinery.builders import (
    abs_, add, and_, assign, case_, case_clause, coil, ctu, eq, fb,
    fcall_expr, fn, for_, if_, jump, label_, move, no, prog, program,
    r_trig, repeat_, ret, rung, sel, sr, ton, var, var_in, var_out,
    while_,
)
from universal_machinery.emitters.st import emit_program
from universal_machinery.il import NamedType, TagType
from universal_machinery.il.ast import Address, Var, VarDirection
from universal_machinery.il.configuration import (
    Configuration, PouInstance, Resource, TaskSpec,
)
from universal_machinery.il.ops import BinaryMath, Compare, Move
from universal_machinery.il.sfc import (
    Action, SfcNetwork, Step, Transition,
)
from universal_machinery.il.types import (
    AliasType, ArrayType, EnumType, StructType, SubrangeType,
)


pytestmark = pytest.mark.skipif(
    find_rusty_bin() is None,
    reason=(
        "rusty (`plc`) binary not found.  Install from "
        "https://github.com/PLC-lang/rusty/releases or set RUSTY_BIN; "
        "the v0.5.0 pre-built needs glibc 2.36+ (Ubuntu 24.04+)."
    ),
)


# -----------------------------------------------------------------------------
# Known rusty (v0.5.0) divergences from the IEC standard / matiec.
# -----------------------------------------------------------------------------
#
# rusty doesn't claim full IEC 61131-3 §3 coverage.  These markers
# capture specific gaps surfaced by the v0.5.0 release so CI tracks
# them as tripwires (an ``XPASS`` if rusty closes the gap means
# we should remove the marker).
#
# Sourced from the rusty CI run on the corpus expansion PR.

#: rusty v0.5.0 doesn't support IEC §6.7 SFC text representation
#: (``INITIAL_STEP`` / ``STEP`` / ``TRANSITION ... END_TRANSITION``).
#: Errors with "Unexpected token: expected KeywordSemicolon" because
#: it tries to parse the SFC block as a regular ST statement.
#: matiec accepts this whole family; rusty doesn't.
_xfail_sfc = pytest.mark.xfail(
    reason=(
        "rusty v0.5.0 doesn't support IEC §6.7 SFC text "
        "representation (INITIAL_STEP / STEP / TRANSITION).  "
        "matiec accepts this -- rusty is a tripwire here in case "
        "the gap closes upstream."
    ),
    strict=False,
)

#: rusty v0.5.0 doesn't support IEC §2.7 system-organisation
#: (``CONFIGURATION ... END_CONFIGURATION``, ``RESOURCE``, ``TASK``,
#: bound ``PROGRAM <inst> WITH <task>``).  Errors with "Unexpected
#: token: expected StartKeyword but found CONFIGURATION".
_xfail_config = pytest.mark.xfail(
    reason=(
        "rusty v0.5.0 doesn't support IEC §2.7 CONFIGURATION / "
        "RESOURCE / TASK blocks.  matiec accepts these -- rusty "
        "is a tripwire here in case the gap closes upstream."
    ),
    strict=False,
)

#: rusty v0.5.0's stdlib (``plc-stdlib`` .deb) uses non-IEC-standard
#: parameter names for SR / LIMIT:
#:   - SR has ``SET1`` / ``RESET`` / ``Q1`` (IEC: ``S1`` / ``R`` / ``Q1``)
#:   - LIMIT has ``MIN`` / ``IN`` / ``MAX`` (IEC: ``MN`` / ``IN`` / ``MX``)
#: Our ST emit follows the IEC standard (matiec accepts), so rusty
#: rejects the named arguments.  Closing this would require either
#: a rusty-specific stdlib remap pass or a rusty upstream fix.
_xfail_stdlib_names = pytest.mark.xfail(
    reason=(
        "rusty v0.5.0's stdlib uses non-IEC-standard parameter "
        "names (SR uses SET1/RESET, LIMIT uses MIN/MAX).  Our ST "
        "emit follows IEC; matiec accepts.  Closing the gap "
        "needs either a backend-specific stdlib remap or a rusty "
        "upstream fix."
    ),
    strict=False,
)


def _need_stdlib_or_skip():
    """Module-level helper: cases that reference IEC §2.5 stdlib FBs
    need ``/usr/share/plc/include/*.st`` resolvable.  Without it,
    rusty fails with ``Unknown type: TON`` (etc.); we skip so the
    failure surfaces as "stdlib missing" rather than "rusty rejects
    our emit"."""
    if find_rusty_stdlib() is None:
        pytest.skip(
            "rusty stdlib include dir not found; install "
            "``plc-stdlib`` (.deb companion package on the rusty "
            "release page) to run stdlib-dependent tests"
        )


def _assert_rusty_accepts(st_source: str, *, need_stdlib: bool = False):
    """Compile ``st_source`` through ``plc -c``; assert clean exit."""
    rc, stdout, stderr = run_rusty(st_source, need_stdlib=need_stdlib)
    assert rc == 0, (
        f"rusty rejected program:\n"
        f"--- stderr ---\n{stderr}\n--- stdout ---\n{stdout}\n"
        f"--- emitted ST ---\n{st_source}"
    )


# -----------------------------------------------------------------------------
# Pure LD and elementary ops (no stdlib needed)
# -----------------------------------------------------------------------------


def test_pure_ld_program_parses_in_rusty():
    """Plain LD: contacts + coil chain.  No FB / stdlib refs."""
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[var("x", TagType.BOOL), var("y", TagType.BOOL)],
             rungs=[rung(no("x"), coil("y"))]),
    ])
    _assert_rusty_accepts(emit_program(p))


def test_ld_with_compare_and_move_parses_in_rusty():
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("speed", TagType.INT),
                 var("last_speed", TagType.INT),
                 var("over_limit", TagType.BOOL),
             ],
             rungs=[
                 rung(Compare(op=">", lhs="speed", rhs="100"),
                       coil("over_limit")),
                 rung(no("over_limit"),
                       Move(src="speed", dst="last_speed")),
             ]),
    ])
    _assert_rusty_accepts(emit_program(p))


def test_ld_with_binary_math_parses_in_rusty():
    """ADD lowers to ``r := a + b;`` in ST.  rusty must accept."""
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("a", TagType.INT),
                 var("b", TagType.INT),
                 var("r", TagType.INT),
             ],
             rungs=[rung(add("a", "b", "r"))]),
    ])
    _assert_rusty_accepts(emit_program(p))


def test_program_with_jump_and_label_parses_in_rusty():
    """Control-flow ops: Jump + Label.  ST emits them as comments
    per IEC §3 (no GOTO statement); rusty must still parse the
    rest of the program."""
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("skip", TagType.BOOL),
                 var("x", TagType.INT),
             ],
             rungs=[
                 rung(no("skip"), jump("AFTER")),
                 rung(no("skip"), coil("skip")),
                 rung(label_("AFTER")),
             ]),
    ])
    _assert_rusty_accepts(emit_program(p))


# -----------------------------------------------------------------------------
# Stateful FB families (§2.5.2.3) -- need stdlib for FB type defs
# -----------------------------------------------------------------------------


def test_ld_with_timer_FB_parses_in_rusty():
    """TON timer instance: ``t1(IN := trigger, PT := T#1000ms);
    done := t1.Q;``.  Mirrors the matiec equivalent."""
    _need_stdlib_or_skip()
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("trigger", TagType.BOOL),
                 var("done", TagType.BOOL),
                 Var(name="t1", data_type=NamedType("TON"),
                     direction=VarDirection.LOCAL),
             ],
             rungs=[rung(no("trigger"), ton("t1", 1000, done_bit="done"))]),
    ])
    _assert_rusty_accepts(emit_program(p), need_stdlib=True)


def test_ld_with_up_counter_FB_parses_in_rusty():
    """CTU up-counter instance per IEC §2.5.2.3.2."""
    _need_stdlib_or_skip()
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("gate", TagType.BOOL),
                 var("reset_bit", TagType.BOOL),
                 var("done", TagType.BOOL),
                 var("cv", TagType.INT),
                 Var(name="counter_inst", data_type=NamedType("CTU"),
                     direction=VarDirection.LOCAL),
             ],
             rungs=[rung(no("gate"),
                           ctu("counter_inst", 5,
                               reset="reset_bit",
                               done_bit="done",
                               accumulator="cv"))]),
    ])
    _assert_rusty_accepts(emit_program(p), need_stdlib=True)


def test_ld_with_r_trig_FB_parses_in_rusty():
    """R_TRIG rising-edge detector per IEC §2.5.2.3.3."""
    _need_stdlib_or_skip()
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("trigger", TagType.BOOL),
                 var("pulse", TagType.BOOL),
                 Var(name="rt", data_type=NamedType("R_TRIG"),
                     direction=VarDirection.LOCAL),
             ],
             rungs=[rung(r_trig(state="rt", clk="trigger", q="pulse"))]),
    ])
    _assert_rusty_accepts(emit_program(p), need_stdlib=True)


@_xfail_stdlib_names
def test_ld_with_sr_bistable_FB_parses_in_rusty():
    """SR set-dominant bistable per IEC §2.5.2.3.3.  xfail on
    rusty v0.5.0: stdlib uses ``SET1`` / ``RESET`` instead of IEC
    ``S1`` / ``R``."""
    _need_stdlib_or_skip()
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("setbtn", TagType.BOOL),
                 var("resetbtn", TagType.BOOL),
                 Var(name="output", data_type=NamedType("SR"),
                     direction=VarDirection.LOCAL),
             ],
             rungs=[rung(sr(q1="output", s1="setbtn", r="resetbtn"))]),
    ])
    _assert_rusty_accepts(emit_program(p), need_stdlib=True)


def test_ld_with_stdlib_call_parses_in_rusty():
    """ABS(x) via the IL's StdFunc op.  Needs stdlib."""
    _need_stdlib_or_skip()
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("v", TagType.REAL),
                 var("av", TagType.REAL),
             ],
             rungs=[rung(abs_("v", "av"))]),
    ])
    _assert_rusty_accepts(emit_program(p), need_stdlib=True)


def test_function_block_call_parses_in_rusty():
    """User-defined FUNCTION_BLOCK + instance call from Main."""
    p = program(subroutines=[
        fb("Average",
           inputs=[var_in("a", TagType.INT), var_in("b", TagType.INT)],
           outputs=[var_out("avg", TagType.INT)],
           rungs=[rung(add("a", "b", "avg"))]),
        prog("Main", main=True,
             local_vars=[
                 var("x", TagType.INT),
                 var("y", TagType.INT),
                 var("m", TagType.INT),
                 var("avg_inst", TagType.INT),
             ],
             rungs=[rung(no("x"), coil("y"))]),
    ])
    _assert_rusty_accepts(emit_program(p))


# -----------------------------------------------------------------------------
# FUNCTION POU + call site
# -----------------------------------------------------------------------------


def test_function_pou_definition_and_call_parses_in_rusty():
    """User-defined FUNCTION + call via ``fcall_expr``."""
    p = program(subroutines=[
        fn("Doubled",
           return_type=TagType.INT,
           inputs=[var_in("x", TagType.INT)],
           st_body=[assign("Doubled", "x")]),
        prog("Main", main=True,
             local_vars=[
                 var("a", TagType.INT),
                 var("result", TagType.INT),
             ],
             st_body=[assign("result", fcall_expr("Doubled", "a"))]),
    ])
    _assert_rusty_accepts(emit_program(p))


# -----------------------------------------------------------------------------
# SFC bodies (§2.6 + §6.7 ST representation)
# -----------------------------------------------------------------------------


@_xfail_sfc
def test_sfc_body_parses_in_rusty():
    """SFC: INITIAL_STEP + STEP + TRANSITION + action.  xfail on
    rusty v0.5.0 (no SFC text-representation support)."""
    sfc_net = SfcNetwork(
        steps=[
            Step("Init", initial=True),
            Step("Run", actions=(Action(qualifier="N", target="active"),)),
        ],
        transitions=[Transition(from_steps=("Init",), to_steps=("Run",))],
    )
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[var("active", TagType.BOOL)],
             sfc=sfc_net),
    ])
    _assert_rusty_accepts(emit_program(p))


@_xfail_sfc
def test_sfc_with_simultaneous_convergence_parses_in_rusty():
    """Multi-from transition: ``FROM (A, B) TO Joined``.  xfail
    on rusty v0.5.0 (no SFC support)."""
    sfc_net = SfcNetwork(
        steps=[
            Step("A", initial=True),
            Step("B", initial=True),
            Step("Joined", actions=(Action(qualifier="N", target="done"),)),
        ],
        transitions=[
            Transition(from_steps=("A", "B"), to_steps=("Joined",)),
        ],
    )
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[var("done", TagType.BOOL)],
             sfc=sfc_net),
    ])
    _assert_rusty_accepts(emit_program(p))


@_xfail_sfc
def test_sfc_with_timed_action_parses_in_rusty():
    """Action with ``time_ms`` emits ``act(L, T#500ms);``.  xfail
    on rusty v0.5.0 (no SFC support)."""
    sfc_net = SfcNetwork(
        steps=[
            Step("Init", initial=True),
            Step("Run", actions=(
                Action(qualifier="L", target="lamp", time_ms=500),
            )),
        ],
        transitions=[Transition(from_steps=("Init",), to_steps=("Run",))],
    )
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[var("lamp", TagType.BOOL)],
             sfc=sfc_net),
    ])
    _assert_rusty_accepts(emit_program(p))


@_xfail_sfc
def test_sfc_with_macrostep_parses_in_rusty():
    """Hierarchical SFC: a Step.macro carrying an inner network
    emits as a plain STEP placeholder at the outer level (PR #66
    in parent).  xfail on rusty v0.5.0 (no SFC support)."""
    inner = SfcNetwork(
        steps=[
            Step("SubInit", initial=True),
            Step("SubRun",
                  actions=(Action(qualifier="N", target="sub_active"),)),
        ],
        transitions=[Transition(from_steps=("SubInit",), to_steps=("SubRun",))],
    )
    outer = SfcNetwork(
        steps=[
            Step("Init", initial=True),
            Step("Macro", macro=inner,
                  actions=(Action(qualifier="S", target="macro_active"),)),
        ],
        transitions=[Transition(from_steps=("Init",), to_steps=("Macro",))],
    )
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("sub_active", TagType.BOOL),
                 var("macro_active", TagType.BOOL),
             ],
             sfc=outer),
    ])
    _assert_rusty_accepts(emit_program(p))


# -----------------------------------------------------------------------------
# User-defined types (§2.3.3)
# -----------------------------------------------------------------------------


def test_struct_type_parses_in_rusty():
    point = StructType(
        name="Point",
        members=(
            Var(name="x", data_type=TagType.INT,
                direction=VarDirection.LOCAL),
            Var(name="y", data_type=TagType.INT,
                direction=VarDirection.LOCAL),
        ),
    )
    p = program(
        user_types=[point],
        subroutines=[
            prog("Main", main=True,
                 local_vars=[
                     var("source", TagType.INT),
                     Var(name="pt", data_type=NamedType("Point"),
                         direction=VarDirection.LOCAL),
                 ],
                 rungs=[rung(move("source", "pt.x"))]),
        ],
    )
    _assert_rusty_accepts(emit_program(p))


def test_array_type_parses_in_rusty():
    vec = ArrayType(name="Vec10", element_type=TagType.INT,
                       bounds=((0, 9),))
    p = program(
        user_types=[vec],
        subroutines=[
            prog("Main", main=True,
                 local_vars=[
                     var("idx", TagType.INT),
                     Var(name="v", data_type=NamedType("Vec10"),
                         direction=VarDirection.LOCAL),
                 ],
                 rungs=[rung(move("idx", "v[0]"))]),
        ],
    )
    _assert_rusty_accepts(emit_program(p))


def test_enum_type_parses_in_rusty():
    color = EnumType(name="Color", values=("RED", "GREEN", "BLUE"))
    p = program(
        user_types=[color],
        subroutines=[
            prog("Main", main=True,
                 local_vars=[
                     Var(name="c", data_type=NamedType("Color"),
                         direction=VarDirection.LOCAL),
                 ],
                 rungs=[rung(move("RED", "c"))]),
        ],
    )
    _assert_rusty_accepts(emit_program(p))


def test_subrange_type_parses_in_rusty():
    percent = SubrangeType(name="Percent", base=TagType.INT,
                              lower=0, upper=100)
    p = program(
        user_types=[percent],
        subroutines=[
            prog("Main", main=True,
                 local_vars=[
                     var("raw", TagType.INT),
                     Var(name="pct", data_type=NamedType("Percent"),
                         direction=VarDirection.LOCAL),
                 ],
                 rungs=[rung(move("raw", "pct"))]),
        ],
    )
    _assert_rusty_accepts(emit_program(p))


def test_alias_type_parses_in_rusty():
    speed = AliasType(name="Speed", base=TagType.REAL)
    p = program(
        user_types=[speed],
        subroutines=[
            prog("Main", main=True,
                 local_vars=[
                     var("raw", TagType.REAL),
                     Var(name="v", data_type=NamedType("Speed"),
                         direction=VarDirection.LOCAL),
                 ],
                 rungs=[rung(move("raw", "v"))]),
        ],
    )
    _assert_rusty_accepts(emit_program(p))


# -----------------------------------------------------------------------------
# ST control flow (§3.3.2)
# -----------------------------------------------------------------------------


def test_st_if_elsif_else_parses_in_rusty():
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("hot", TagType.BOOL),
                 var("cold", TagType.BOOL),
                 var("zone", TagType.INT),
             ],
             st_body=[
                 if_(("hot", [assign("zone", 2)]),
                      ("cold", [assign("zone", 0)]),
                      else_=[assign("zone", 1)]),
             ]),
    ])
    _assert_rusty_accepts(emit_program(p))


def test_st_case_parses_in_rusty():
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("mode", TagType.INT),
                 var("result", TagType.INT),
             ],
             st_body=[
                 case_("mode",
                       case_clause([0], [assign("result", 100)]),
                       case_clause([1], [assign("result", 200)]),
                       else_=[assign("result", 999)]),
             ]),
    ])
    _assert_rusty_accepts(emit_program(p))


def test_st_for_loop_parses_in_rusty():
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("i", TagType.INT),
                 var("total", TagType.INT),
             ],
             st_body=[for_("i", 0, 9, [assign("total", "total")])]),
    ])
    _assert_rusty_accepts(emit_program(p))


def test_st_while_loop_parses_in_rusty():
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("running", TagType.BOOL),
                 var("count", TagType.INT),
             ],
             st_body=[while_("running", [assign("count", "count")])]),
    ])
    _assert_rusty_accepts(emit_program(p))


def test_st_repeat_loop_parses_in_rusty():
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("done", TagType.BOOL),
                 var("counter", TagType.INT),
             ],
             st_body=[repeat_([assign("counter", 5)], until="done")]),
    ])
    _assert_rusty_accepts(emit_program(p))


# -----------------------------------------------------------------------------
# §2.7 system organisation
# -----------------------------------------------------------------------------


@_xfail_config
def test_configuration_resource_task_parses_in_rusty():
    """Full CONFIGURATION / RESOURCE / TASK / PROGRAM-WITH-TASK
    wrapper.  xfail on rusty v0.5.0 (no §2.7 support)."""
    p = program(
        subroutines=[
            prog("Main",
                 local_vars=[
                     var("x", TagType.BOOL),
                     var("y", TagType.BOOL),
                 ],
                 rungs=[rung(no("x"), coil("y"))]),
        ],
        configurations=[
            Configuration(
                name="Plant",
                resources=[
                    Resource(
                        name="PLC1",
                        tasks=[TaskSpec(name="Fast",
                                          interval="T#100ms",
                                          priority=1)],
                        pou_instances=[
                            PouInstance(name="MainInst",
                                          type_name="Main",
                                          task="Fast"),
                        ],
                    ),
                ],
            ),
        ],
    )
    _assert_rusty_accepts(emit_program(p))


# -----------------------------------------------------------------------------
# §2.4.1.1 direct representation + VAR_EXTERNAL ↔ VAR_GLOBAL
# -----------------------------------------------------------------------------


def test_iec_direct_representation_parses_in_rusty():
    """``Var.address = Address('%IX0.0')`` emits inline AT clause."""
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 Var(name="in1", data_type=TagType.BOOL,
                     direction=VarDirection.LOCAL,
                     address=Address("%IX0.0")),
                 Var(name="out1", data_type=TagType.BOOL,
                     direction=VarDirection.LOCAL,
                     address=Address("%QX0.0")),
             ],
             rungs=[rung(no("in1"), coil("out1"))]),
    ])
    out = emit_program(p)
    assert "in1 AT %IX0.0 : BOOL" in out, out
    _assert_rusty_accepts(out)


def test_vendor_address_falls_back_to_comment_in_st():
    """Non-IEC vendor addresses (CLICK ``Y002``) emit as a trailing
    ``(* AT Y002 *)`` comment; rusty sees plain ``lamp : BOOL;``."""
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 Var(name="lamp", data_type=TagType.BOOL,
                     direction=VarDirection.LOCAL,
                     address=Address("Y002")),
                 var("trigger", TagType.BOOL),
             ],
             rungs=[rung(no("trigger"), coil("lamp"))]),
    ])
    out = emit_program(p)
    assert "lamp : BOOL;  (* AT Y002 *)" in out, out
    _assert_rusty_accepts(out)


@_xfail_config
def test_var_external_to_config_global_with_at_clause_parses_in_rusty():
    """§2.4.3 VAR_EXTERNAL bound to §2.7.1 config-scope VAR_GLOBAL
    with an AT %QX0.0 clause.  xfail on rusty v0.5.0 (the
    CONFIGURATION wrapper isn't supported)."""
    from universal_machinery.il.ast import PouKind, Subroutine
    main_pou = Subroutine(
        name="Main",
        kind=PouKind.PROGRAM,
        external_vars=[
            Var(name="LED", data_type=TagType.BOOL,
                direction=VarDirection.EXTERNAL),
        ],
        rungs=[rung(no("LED"), coil("LED"))],
    )
    p = program(
        subroutines=[main_pou],
        configurations=[
            Configuration(
                name="Plant",
                global_vars=[
                    Var(name="LED", data_type=TagType.BOOL,
                        direction=VarDirection.LOCAL,
                        address=Address("%QX0.0")),
                ],
                resources=[Resource(
                    name="PLC1",
                    tasks=[TaskSpec(name="Fast",
                                      interval="T#100ms",
                                      priority=1)],
                    pou_instances=[PouInstance(name="MainInst",
                                                 type_name="Main",
                                                 task="Fast")],
                )],
            ),
        ],
    )
    _assert_rusty_accepts(emit_program(p))


# -----------------------------------------------------------------------------
# §2.5.2 standard library families
# -----------------------------------------------------------------------------


@_xfail_stdlib_names
def test_selection_functions_parse_in_rusty():
    """SEL / MAX / MIN / LIMIT per IEC §2.5.2.8.  xfail on rusty
    v0.5.0: ``LIMIT`` in its stdlib uses ``MIN``/``MAX`` instead
    of IEC ``MN``/``MX``."""
    _need_stdlib_or_skip()
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("g", TagType.BOOL),
                 var("a", TagType.INT),
                 var("b", TagType.INT),
                 var("c", TagType.INT),
                 var("r", TagType.INT),
             ],
             st_body=[
                 assign("r", fcall_expr("SEL", G="g",
                                          IN0="a", IN1="b")),
                 assign("r", fcall_expr("MAX", "a", "b", "c")),
                 assign("r", fcall_expr("MIN", "a", "b", "c")),
                 assign("r", fcall_expr("LIMIT", MN="a",
                                          IN="b", MX="c")),
             ]),
    ])
    _assert_rusty_accepts(emit_program(p), need_stdlib=True)


def test_string_functions_parse_in_rusty():
    """CONCAT / LEN per IEC §2.5.2.9."""
    _need_stdlib_or_skip()
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("a", TagType.STRING),
                 var("b", TagType.STRING),
                 var("joined", TagType.STRING),
                 var("n", TagType.INT),
             ],
             st_body=[
                 assign("joined", fcall_expr("CONCAT", "a", "b")),
                 assign("n", fcall_expr("LEN", "joined")),
             ]),
    ])
    _assert_rusty_accepts(emit_program(p), need_stdlib=True)


def test_type_conversion_functions_parse_in_rusty():
    """INT_TO_REAL / REAL_TO_INT per IEC §2.5.2.1."""
    _need_stdlib_or_skip()
    p = program(subroutines=[
        prog("Main", main=True,
             local_vars=[
                 var("i", TagType.INT),
                 var("r", TagType.REAL),
             ],
             st_body=[
                 assign("r", fcall_expr("INT_TO_REAL", "i")),
                 assign("i", fcall_expr("REAL_TO_INT", "r")),
             ]),
    ])
    _assert_rusty_accepts(emit_program(p), need_stdlib=True)
