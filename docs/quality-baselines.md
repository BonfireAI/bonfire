# Quality baselines — what the shared gate grades, and every debt it grades against

The shared quality kit is mounted through `.github/workflows/quality.yml`, pinned to a
full commit SHA of `BonfireAI/candyfactory-quality`. Its runner, `cf-gate`, runs one
twelve-stage battery and exits on the worst verdict.

Three of those stages are **ratchets**: they compare the tree against a committed
baseline and fail on anything worse. A ratchet is only honest if every entry in its
baseline carries a written reason and can only ever shrink. Two of the three baselines
are machine-generated files with no room for prose — so their reasons live here.

## The battery, and what it graded on adoption

Measured from the repository root with the pinned kit, on the commit that introduced
this file:

| Stage | Verdict |
|---|---|
| `ruff-check` · `ruff-format` | PASS |
| `cf-sticky-check` · `cf-file-budget` · `cf-mirror-check` · `cf-recursion-check` | PASS |
| `cf-exemptions` | PASS |
| `cf-no-bon-ref` | PASS against the registry below |
| `cf-import-contract` | PASS |
| `mypy` | PASS against `mypy-baseline.txt` |
| `complexipy` | PASS against `complexipy-snapshot.json` |
| `pytest` | PASS |

Before the pin advanced, **`complexipy`, `cf-import-contract` and `cf-no-bon-ref` had
never run against this repository at all** — the pinned kit predated all three. The
three baselines below are therefore adoption baselines: the first honest measurement,
not a concession.

## 1 · `complexipy-snapshot.json` — cognitive-complexity watermarks

Threshold 15. The snapshot records every function above it, and the gate fails on a new
offender or on a baselined offender rising above its recorded watermark.

**One entry added on adoption:**

| Function | Cognitive complexity | Reason |
|---|---|---|
| `src/bonfire/handlers/wizard.py` · `WizardHandler::handle` | 17 | Pre-existing. Surfaced the first time this gauge ever measured this tree; the previous kit pin never invoked complexipy. Recorded at its measured value so the ratchet has a true floor, and shrink-only from here: `handle` may not exceed 17 again. Splitting it is a change to the wizard dispatch path and is owned by that module, not by mounting the gate. |

Nothing was removed and no watermark was raised: the regenerated snapshot differs from
the previous one by exactly this one addition (20 entries / 28 functions → 21 / 29).

**Re-baselining, when a function genuinely improves:** run `complexipy src
--snapshot-create` **from the repository root** (the snapshot path is relative to the
working directory) and commit the shrink. Note the snapshot does not auto-shrink; an
improvement left uncommitted leaves a stale, too-generous watermark.

## 2 · `mypy-baseline.txt` — the zero-new-type-errors ratchet

The baseline is a multiset of normalized mypy findings; anything not in it is new and
fails. Line numbers are normalized to `:0` so unrelated drift cannot resurrect a
finding.

**Change on adoption: four lines rewritten, one dropped. No new type error was
absorbed.**

| Change | Reason |
|---|---|
| `ollama`, `lancedb`, `pyarrow`, `pydantic_ai` — each `Cannot find implementation or library stub for module named "X" [import-not-found]` became `Library stubs not installed for "X" [import-untyped]` | Same four sites, same condition, different wording. The pinned kit's `cf_quality.mypy_normalize` collapses all three shapes a missing third-party import can take onto ONE canonical `import-untyped` line, precisely so the baseline encodes the code and not the machine it was measured on. The previous baseline was written before that normalizer existed. Zero findings added; four re-spelled. |
| One trailing `note: See https://mypy.readthedocs.io/...#missing-imports` line removed | The normalizer strips mypy's once-per-run global stub notes. They are anchored to whichever missing-import site happens to come first, so they relocate between files as imports shift and were a source of phantom new/fixed deltas. Not an error line; nothing is masked by its absence. |

The 49 pre-existing unresolved findings are untouched and remain shrink-only. The four
optional-dependency imports resolve when the `knowledge` extra is installed and are
tracked as ordinary typing debt.

**Re-baselining:** `mypy src --config-file <kit mypy-base.toml> | python -m
cf_quality.mypy_normalize | mypy-baseline sync`, then commit.

## 3 · `no-bon-ref-exemptions.json` — the ticket-reference registry

The law bans internal-tracker ids from the code and config tree: a ticket id is a local
index, meaningless to anyone reading the code. Markdown and `docs/` are out of the
gauge's jurisdiction by design — mapping work to tickets is documentation's function.

On adoption the gauge measured **349 references across 118 files**: 116 test modules,
one developer driver script, and the `reason` prose of the grandfathered entries in
`exemptions.json`. Every one is registered with its own per-file entry and its own
written reason, and `frozen_count` is 118 — adding a 119th requires bumping that number
in the same diff, which is a visible decision.

The entries are **explicit per-file paths, never a glob.** A pattern like `tests/unit/*`
would bless every test file written from now on, which is exactly the unbounded escape
hatch the kit's own documentation warns against. Each blessing prints its path, its line
and its reason on every run, so a registered exemption is loud, never silent.

**Why these are registered rather than scrubbed:** `docs/release-gates.md` already
scopes this debt and states why — the references live in test *file names* as well as in
comments, so cleaning them is a rename sweep across the suite, not a comment sweep. That
sweep is tracked separately from mounting the gate. Mounting the gate first is what
stops the 119th reference; the sweep shrinks the 118.

**Shrinking:** clean a file, delete its entry, lower `frozen_count` by one. The gate
prints ratchet slack whenever `frozen_count` exceeds the live entry count, so a stale
registry announces itself.

## Every one of these gates was proven able to FAIL

A gate that has only ever been observed passing is not known to be a gate. Each was fed
a deliberately broken input and observed to go red, by name, on the commit that mounted
it:

| Gate | Broken input | Result |
|---|---|---|
| `cf-no-bon-ref` | a planted, unregistered tracker reference in a new source file | `FAIL (1 ticket reference(s))`, exit 1, naming file and line |
| `complexipy` | a planted function of cognitive complexity above 15, absent from the snapshot | exit 1: "exceeds 15 but was not part of the snapshot" |
| `complexipy` | a baselined function's watermark lowered below its true value | exit 1: "increased from 16 to 17" |
| `cf-import-contract` | `bonfire.models` importing `bonfire.engine`, which the committed contract forbids | `CONTRACT_BROKEN`, exit 1, naming the forbidden edge |
| `mypy` | a planted `return "str"` from a function declared `-> int` | baseline filter exit 1: "Your changes introduced new violations" |
