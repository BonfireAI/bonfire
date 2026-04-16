# Release Policy

## Scope

This policy governs how `bonfire-ai` is versioned, tagged, and published
to PyPI during the pre-release and v0.1 development periods.

## Pre-release Period

`bonfire-ai` is in pre-release until Wave 9.2 of the v0.1 plan lands.

During this period:

- **Versions follow PEP 440 alpha numbering.** `0.0.0a1`, `0.0.0a2`, ...
- **PyPI publications are name-reservation only.** Each published wheel
  is a stub whose `bonfire` command prints a pre-release notice and
  exits. No functional features ship to PyPI.
- **No GitHub release tags.** The repository's releases page remains
  empty until the first release candidate.
- **README carries a pre-release banner.** Every landing page and
  README.md preview on PyPI shows a clear "do not use" notice.

## Release Candidate Period

When Wave 8 (documentation polish) is complete and Wave 9 (smoke tests)
is in flight:

- Versions advance to `0.1.0rc1`, `0.1.0rc2`, ...
- GitHub release tags begin at `v0.1.0rc1`.
- The pre-release banner is reworded to a release-candidate notice with
  a known-issues list.
- PyPI publications remain alpha-classified; `pip install bonfire-ai`
  without `--pre` still yields `0.0.0a1`.

## v0.1.0 Release

The first functional release is cut when:

- Wave 9.1 end-to-end smoke tests pass in CI on `main`.
- Wave 9.2 release preparation is merged.
- All four trust-triangle components (W1.5.1 interfaces, W1.5.3 default
  allow-list floor, W4.1 user-configurable allow-lists, W4.2 default
  security hook set) are on `main`.

At that point:

- Version becomes `0.1.0`.
- GitHub release tag `v0.1.0` is published.
- The PyPI classifier advances from `Development Status :: 3 - Alpha`
  to `Development Status :: 4 - Beta`.
- README pre-release banner is removed.

## Yank Policy

Any release shown to have a security defect in the trust-triangle
components is yanked from PyPI within one business day of verification.
Users receive a `pip install` warning pointing to the fixed release.

## Signing

Release artifacts are signed with a maintainer GPG key once v0.1.0 is
cut. Pre-release artifacts are unsigned.
