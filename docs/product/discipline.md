# Bonfire Disciplines

> **Disciplines** are the load-bearing guarantees Bonfire makes to its
> users. Each discipline ships as a deterministic pipeline stage that
> runs on every PR -- not as a Wizard recommendation or a CI add-on, but
> as part of the canonical eight-stage build.

## Why discipline?

A pipeline that *recommends* a check is one that lets the check slip.
The S007 incident is the canonical reproduction case: two sibling PRs
widened overlapping interfaces (an enum and a schema), each one's scoped
pytest run passed, both PRs merged, the next full-suite pytest on
`v0.1` tip surfaced 23 failures across schema/persona/role/config tests.
None of the 23 were in either Warrior's scoped set. A pre-merge
full-suite would have caught all 23 -- but only if it ran *deterministically*,
not at human discretion.

Bonfire's answer is to put the check **inside** the pipeline. Disciplines
are stages, not advice.

## Disciplines list

### Merge Preflight Discipline

> Bonfire never merges a PR until a full-suite pytest run on the
> simulated merged tip passes. When two sibling PRs target the same
> branch, both diffs are applied in the same scratch worktree and
> verified together. Cross-wave interactions are blocked at preflight,
> not discovered post-merge.

**Where it lives.** The `merge_preflight` stage of `standard_build()`,
between `wizard` (review approval) and `herald` (the merge button). See
[`docs/pipeline-stages.md`](../pipeline-stages.md) for the full
reference.

**What it guarantees.**

1. The PR's diff applies cleanly to `origin/<base>` (else `merge_conflict`,
   pipeline halts).
2. Full-suite pytest passes against the simulated merged tip (else
   `pure_warrior_bug` or `pytest_collection_error`, pipeline halts).
3. When sibling PRs target the same base, *all* open sibling diffs are
   applied to the same scratch worktree before pytest runs. A failure
   whose file is in a sibling PR's diff is classified as
   `cross_wave_interaction` and the pipeline halts -- the PR is *not*
   merged into a state that another open PR will break.
4. Pre-existing failures (failures that also fail on `origin/<base>`) are
   classified as `pre_existing_debt` and surface as a debt annotation;
   they do **not** block the merge (Sage memo `bon-519-sage-20260428T033101Z.md`
   §A Q6 ratified ALLOW-WITH-ANNOTATION). The principle: a PR is not
   responsible for failures it inherits.

**What it forecloses.** The S007 absorption trap (the Wizard editing
test files to chase moving targets), the silent post-merge red main, the
"works on my branch" cross-wave incident, and the audit-trail wobble
that comes with hand-coordinated reverts.

**Where to look in the codebase.**

- Stage handler: [`src/bonfire/handlers/merge_preflight.py`](../../src/bonfire/handlers/merge_preflight.py)
- Scratch primitive: [`src/bonfire/git/scratch.py`](../../src/bonfire/git/scratch.py)
- Quality gate: [`src/bonfire/engine/gates.py`](../../src/bonfire/engine/gates.py)
  (class `MergePreflightGate`)
- Classification metadata: `META_PREFLIGHT_CLASSIFICATION`,
  `META_PREFLIGHT_TEST_DEBT_NOTED` in
  [`src/bonfire/models/envelope.py`](../../src/bonfire/models/envelope.py)
- Sage decision memo: `bon-519-sage-20260428T033101Z.md` §A Q4-Q7, §D2-D6

## How to add a discipline

A new discipline is a new stage in `standard_build()` plus a deterministic
handler. The pattern from the merge-preflight stage:

1. Identify the destructive operation the discipline guards
   (merge / deploy / release).
2. Make the gate deterministic -- no LLM judgment on the gate itself.
   The Wizard reviews; the discipline-stage handler decides.
3. Add a handler module under `src/bonfire/handlers/`, return a
   structured `ErrorDetail` on failure (never raise).
4. Register the stage in `standard_build()`. Re-wire downstream
   `depends_on`.
5. Add a `Gate` in `engine/gates.py`. Wire it via `gates=[...]` on the
   stage spec.
6. Document the discipline here. The user-facing pitch comes first;
   implementation links come after.

The point is to make the discipline impossible to skip without changing
the pipeline definition -- which is itself a gated, audited change.
