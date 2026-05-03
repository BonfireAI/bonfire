# Pipeline Stages

> Reference for the eight handlers that compose the standard Bonfire build
> pipeline. Each stage implements the
> [`StageHandler`](../src/bonfire/protocols.py) protocol and returns an
> envelope; the [`PipelineEngine`](../src/bonfire/engine/pipeline.py)
> walks the DAG in topological order, evaluates quality gates, and bounces
> back on failure where configured.

## Overview

Bonfire's standard build is the eight-stage pipeline produced by
`bonfire.workflows.standard.standard_build()`:

```
scout -> knight -> warrior -> prover -> bard -> wizard -> merge_preflight -> steward
```

The first four stages (scout, knight, warrior, prover) are LLM-driven and
route through the dispatch backend. The last four (bard, wizard,
merge_preflight, steward) are deterministic stage handlers that wrap
external tools (`gh` CLI, git, pytest) and never invoke an LLM.

## Stages reference

### `bard` (publisher)

Publishes the work as a pull request via `gh pr create`. Reads the prover
result for context, attaches the PR number to envelope metadata under
`META_PR_NUMBER`. Bounces nothing -- if `gh` fails, the pipeline halts.

### `wizard` (reviewer)

Posts a structured review on the PR via `gh pr review`. Routes to one of
`approve`, `request_changes`, or `comment`. The `review_approval` gate
reads the verdict from `prior_results[META_REVIEW_VERDICT]`; on
`request_changes` the pipeline bounces back to `warrior` (max iterations
honoured by the warrior stage).

### `merge_preflight` (verifier)

Runs full-suite pytest against a *simulated merged tip* before
`gh pr merge`. Detects cross-wave interactions between sibling PRs
targeting the same base.

**Trigger.** Between `wizard` approve and `steward` merge. Skipped when
the wizard verdict is not `approve` (returns COMPLETED with a `skipped`
result string).

**Inputs.** PR number (from `prior_results` or envelope metadata), base
branch (`master` by default), optional sibling-batch detection toggle.

**Outputs.** Envelope status reflects the verdict; the
[`PreflightClassification`](../src/bonfire/handlers/merge_preflight.py)
verdict-value is recorded under
[`META_PREFLIGHT_CLASSIFICATION`](../src/bonfire/models/envelope.py).
`PRE_EXISTING_DEBT` additionally sets `META_PREFLIGHT_TEST_DEBT_NOTED=True`
so Steward (or a future debt-annotation feature) can post a notice on the
PR.

**Failure classification.** Six deterministic verdicts; first-match-wins
ordering (Sage memo `bon-519-sage-20260428T033101Z.md` §A Q4):

| Verdict                    | Meaning                                                  | Pipeline action               |
|----------------------------|----------------------------------------------------------|-------------------------------|
| `green`                    | All tests pass on the simulated merged tip               | Allow merge                   |
| `pre_existing_debt`        | Failures also fail on `origin/<base>` (no PR diff)       | Allow merge **with annotation** |
| `cross_wave_interaction`   | Failure file or traceback file in an open sibling PR     | **Block merge**               |
| `pure_warrior_bug`         | Failure neither in baseline nor sibling                  | **Block merge**               |
| `pytest_collection_error`  | pytest crash before collection (e.g. ImportError)        | **Block merge**               |
| `merge_conflict`           | PR diff did not apply cleanly to base                    | **Block merge**               |

`merge_conflict` is produced by the handler shell when `git apply --3way`
fails; the other five are produced by the pure
`classify_pytest_run` function (see Sage §D4).

**Sibling-batch behavior.** When 2+ PRs target the same base, the handler
applies *all* open PR diffs to the same scratch worktree in PR-number-
ascending order before running pytest. Cross-wave interactions surface as
`cross_wave_interaction`; the failing PR numbers are recorded on the
classification under `sibling_pr_numbers`.

**Cleanup.** Scratch worktree at
`<repo>/.bonfire-worktrees/preflight/pr-<N>-<8hex>/` torn down on context
exit (try/finally guarantee, mirrors `WorktreeManager`). Cleanup
exceptions are swallowed so a cleanup failure never masks the original
handler error.

**Cost.** `~28s` for the v0.1 baseline pytest run plus `~5s` for the
`gh pr list` + `gh pr diff` queries. The `origin/<base>` baseline-failure
set is cached per base SHA in `baseline_cache` so subsequent preflights
in the same session amortise the baseline run.

**Reserved follow-ups.** Auto-dispatch to a Sage reconciliation lane on
`cross_wave_interaction`, baseline caching across sessions, and
pytest-xdist parallelization are filed as out-of-scope D-FTs in the
merge-preflight PR body (Sage memo §B lines 184-192).

### `steward` (closer)

Merges the PR via `gh pr merge --merge` once preflight is green (or
ALLOW-WITH-ANNOTATION on debt). Closes referenced issues. Reads
`META_PR_NUMBER` from prior_results and verdict from prior_results to
guard against silent dispatch.

### `architect` (analyst, optional)

Pre-pipeline analysis of repository state. Not part of the linear standard
build; consumed by ad-hoc workflows that need a structured architecture
report before scout dispatch.

## Verdict reference

Each verdict is a `PreflightVerdict` enum value. The classification
dataclass round-trips:

- `verdict` -- one of the six values above
- `failing_tests` -- tuple of `FailingTest` (file, classname, name, message, traceback_files)
- `sibling_pr_numbers` -- tuple of intersecting PR numbers (cross-wave only)
- `sibling_detection_status` -- `"ok"` / `"skipped"` / `"error"`
- `pytest_returncode` / `pytest_duration_seconds` / `pytest_stdout_tail`

The classifier is a pure function (no I/O); the handler shell handles
git, gh, and subprocess invocation. See Sage memo
`bon-519-sage-20260428T033101Z.md` §D4 for the full algorithm.

## Pipeline composition

The reference plan is built by `standard_build()`. The merge_preflight
stage carries:

```python
_stage(
    "merge_preflight",
    "verifier",
    handler_name="merge_preflight",
    gates=["merge_preflight_passed"],
    depends_on=["wizard"],
)
```

and `steward.depends_on = ["merge_preflight"]`. The
`merge_preflight_passed` gate (see
[`engine/gates.py`](../src/bonfire/engine/gates.py)) reads the envelope
status:

- `FAILED` -> gate fails with severity `error` -> pipeline halts
- `COMPLETED` + `META_PREFLIGHT_TEST_DEBT_NOTED=True` -> passes with severity `warning`
- `COMPLETED` otherwise -> passes with severity `info`

The handler is NOT registered in `HANDLER_ROLE_MAP` (deterministic
handlers bypass the gamified-display map per Sage §A Q1 Path β).
`MergePreflightHandler` is exported from `bonfire.handlers` directly.
