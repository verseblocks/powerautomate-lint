# powerautomate-lint

Lint Power Automate cloud flows offline. Resolves every expression reference against the flow's own action graph, so it can tell you that `outputs('Get_a_row')` names an action that isn't there.

No tenant. No credentials. No network. Nothing is uploaded.

```bash
pip install powerautomate-lint
palint ./src
```

```
src/Workflows/Approvals-1A2B3C.json: error: [PAL101] Approvals: outputs('Get_Manager') names no action or trigger in this flow
src/Workflows/Approvals-1A2B3C.json: warning: [PAL102] Approvals: outputs('Send_Email') resolves only because the runtime ignores case; the action is named 'Send_email'

1 flows, 47 expressions, 1 errors, 1 warnings, 0 notes
```

Point it at an unpacked solution, a `Workflows` folder, a solution `.zip`, or a single flow `.json`.

## Why this exists

Microsoft's own flow analysis works by uploading your solution to a regional endpoint. If you audit other people's environments under NDA, you cannot do that, so the analysis has to happen on your machine.

And the specific thing nothing else does offline is resolve references. Plenty of tools will tell you how many actions a flow has. None of them will tell you that an expression names an action that does not exist, because doing that means building the action graph first, descending through every container shape, and then matching names the way the runtime matches them.

## Rules

| Rule | Severity | What it catches |
| --- | --- | --- |
| `PAL101` | error | `outputs()`, `body()`, `actions()`, `result()` or `items()` naming something that isn't in the flow |
| `PAL102` | warning | A reference that resolves only because the runtime ignores case |
| `PAL103` | error | `variables('x')` with no Initialize variable anywhere in the flow |
| `PAL106` | error | A function name that isn't in the Workflow Definition Language catalogue |
| `PAL107` | note | A function cased differently from the documentation, like `tolower` for `toLower` |

`PAL101` matters because an unresolved reference does not fail at run time. It evaluates to null. The flow reports success and passes a missing value downstream, which is why these survive in production for years.

## Two things we found writing it

Both are asserted in the test suite against Microsoft's own flows, so you can check them yourself.

**Three expressions in the CoE Starter Kit only parse if you treat U+00A0 as whitespace.** Someone separated `concat()` arguments with a no-break space instead of a space, in `AdminSyncTemplatev3CoESolutionMetadata` and `SetupWizardUpdateDataflowEnvironment`. Those flows run. The runtime accepts it and no documentation mentions it. Remove U+00A0 from this lexer's whitespace set and exactly three expressions stop parsing, which is `test_removing_nbsp_from_whitespace_breaks_exactly_three_expressions`.

**Twelve references across eight CoE flows resolve only because the runtime ignores case**, 67 occurrences in total. `CLEANUPHELPER-SolutionObjects` calls `outputs('Get_Flow_To_Remove')` against an action named `Get_Flow_to_Remove`. There are four more in that one flow, plus `Add_HTTP_Request` against `add_HTTP_Request`, `Get_app_from_Inventory` against `Get_App_from_Inventory`, and `Apply_to_each_new_User_to_Add` against `Apply_to_each_New_User_to_Add` in two flows that account for 54 of the occurrences between them. They work today. They break the moment anyone renames the action, and nothing in the designer warns you. That's `PAL102`.

## Use it in CI

`palint` emits SARIF, so GitHub renders findings on the diff.

```yaml
- run: pip install powerautomate-lint
- run: palint ./src --format sarif -o palint.sarif --fail-on error
  continue-on-error: true
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: palint.sarif
```

Exit codes: `0` clean, `1` something met `--fail-on`, `2` nothing could be scanned. The third one matters. A build that finds no flows is not a passing build.

## The expression parser on its own

The parser has no dependencies and is a supported entry point, if you want to build something else on it.

```python
from powerautomate_lint.expression import parse, parse_template

parse("concat('a', outputs('x'))")
# FunctionCall(name='concat', args=(Literal('a'), FunctionCall(name='outputs', ...)), ...)

parse_template("Hi @{variables('name')}, you have @{variables('count')} items").interpolations
# two Interpolation nodes, each with an AST and an offset into the original string
```

It handles the things that trip up a regex: `@@` escaping, `''` quote doubling inside string literals, and braces inside string literals inside an interpolation, so `@{concat('{', variables('x'), '}')}` parses correctly instead of ending at the first `}`.

Syntax errors carry a code and a character offset:

```python
from powerautomate_lint.expression import ExpressionSyntaxError
try:
    parse("concat('a',)")
except ExpressionSyntaxError as e:
    print(e.code, e.offset)   # trailing-comma 11
```

## What it does not do

Not a structure or cost linter. It won't count your actions, flag nested loops, or comment on your concurrency settings. [pp-lint](https://github.com/alvesmaia/pp-lint) does that kind of check offline already and there's no sense duplicating it. The scope here is reference integrity, deliberately.

It reads what the definition says, not what a connector does at run time. If an action's output schema changed, `outputs('X')?['body/thing']` still looks fine here.

No tenant means no run history, no connection health, and no licence analysis. Those need an API.

## Development

```bash
git clone https://github.com/verseblocks/powerautomate-lint
cd powerautomate-lint
pip install -e ".[dev]"
pytest            # 125 tests, no network
ruff check .
mypy
```

Six real flows from the CoE Starter Kit are committed under `fixtures/vendor/coe/`, unmodified, with a manifest recording each file's upstream path and SHA-256. The suite verifies those hashes on every run, so the fixtures can't quietly drift into agreeing with the code. `tools/fetch_corpus.py` pulls all 239 flows for the deeper opt-in tests:

```bash
python tools/fetch_corpus.py
pytest -m corpus
```

The assertion that keeps this honest is that `PAL101`, `PAL103` and `PAL106` must be completely silent across every Microsoft-authored flow. An early version that read only the top level of `definition.actions` produced 449 false errors, and a version that resolved `items()` without case folding produced 55. Both passed the hand-written fixtures. Neither survived the corpus.

## Licence

MIT. Test fixtures are MIT from the Microsoft CoE Starter Kit, attributed in `NOTICE`.

Built by [VerseBlocks](https://www.verseblocks.com).
