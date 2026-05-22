# rusty_backend

Backend for [universal_machinery](https://github.com/IliTheButterfly/universal_machinery) targeting the [rusty (PLC-lang) compiler](https://github.com/PLC-lang/rusty).

rusty is an IEC 61131-3 -> LLVM compiler in Rust.  Unlike matiec, rusty accepts the **3rd-edition language features** -- `METHOD`, `INTERFACE`, `EXTENDS`, `IMPLEMENTS`, `ABSTRACT`.  That makes it the missing accredited reference compiler for the parent project's OOP cert claim, which matiec rejects.

## Usage

```python
from rusty_backend import RustyBackend

backend = RustyBackend()
backend.write(program, "myprog.st")     # IEC §3 Structured Text
```

Or via the parent's backend registry:

```python
import rusty_backend  # registers as side-effect
from universal_machinery.backends import get_backend
backend = get_backend("rusty")
```

The backend itself only emits ST.  Validating that the emitted ST compiles through rusty's `plc` binary is a separate concern handled by the test suite when the binary is on PATH.

## Capabilities

Same headline IEC 2nd-edition surface as the `openplc` backend (LD, ST, SFC, timers, counters, functions, function blocks, jump, parallel), **plus** the 3rd-edition OOP capabilities:

| OOP capability | rusty | matiec / openplc |
|---|---|---|
| `methods` | yes | no -- matiec rejects `METHOD` |
| `interfaces` | yes | no -- matiec rejects `INTERFACE` |
| `extends` | yes | no -- matiec rejects `EXTENDS` |
| `implements` | yes | no -- depends on INTERFACE |
| `abstract` | yes | no -- depends on METHOD |

Reading `.st` back into IL is supported via the parent's `parse_program` (v1, since universal_machinery PR #84) — round-trips PROGRAM / FUNCTION / FUNCTION_BLOCK with VAR_INPUT / VAR_OUTPUT / VAR_IN_OUT / VAR (LOCAL) blocks + body.  Out-of-scope shapes (VAR_EXTERNAL / VAR_TEMP / VAR_GLOBAL, AT clauses, TYPE blocks, CONFIGURATION, OOP, SFC text) raise `StParseError`; round-trip via the `openplc` backend's `.xml` path for those.

## Dependencies

Requires the parent `universal_machinery` project on the Python path -- this backend dispatches all lowering to it.  In a local checkout:

```bash
pip install -e ./universal_machinery[dev]
pip install -e ./universal_machinery/backends/rusty[dev]
```

## Installing the rusty compiler

The subprocess round-trip tests need the `plc` binary on `PATH`.  Pre-built binaries are linked from each rusty release: <https://github.com/PLC-lang/rusty/releases>.

```bash
# Linux (needs glibc 2.36+; Ubuntu 24.04 or newer):
curl -sL https://github.com/PLC-lang/rusty/releases/latest/download/plc-linux-x86_64 -o ~/.local/bin/plc
chmod +x ~/.local/bin/plc
plc --version

# Or via the apt .deb package:
curl -sL https://github.com/PLC-lang/rusty/releases/download/v0.5.0/plc-compiler_0.5.0-1_amd64.deb -o /tmp/plc.deb
sudo dpkg -i /tmp/plc.deb
```

Tests honour `RUSTY_BIN=/path/to/plc` if you keep it outside `PATH`.

## License

AGPL-3.0-or-later, same as the parent project.
See [`LICENSE`](LICENSE) for the full text.

Contributions require a `Signed-off-by` line per the
[Developer Certificate of Origin](https://developercertificate.org/).
