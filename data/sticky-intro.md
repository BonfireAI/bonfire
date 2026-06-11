## The BubbleGum Law (form)

This repository is governed by **the BubbleGum Law** — CandyFactory's form law. It sticks:
if you are reading this to write code here, you are now carrying it.

- **Budgets, not vibes:** functions stay ≤ CC 10 and ≤ 50 statements; new files stay ≤ 500
  lines. Existing offenders are baselined and may only shrink (ratchet — never a world-refactor).
- **Reuse before reinvention:** search this repo before writing. In-repo duplication fails the
  gate; a cross-repo copy must declare its mirror ("mirrors <repo>'s <artifact>").
- **Recursion is declared, not banned:** structurally-recursive data with a stated bound,
  marked as such — or it fails.
- **New code type-checks clean,** and failure speaks typed errors (the Elegance Law).
- **Splitting a file is design, not evasion:** two incohesive 350-line halves satisfy nothing;
  the gate measures, review judges.

In CandyFactory CI — and inside Bonfire burns — this law is a **gate**: comply by design, not
by suppression; any `# noqa` / `# nosec` carries a written reason and a human's blessing.
Everywhere else, treat it as the strongest suggestion in the file.
