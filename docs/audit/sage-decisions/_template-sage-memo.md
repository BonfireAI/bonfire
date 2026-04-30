# Sage Decision Memo Template

A blank Sage memo skeleton. Copy this file, rename it
`cluster-NNN-sage-<UTC-stamp>.md`, fill in the sections, and lock it as
the canonical synthesis for a single cluster.

## Conventions for this template

- **Ticket references:** never paste naked tracker IDs in the published
  template prose. Use the placeholder `<ticket-paraphrase>` (plain
  English describes the work; the maintainer's tracker carries the ID).
- **§D8 prose-vs-list parity:** when a memo carries a §D8 test-surface
  section, the closing arithmetic line (`A + B + ... = T tests`) MUST
  match the per-file enumeration `(~N tests)` summed across the listed
  files. Both numbers are load-bearing; divergence is a memo bug.
- **Code samples:** prefer explicit `Optional[T]` (or `T | None`) over
  comment-driven type-checker escapes. The annotation is the contract.

## Standard sections

### A. Cluster summary

One paragraph: what cluster, what problem, what was synthesized.
Cite the upstream knight memos by relative path.

### B. Scope and boundaries

What this decision binds. What it deliberately does not bind.
Out-of-scope items go in §K (deferred).

### C. Knight inputs

Bullet list of the knight memos this synthesis read. One line each:
`<knight-letter> <lens> — <relative path to memo>`.

### D. Locked decisions

The numbered, machine-grep-able decision list. Each item:

- **Dx — `<short-name>`.** One sentence stating the decision.
  Surrounding paragraph explains rationale and edge cases.

When a decision binds a Warrior contract, repeat the contract verbatim
under §G (Warrior contract block).

### E. Open questions

Items the knights flagged that this synthesis does NOT resolve.
Each one becomes a follow-up ticket using the `<ticket-paraphrase>`
form.

### F. Risks and mitigations

What could go wrong with the locked decision; what guards exist.

### G. Warrior contract

The exact files, paths, and content invariants the Warrior must
honor. The downstream RED tests assert against this block, so it must
be unambiguous and self-contained.

### H. Style notes

Any style-guide call-outs the cluster requires. Cite `docs/style.md`
for normative decisions.

### I. Test surface

Tests added, files touched, count per file. If the cluster ships a
non-trivial test surface, add §D8 with the prose-vs-list parity
described above.

### J. Migration / backwards compatibility

Empty when the cluster is greenfield. Otherwise lists what existing
callers must change.

### K. Deferred

Items pulled out of scope. Each one becomes a `<ticket-paraphrase>`
follow-up so nothing is lost.

---

**End of template.** Replace this line with the synthesized memo body.
