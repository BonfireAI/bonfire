# Sage Memo Template (canonical)

This file's stem (`sage-memo-template`) ends with `-template`, which is the
selector the cluster-350 doc-invariant smoke test (innovation lens) uses to
identify the canonical Sage memo template. The smoke test scrubs files whose
stem matches this pattern of internal-tracker-id leakage.

**The full template content lives at**
[`_template-sage-memo.md`](_template-sage-memo.md).

This file is a thin redirect. It exists so that:

1. External contributors can find the template by alphabetical sort
   (it lands at the bottom of the directory listing alongside its
   underscore-prefixed sibling).
2. The doc-invariant smoke test's `-template` stem selector finds a
   tracker-id-clean file even if the underscore-prefixed file is renamed
   in a future hygiene pass.
3. The placeholder ticket reference (`<ticket-Z>`) and the section
   anchors (`§A` through `§G`) used in the canonical template are
   stable across both filenames.

For the canonical Sage memo shape, copy
[`_template-sage-memo.md`](_template-sage-memo.md) verbatim and replace
`<ticket-Z>` with your concrete ticket reference. Concrete memos may cite
their own tracker; the template MUST stay tracker-clean.

## Cross-references

- [`_template-sage-memo.md`](_template-sage-memo.md) — the canonical body.
- [`../../style.md`](../../style.md) — code style decisions referenced
  by §F of the template.
- [`../../contributor-guide/wizard-pre-stage.md`](../../contributor-guide/wizard-pre-stage.md)
  — Wizard pre-stage procedure that consumes Sage memos.

---

**END Sage memo template (redirect).**
