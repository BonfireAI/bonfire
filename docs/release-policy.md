# Release Policy

## Scope

This policy governs how `bonfire-ai` is versioned, tagged, and published
to PyPI during the pre-release and v0.1 development periods.

## Current Status

`bonfire-ai` is at stable `1.0.1` (per `pyproject.toml`), PyPI classifier `Development Status :: 5 - Production/Stable`. See [`CHANGELOG.md`](../CHANGELOG.md) for the per-release record.

**ARCHIVED — v0.1.0 gate bypassed by the opinion-package pivot 2026-05-17 (BON-610 closed Done). Preserved per `history-is-sacred`; the subsequent release line is on `main` with `v1.0.0` and `v1.0.1` (commit `3bbfbe5`) already shipped.**

Historically: `bonfire-ai` WAS in alpha at version `0.1.0a4` (per
`pyproject.toml` at the time). The original `0.1.0` tag shipped on
2026-04-28; on 2026-05-03 the version label was reverted to `0.1.0a1`
to honestly reflect that the release-gate items in
[`docs/release-gates.md`](release-gates.md) remained open, and the
alpha series advanced to `0.1.0a4`. Stable `v0.1.0` was the planned
future tag once the release-gate items cleared. The opinion-package
pivot of 2026-05-17 cut a `1.0.0` stable tag directly off `main`
(followed by `1.0.1` at commit `3bbfbe5`), bypassing the v0.1.0
release ladder wholesale.

The two sections below ("Pre-release Period" and "Release Candidate
Period") describe earlier alpha-numbering phases (`0.0.0a1`, `0.0.0a2`,
…) that ran during v0.1 development. They are retained as historical
reference. The "v0.1.0 Release" section captures the gates that would
have governed cutting the stable tag had the pivot not bypassed it;
preserved per `history-is-sacred`.

## Pre-release Period

> **Historical.** This phase is complete. `bonfire-ai` was in
> pre-release until Wave 9.2 of the v0.1 plan landed; `0.1.0` shipped
> on 2026-04-28.

`bonfire-ai` is in pre-release until Wave 9.2 of the v0.1 plan lands.

During this period:

- **Versions followed PEP 440 alpha numbering.** `0.0.0a1`, `0.0.0a2`, ... (this earlier pre-release phase ran during v0.1 development; the current alpha series is `0.1.0aN`.)
- **PyPI publications are name-reservation only.** Each published wheel
  is a stub whose `bonfire` command prints a pre-release notice and
  exits. No functional features ship to PyPI.
- **No GitHub release tags.** The repository's releases page remains
  empty until the first release candidate.
- **README carries a pre-release banner.** Every landing page and
  README.md preview on PyPI shows a clear "do not use" notice.

## Release Candidate Period

> **Historical.** This phase is complete. The release-candidate window
> closed when `0.1.0` was cut on 2026-04-28.

When Wave 8 (documentation polish) is complete and Wave 9 (smoke tests)
is in flight:

- Versions advance to `0.1.0rc1`, `0.1.0rc2`, ...
- GitHub release tags begin at `v0.1.0rc1`.
- The pre-release banner is reworded to a release-candidate notice with
  a known-issues list.
- PyPI publications remain alpha-classified; `pip install bonfire-ai`
  without `--pre` resolves to the most recent stable release (currently
  `0.1.0`), not the in-flight rc.

## v0.1.0 Release

**ARCHIVED — the v0.1.0 release gate was bypassed by the opinion-package pivot on 2026-05-17 (BON-610 closed Done). The gate items below are preserved per `history-is-sacred`; the active release line ships from `main` with `v1.0.0` and `v1.0.1` (commit `3bbfbe5`) already published.**

The first functional release WAS to be cut when:

- Wave 9.1 end-to-end smoke tests pass in CI on `main`.
- Wave 9.2 release preparation is merged.
- All four trust-triangle components are on `main`: the four
  `@runtime_checkable` extension protocols (`AgentBackend`,
  `VaultBackend`, `QualityGate`, `StageHandler`), the default
  allow-list floor and the `ToolPolicy` extension Protocol (W4.1 —
  the Protocol seam IS the user-configurable surface; no TOML loader
  ships in v0.1), and the default security hook set (W4.2).

At that point:

- Version was to become `0.1.0`.
- GitHub release tag `v0.1.0` was to be published.
- The PyPI classifier was to advance from `Development Status :: 3 - Alpha`
  to `Development Status :: 4 - Beta`.
- README pre-release banner was to be removed.

In practice the pivot of 2026-05-17 cut a `1.0.0` stable tag directly
off `main` (followed by `1.0.1` at commit `3bbfbe5`); the package's
Development Status now reflects stable, the README pre-release banner
was retired with the v1 ship, and the gate items above closed unmet by
design — preserved here for history.

## Yank Policy

Any release shown to have a security defect in the trust-triangle
components is yanked from PyPI within one business day of verification.
Users receive a `pip install` warning pointing to the fixed release.

## Signing

Release artifacts were originally to be signed with a maintainer GPG
key once v0.1.0 was cut; pre-release artifacts were unsigned. This
rule was relaxed in PR #141 for the v1.0.0 / v1.0.1 ship under the
opinion-package pivot — those tags are annotated-but-unsigned. New
signing policy travels with the active release line on `main`.
