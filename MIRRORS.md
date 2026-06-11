# Declared mirrors

Every cross-repo copy in this repo is DECLARED here (the BubbleGum Law's
two-tier DRY: in-repo duplication is gated; cross-repo copies are declared
mirrors, so divergence is a decision, never silence). `cf-mirror-check`
fails the build when a mirrored file's bytes drift from the declared
`content sha256`, when a row is incomplete, or when a `pinned date` is older
than the max pin age (default 90 days) — legalized drift expires.

After editing a mirrored file deliberately: recompute `content sha256`
(`sha256sum <file>`), refresh `pinned parent SHA` against the parent, and
stamp `pinned date` with today's date.

| artifact | local path | parent repo | parent path | pinned parent SHA | content sha256 | pinned date |
|---|---|---|---|---|---|---|
| BubbleGum sticky intro v2 — Seven Pillars (mounted as the CLAUDE.md block; block byte-fidelity gated by cf-sticky-check) | data/sticky-intro.md | candyfactory-canon | decisions/0030-bubblegum-v2-seven-pillars.md | c913c85c06737ec22a2dc8287e1f4bd779643803 | 7dc04712c33f98318563bb2a1b9e60c753b83e257ed5aa403c406911d7d45e07 | 2026-06-11 |

<!-- example row: | sticky-intro | data/sticky-intro.md | candyfactory-canon | decisions/0029-bubblegum-law.md | <full parent commit SHA> | <sha256 of the local file> | 2026-06-10 | -->
