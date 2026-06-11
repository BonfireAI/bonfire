## The BubbleGum Law (form)

**The BubbleGum Law** — CandyFactory's form law — governs this repository. It sticks:
read it and you carry it.

- **SOLID:** one responsibility per module (new files ≤ 500 lines); extend via registries,
  not dispatch chains; overrides substitute cleanly; interfaces stay narrow (≤ 5 methods,
  no NotImplementedError stubs); dependencies point inward — core never imports
  adapters/packs/tenants; each repo commits its import contract.
- **DRY:** search before writing; never paste what exists; cross-repo copies declare their mirror.
- **KISS:** functions ≤ CC 10, ≤ 50 statements; recursion declares a bound or fails.
- **The bench:** no dead code (YAGNI) · no import cycles (SoC) · compose, don't subclass ·
  neighbors, not strangers (Demeter) · failure speaks typed errors (the Elegance Law).

Budgets come from measurement; offenders baseline and only shrink — ratchet, never
world-refactor. In CandyFactory CI and Bonfire burns the measured core runs as gates,
each proven by a control rod; the rest is census and review. Comply by design: every
suppression carries a written reason and a registered blessing. Elsewhere, this law is
the strongest suggestion in the file.
