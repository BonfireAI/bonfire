# Changelog

All notable changes to Bonfire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] -- v0.1.0

### Pipeline

- Added `MergePreflightHandler` -- a deterministic merge-preflight
  pipeline stage that runs full-suite pytest against the simulated
  merged tip before merge. Detects cross-wave interactions between
  sibling PRs targeting the same base (the S007 enum-widening incident
  reproduction case). Six-verdict classifier with first-match-wins
  ordering: `green`, `pre_existing_debt` (allow with annotation),
  `cross_wave_interaction`, `pure_warrior_bug`, `pytest_collection_error`,
  `merge_conflict`. New scratch-worktree primitive
  (`bonfire.git.scratch.ScratchWorktreeFactory`) and quality gate
  (`MergePreflightGate`) wire it into `standard_build()` between
  `wizard` and `herald`. See `docs/pipeline-stages.md` and
  `docs/product/discipline.md`. Sage memo
  `bon-519-sage-20260428T033101Z.md`.

### GitHub client

- Added `GitHubClient.list_open_prs(base, *, exclude=None)` and the
  frozen `PRSummary` Pydantic model. Used by the merge-preflight stage
  for sibling-batch detection. `MockGitHubClient` carries matching
  parity (`set_open_prs` configures canned data;
  `list_open_prs` returns it).

### Models

- Added `META_PREFLIGHT_CLASSIFICATION` and
  `META_PREFLIGHT_TEST_DEBT_NOTED` metadata-key constants to
  `bonfire.models.envelope`.
