# BON-341 — Sage Contract-Lock (Dual Knight Reconciliation)

**Stamp:** 2026-04-23T01:37:25Z
**Scope:** Reconcile Knight A (innovative, 355f8e5) + Knight B (conservative, 66c768e) into ONE canonical RED contract for Warriors.
**Supersedes (partially):** D8/D9/D10 numeric locks in `docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md`. D1–D7, D11–D12 stand unchanged.
**Authority:** This memo is the single source of truth for Warrior base branch + numeric preflight locks for BON-341 dispatch.

---

## Summary (one-line decision)

**Warriors branch off `antawari/bon-341-red-canonical` (pre-staged merge).
Final RED = 268 tests. Revised lock: `passed >= 3086, xfailed == 28, xpassed == 0, FAILED == 0, ERROR == 0`.**

---

## D-CL1 — Adoption Filter (10 Knight A innovations)

Criteria: **ADOPT** = durable drift-guard OR known-risky seam Knight B missed AND ≤30 LOC. **FILE_FOLLOWUP** = valuable but non-blocking OR duplicative. **REJECT** = speculative / over-specifies / white-box.

| # | Innovation | Verdict | Rationale |
|---|---|---|---|
| 1 | `TestNoStaleVaultXfails` meta-test class in `test_architect_handler.py:600-631` (2 tests) | **ADOPT** | Matches BON-520 forever-guard pattern (`test_persona_builtins_dynamic_role_coverage.py:96`); 32 LOC; grep-style drift-guard prevents xfail-decorator regressions from future agents. Anta's explicit memory `project_bon126_cognitive_axioms` reinforces grep-style invariant tests. Self-excluding assertion (`f"@{marker}"`) is the correct pattern — no false positives. |
| 2 | Byte-stability `content_hash(entry.content) == entry.content_hash` on chunker (markdown + source) — `test_knowledge_chunker.py:111-116, 247-251` | **ADOPT** | Cross-contract invariant between two Sage-locked modules (D8.2: chunker line 442 + hasher line 427). Durable guard catches future chunker regressions that silently skip hashing. 10 LOC. High-risk seam (VaultEntry identity depends on content_hash correctness). |
| 3 | `__all__` exhaustiveness locks on `test_scan_package.py:29-35` + `test_knowledge_package.py` (submodule-importable sweep, 9 tests) | **ADOPT (scan_package only)** / **FILE_FOLLOWUP (knowledge_package submodule sweep)** | `scan/__init__.py` `__all__` == `{"TechScanner", "DecisionRecorder"}` is explicitly locked in D2 row 13 — adopt. Knight A's `knowledge_package.py` submodule-importable sweep (lines 39-95) duplicates per-file import coverage already in dedicated per-module test files; file followup as coverage-consolidation cleanup. |
| 4 | `test_factory_all_params_are_keyword_only` — `test_knowledge_factory.py:46-55` | **ADOPT** | D8.2 line 493 explicitly locks signature as `(*, enabled=..., backend=..., ...)` — this test IS the signature lock. 10 LOC. Would catch any Warrior who accidentally drops the `*,` separator. Sage contract already mandates this shape; the test pins it at source. |
| 5 | Parametrize-heavy coverage (whitespace variants, manifest languages, suffix classifications, exclusion patterns, resilience handlers, factory branches) | **ADOPT selectively** | Adopt: manifest-language parametrize in `test_scan_tech_scanner.py:70-88` (4 cells, covers Cargo.toml + go.mod — known-risky seams for future contributors) + factory branch parametrize `test_knowledge_factory.py:109-121` (protocol conformance across branches, 4 cells). Reject: whitespace-variants on chunker.empty (5 cells of redundancy with single `test_empty_returns_empty`). |
| 6 | Empty/missing/malformed input edges (every module) | **ADOPT (resilience-tier)** / **FILE_FOLLOWUP (edge-expansion)** | Adopt: `malformed_package_json_does_not_crash` (`test_scan_tech_scanner.py:125-133`) — real resilience contract (v1 scanner MUST not crash on bad JSON). Adopt: `missing_dir_returns_zero` in backfill (2 tests, durable invariant). File followup: `empty_file_returns_zero` on ingest + `empty_input_returns_empty_output` on mock_embedder (nice-to-have, marginal). |
| 7 | Split-multi-invariant tests (where D8 named a single test, A split into 2-3 sharper) | **REJECT** | Knight A's splits (e.g. `test_file_info_is_frozen` + `test_file_info_exposes_locked_attributes`; `test_content_hash_normalization_is_idempotent`) add test-suite maintenance burden without durable value. Sage D8.3 intentionally merged these invariants into single tests. Knight B's consolidated form is canonical. |
| 8 | Case-insensitivity + positional-args-rejected tests on memory backend | **REJECT (case-insensitivity)** / **ADOPT (positional-args-rejected)** | Reject `test_query_is_case_insensitive` (`test_knowledge_memory.py:147-153`) — Sage D8.2 does NOT lock case-insensitive query; v1 `memory.py:query()` uses `.lower()` but the CONTRACT is "substring match scores by word count" (D8.3 name). Over-specifies implementation detail. Adopt `test_constructor_rejects_positional_args` (`test_knowledge_memory.py:224+`) — directly pins D8.2's `__init__(self) -> None` signature. 4 LOC. |
| 9 | Provenance propagation tests on chunker + ingest | **ADOPT** | `test_chunk_markdown_propagates_provenance` (`test_knowledge_chunker.py:147-157`) + `test_ingest_markdown_propagates_provenance` (`test_knowledge_ingest.py:65+`) pin D8.2 VaultEntry field contract (source_path + project_name + git_hash flow through pipeline). Durable integration-style unit tests. 10 LOC each. |
| 10 | Content-hash equivalence under iteration (stability across N calls) | **REJECT** | `test_content_hash_stable_across_many_calls` (`test_knowledge_hasher.py:60+`) — duplicates `test_content_hash_stable_across_calls` (D8.3 locked) at N=many. No additional signal; stability is binary not frequency-dependent. Maintenance burden (pytest parametrize noise) without corresponding fault-detection lift. |

**Also flagged during spot-check (not in original list):**

- `test_content_hash_uses_sha256_under_the_hood` (`test_knowledge_hasher.py:136-141`) — **REJECT**. White-box test asserting specific algorithm + specific normalization rule. If a future port switches to BLAKE3 with the same normalization contract, this test fails for no customer-visible reason. Over-specifies per D9.8 philosophy (contract, not implementation).
- Knight B's `test_file_hash_matches_content_hash_of_file_bytes` uses `hashlib.sha256(path.read_bytes())` — **BUG IN KNIGHT B**. v1 `vault/hasher.py:31` implements `file_hash(path) = content_hash(path.read_text())` (NORMALIZED), not raw bytes. Knight B's test passes coincidentally only when test payloads contain no whitespace to normalize. **Use Knight A's expression** (`file_hash(p) == content_hash(payload)`) — this is cross-module verification, not white-box.

---

## D-CL2 — File-by-File Reconciliation Matrix

Legend: **A** = take Knight A whole. **B** = take Knight B whole. **merge(A+B)** = merge Knight A tests named + Knight B tests named (Wizard uses `git checkout <A-branch> -- ...` + hand-edits OR file-level surgery). **Final count** = integer tests per file after reconciliation.

| # | File | Canonical Source | A pieces merged in | B pieces merged in | Final tests | Rationale |
|---|---|---|---|---|---|---|
| 1 | `tests/unit/test_knowledge_hasher.py` | **merge(A+B)** | A body verbatim MINUS `test_content_hash_uses_sha256_under_the_hood` (REJECT #10 above) MINUS `test_content_hash_stable_across_many_calls` (REJECT innovation 10). File_hash expression from A (stricter + correct per v1 ground truth). | — | 10 | Knight A's file_hash expression is correct; Knight B's is buggy-but-coincidentally-passing. Strip white-box sha256 + redundant stability-many. |
| 2 | `tests/unit/test_knowledge_memory.py` | **merge(A+B)** | A body MINUS `test_query_is_case_insensitive` (REJECT innovation 8a). KEEP: `test_constructor_rejects_positional_args` (ADOPT 8b), `test_get_by_source_returns_empty_for_unknown_path` (ADOPT 6), `test_exists_false_for_empty_hash_on_empty_backend`, `test_store_preserves_existing_content_hash`. | — | 16 | A covers all D8.3 required names + known-risky seams. Strip case-insensitivity over-spec. |
| 3 | `tests/unit/test_knowledge_chunker.py` | **merge(A+B)** | A body MINUS whitespace-variants parametrize (REJECT 5-partial) — keep 1 `test_chunk_markdown_empty_returns_empty` (D8.3 named). KEEP: byte-stability (ADOPT 2), provenance (ADOPT 9), metadata-keys-locked, chunk_index-contiguous, tags/entry_type per D8.2. | — | 21 | Byte-stability vs hasher is the critical cross-module invariant. Provenance propagates D8.2 VaultEntry fields. |
| 4 | `tests/unit/test_knowledge_scanner.py` | **merge(A+B)** | A body MINUS split-from-frozen shape-invariant (REJECT 7). KEEP: parametrize suffix-classification (5 cells, ADOPT 5), parametrize default-excludes (4 cells, ADOPT 5), manifest-counts-match-files, extract-signatures-skips-syntax-errors. | — | 20 | Parametrize suffix + excludes are durable matrix tests. Drop the FrozenInstanceError-splitting noise. |
| 5 | `tests/unit/test_knowledge_embeddings.py` | **merge(A+B)** | A body MINUS `test_get_embedder_unknown_provider_message_cites_name` (over-specifies error text) MINUS `test_embedding_provider_rejects_missing_methods` (runtime_checkable already covers). KEEP: `test_mock_embedder_vector_length_matches_dim`, `test_mock_embedder_default_dim_is_768`, `test_mock_embedder_distinct_inputs_produce_distinct_vectors`, `test_get_embedder_respects_dim`. | — | 11 | Hold the 7 D8.3-named tests + 4 durable invariants. Strip error-string-matching. |
| 6 | `tests/unit/test_knowledge_ingest.py` | **merge(A+B)** | A body MINUS `test_ingest_markdown_missing_file_returns_zero` + `test_ingest_session_missing_file_returns_zero` (FILE_FOLLOWUP 6) MINUS `test_ingest_markdown_empty_file_returns_zero` (FILE_FOLLOWUP 6) MINUS `test_retrieve_context_returns_list_type` (subsumed by D8.3). KEEP: `test_ingest_markdown_propagates_provenance` (ADOPT 9), `test_retrieve_context_empty_backend_returns_empty_list`. | — | 8 | Baseline 5 D8.3-named + 2 provenance + 1 empty-backend resilience. |
| 7 | `tests/unit/test_knowledge_consumer.py` | **merge(A+B)** | A body MINUS `test_each_handler_is_resilient_to_backend_failure` (duplicates `test_backend_store_exception_is_caught_and_logged` at finer granularity; FILE_FOLLOWUP — resilience-across-all-4-handlers is nice-to-have). KEEP: `test_dedup_prevents_duplicate_store_across_calls`, `test_metadata_contains_only_locked_keys` (pins D8.2 metadata LOCK to only session_id + event_id). | — | 15 | All 11 D8.3-named + 2 additional durable locks + 2 innovation holds. |
| 8 | `tests/unit/test_knowledge_backfill.py` | **merge(A+B)** | A body whole (7 tests). Includes ADOPT 6 resilience tests (`missing_dir_returns_zero`, `counts_are_non_negative`, `ignores_non_markdown`). | — | 7 | Small file; A's expansion adds 3 durable edges over D8.3 floor of 4. |
| 9 | `tests/unit/test_knowledge_factory.py` | **merge(A+B)** | A body whole MINUS `test_get_knowledge_backend_does_not_exist` (already subsumed by `__all__` lock in package test). KEEP: keyword-only guard (ADOPT 4), protocol-across-branches parametrize (ADOPT 5), `test_default_call_returns_memory_backend`. | — | 11 | 7 D8.3-named + 4 durable innovation tests. |
| 10 | `tests/unit/test_knowledge_package.py` | **merge(A+B)** | A body TRUNCATED to 3 tests: just D8.3 names (`test_package_imports_without_error`, `test_exports_get_vault_backend`, `test_get_vault_backend_default_signature`). DROP the 9-test `TestKnowledgeSubmodulesImport` class (FILE_FOLLOWUP 3 — duplicates per-module file coverage). | — | 3 | Clean D8.3 floor. Submodule-importable sweep files as cleanup ticket. |
| 11 | `tests/unit/test_scan_tech_scanner.py` | **merge(A+B)** | A body MINUS `test_detects_pytest_as_test_framework` (speculative — not in D8.3; FILE_FOLLOWUP). KEEP: manifest-language parametrize (ADOPT 5), malformed-JSON resilience (ADOPT 6), scan_and_store dedup (durable). | — | 9 | 6 D8.3-named + 1 parametrize + 1 resilience + 1 dedup. |
| 12 | `tests/unit/test_scan_decision_recorder.py` | **merge(A+B)** | A body whole (9 tests). Includes ADR-extract edges + scan_and_store dedup. | — | 9 | 5 D8.3-named + 4 resilience edges (missing_path, empty_markdown, scan_and_store_dedups, scans_directory). All durable. |
| 13 | `tests/unit/test_scan_package.py` | **merge(A+B)** | A body whole (4 tests). Includes `test_package_all_contains_only_locked_names` (ADOPT 3). | — | 4 | 3 D8.3-named + 1 `__all__` exhaustiveness lock (D2 row 13). |
| 14 | `tests/unit/test_architect_handler.py` (modified) | **A** | A whole (34 tests). Includes `TestNoStaleVaultXfails` drift-guard class (ADOPT 1). | — | 34 | Knight A is correct superset. Drift-guard is durable BON-520-pattern forever-guard. Same docstring+import rewrites as Knight B; no content divergence outside the 2 extra meta-tests. |
| 15 | `tests/unit/test_event_consumers.py` (modified) | **B** (identical to A) | — | B whole | 59 | Both Knights produced identical output — take B (conservative principle). |
| 16 | `tests/unit/test_prompt_compiler.py` (modified) | **B** (identical to A) | — | B whole | 138 | `_FORBIDDEN` insert only. Both Knights identical. Take B. |

**Per-file totals check:**
- New test files (13): 10+16+21+20+11+8+15+7+11+3+9+9+4 = **144 new tests**
- Modified files net adds: A added `TestNoStaleVaultXfails` (2 tests) beyond Knight B's arch_handler → +2 over D10's 17-xfails-flipped baseline. Event_consumers + prompt_compiler: no added test count (renamed tests, not added).
- Modified file total tests: 34 + 59 + 138 = **231 existing-surface tests** (of which ~17 flipped from xfail+xpass to plain pass, +2 new meta-tests).

---

## D-CL3 — Warrior Base Branch Specification

**Pre-staged merge branch:** `antawari/bon-341-red-canonical` off `v0.1@a04ea82`.

Wizard executes from `/home/ishtar/Projects/bonfire-public/` main tree (current working tree, clean):

```bash
cd /home/ishtar/Projects/bonfire-public

# 1. Safety check — we must be on a clean main tree.
git status --porcelain
# Expected: empty output. If anything staged/unstaged, STOP and stash.

git switch v0.1
git pull --ff-only origin v0.1

# 2. Create canonical RED branch.
git switch -c antawari/bon-341-red-canonical

# 3. Take Knight A whole for the 13 NEW test files (A is pure superset per
#    D-CL2 rows 1-13; reconciliation filters applied AFTER in step 7).
git checkout antawari/bon-341-knight-a -- \
  tests/unit/test_knowledge_hasher.py \
  tests/unit/test_knowledge_memory.py \
  tests/unit/test_knowledge_chunker.py \
  tests/unit/test_knowledge_scanner.py \
  tests/unit/test_knowledge_embeddings.py \
  tests/unit/test_knowledge_ingest.py \
  tests/unit/test_knowledge_consumer.py \
  tests/unit/test_knowledge_backfill.py \
  tests/unit/test_knowledge_factory.py \
  tests/unit/test_knowledge_package.py \
  tests/unit/test_scan_tech_scanner.py \
  tests/unit/test_scan_decision_recorder.py \
  tests/unit/test_scan_package.py

# 4. Take Knight A whole for test_architect_handler.py (has TestNoStaleVaultXfails).
git checkout antawari/bon-341-knight-a -- tests/unit/test_architect_handler.py

# 5. Take Knight B for test_event_consumers.py + test_prompt_compiler.py
#    (identical to Knight A; conservative principle).
git checkout antawari/bon-341-knight-b -- \
  tests/unit/test_event_consumers.py \
  tests/unit/test_prompt_compiler.py

# 6. Stage + commit the raw dual-knight blend (pre-filter checkpoint).
git add tests/unit/test_knowledge_*.py tests/unit/test_scan_*.py \
        tests/unit/test_architect_handler.py \
        tests/unit/test_event_consumers.py \
        tests/unit/test_prompt_compiler.py
git commit -m "BON-341 contract-lock: dual-knight RED blend (pre-filter)

Knight A: test_knowledge_* + test_scan_* + test_architect_handler.py
Knight B: test_event_consumers.py + test_prompt_compiler.py (identical to A)
Sage contract-lock memo: docs/audit/sage-decisions/bon-341-sage-contract-lock-20260423T013725Z.md"

# 7. Apply D-CL2 reconciliation filter (see D-CL6 for the edits per file).
#    Wizard performs editor-mode surgery to strip REJECT tests named in D-CL1.
#    This is manual (filter is small; 10 named tests to remove across 6 files).
#    See "Filter application guide" immediately below.

# 8. Verify RED state — expected collection-time ERROR on knowledge.chunker
#    import (modules not yet ported); other tests collect + fail (import errors
#    or AssertionError).
PYTHONPATH=$(pwd)/src .venv/bin/pytest tests/ --collect-only 2>&1 | tail -20
PYTHONPATH=$(pwd)/src .venv/bin/pytest tests/ 2>&1 | tail -20

# 9. Final commit + push.
git add -u
git commit -m "BON-341 contract-lock: filter applied (REJECT tests removed per D-CL1)

Removed 10 named tests across 6 files per Sage verdicts in
docs/audit/sage-decisions/bon-341-sage-contract-lock-20260423T013725Z.md"

git push -u origin antawari/bon-341-red-canonical
```

**Filter application guide (step 7) — explicit list of test-name removals:**

| File | Named test to delete |
|---|---|
| `test_knowledge_hasher.py` | `test_content_hash_uses_sha256_under_the_hood` (line 136-141) |
| `test_knowledge_hasher.py` | `test_content_hash_stable_across_many_calls` (line 60-68 approx) |
| `test_knowledge_memory.py` | `test_query_is_case_insensitive` (line 146-153) |
| `test_knowledge_embeddings.py` | `test_get_embedder_unknown_provider_message_cites_name` |
| `test_knowledge_embeddings.py` | `test_embedding_provider_rejects_missing_methods` |
| `test_knowledge_ingest.py` | `test_ingest_markdown_missing_file_returns_zero` |
| `test_knowledge_ingest.py` | `test_ingest_session_missing_file_returns_zero` |
| `test_knowledge_ingest.py` | `test_ingest_markdown_empty_file_returns_zero` |
| `test_knowledge_ingest.py` | `test_retrieve_context_returns_list_type` |
| `test_knowledge_consumer.py` | `test_each_handler_is_resilient_to_backend_failure` |
| `test_knowledge_package.py` | ALL of `class TestKnowledgeSubmodulesImport` (lines 39-95) |
| `test_knowledge_scanner.py` | `test_file_info_exposes_locked_attributes` (duplicate of is_frozen + init) |
| `test_knowledge_chunker.py` | `test_chunk_markdown_whitespace_only_returns_empty` parametrize cells (keep as single non-parametrize) |
| `test_scan_tech_scanner.py` | `test_detects_pytest_as_test_framework` |

**Expected post-filter test count:** 144 new tests (see D-CL4).

---

## D-CL4 — Final RED Test Count (LOCKED)

### New tests (13 files)

| File | Count |
|---|---:|
| `test_knowledge_hasher.py` | 10 |
| `test_knowledge_memory.py` | 16 |
| `test_knowledge_chunker.py` | 21 |
| `test_knowledge_scanner.py` | 20 |
| `test_knowledge_embeddings.py` | 11 |
| `test_knowledge_ingest.py` | 8 |
| `test_knowledge_consumer.py` | 15 |
| `test_knowledge_backfill.py` | 7 |
| `test_knowledge_factory.py` | 11 |
| `test_knowledge_package.py` | 3 |
| `test_scan_tech_scanner.py` | 9 |
| `test_scan_decision_recorder.py` | 9 |
| `test_scan_package.py` | 4 |
| **New subtotal** | **144** |

### Modified files net contribution

| File | Baseline | After | Net Δ |
|---|---:|---:|---:|
| `test_architect_handler.py` | 32 (17 xfailed + 15 pass) | 34 (0 xfailed + 34 pass, includes 2 meta-tests) | +2 new tests; 17 xfails flip to pass |
| `test_event_consumers.py` | 59 | 59 | 0 (rename only) |
| `test_prompt_compiler.py` | 138 | 138 | 0 (add one `_FORBIDDEN` entry; no test-count change) |
| **Modified subtotal Δ** | | | **+2 new, +17 xfails flipped** |

### Final RED test count

- **Total new RED tests (Warriors must make GREEN): 144 (new files) + 2 (meta-tests in arch_handler) = 146 brand-new.**
- **Total xfail-flips (Warriors must keep passing): 17.**
- **Contract-lock FLOOR of pass-count increase: 146 + 17 = 163 tests.**

**BUT** — for the D10 numeric lock recompute, what matters is ABSOLUTE full-suite pass count after port. That includes:
- Baseline 2833 passed
- +146 new RED tests that Warriors make GREEN
- +17 xfails that flip to pass
- +17 xpasses that report as plain pass (pytest strict=False conversion)
- -0 from modifications to 3 existing files (no deletions)
- +2 new meta-tests in arch_handler

**Arithmetic:** 2833 + 146 + 17 + 17 + 2 = **3015 passed** (expected midpoint).

Accounting for test-consolidation slack (Knight A had 177 new tests; we filtered 33 to land at 144; ceiling could vary ±5 for execution-time dynamic collection): **floor 3086 is the correct Wizard-bounce gate after re-accounting the `xpass→pass` tally**. See D-CL5.

---

## D-CL5 — Revised D10 Numeric Lock

**Original D10 lock (supersede):**
```
passed >= 2935 AND passed <= 2980
xfailed == 28
xpassed == 0
FAILED == 0
ERROR == 0
```

**Revised D10 lock (authoritative after contract-lock):**
```
passed >= 3086 AND passed <= 3140
xfailed == 28
xpassed == 0
FAILED == 0
ERROR == 0
```

### Arithmetic (authoritative)

| Component | Original D10 | Contract-lock revised | Delta |
|---|---:|---:|---:|
| N1 (new knowledge tests) | +68 | **+118** | +50 (D-CL2 expansion: 10+16+21+20+11+8+15+7+11+3 = 120; −2 for 2 submodule-sweep drops = 118) |
| N2 (new scan tests) | +15 | **+22** | +7 (D-CL2: 9+9+4 = 22) |
| N3 (new meta-tests in arch_handler) | 0 | **+2** | +2 (ADOPT 1 — `TestNoStaleVaultXfails`) |
| M1 (xfails flipped to pass) | +17 | **+17** | 0 |
| M2 (xpasses now report as pass) | +17 | **+17** | 0 |
| **Total Δ passed** | **+117** | **+176** | **+59** |
| **Passed (absolute)** | 2833+117 = 2950 | 2833+176 = **3009** | +59 |
| **Floor with +77 headroom** | 2935 | **3086** | +151 |

Wait — arithmetic sanity-check. Let me recompute with precise values.

- N1 (knowledge new tests, sum of rows 1–10 in D-CL2): 10+16+21+20+11+8+15+7+11+3 = **122**.
- N2 (scan new tests, sum of rows 11–13): 9+9+4 = **22**.
- N3 (arch_handler meta-tests): **+2**.
- M1 (xfails→pass): **+17**.
- M2 (xpass→pass accounting): **+17**.
- **Σ = 122 + 22 + 2 + 17 + 17 = 180**.
- **Passed absolute = 2833 + 180 = 3013**.

Floor should carry ~3% headroom for Knight-permitted consolidation during Warrior GREEN (fixture sharing may collapse 3-5 tests). Ceiling carries +4% for parametrize expansion at collection time (pytest counts cells, not test defs).

**Final revised lock:**

```
passed >= 3009 AND passed <= 3040    # TIGHT — contract-lock is firm
xfailed == 28                         # unchanged from D10
xpassed == 0                          # unchanged from D10
FAILED == 0
ERROR == 0
```

**Correction to summary line:** the single-line decision in the Summary used `passed >= 3086` — that was a too-loose approximation. Use **`passed >= 3009`** as the Wizard-bounce gate.

**Wizard merge-preflight assertion (final):** after `.venv/bin/pip install -e .` + `.venv/bin/pytest tests/ -v` on `antawari/bon-341-warrior-canonical` (the Warrior branch, post-GREEN):

```
passed >= 3009
passed <= 3040
xfailed == 28
xpassed == 0
FAILED == 0
ERROR == 0
```

If any lock diverges, Wizard bounces PR. Revised.

---

## D-CL6 — Warrior Contract Delta (from D9)

Enumerated deltas. Warriors read D9 for the PORT operation scope; the following additions pin what must additionally be implemented for each ADOPTed innovation to go GREEN:

### From ADOPT 1 (TestNoStaleVaultXfails meta-test)

- **Warrior action:** NONE in src/. This is a test-file-only drift-guard. The test reads its own source and asserts no stale `@_VAULT_XFAIL` / `@_CHUNKER_XFAIL` / `@_SCANNER_XFAIL` / `@_HANDLER_XFAIL` decorator applications remain AND no `bonfire.vault` imports remain in `test_architect_handler.py`.
- **Pre-condition:** D6 table already mandates removing all 42 decorator applications + 4 marker constants + 4 try/except shims. This test merely pins that outcome.

### From ADOPT 2 (byte-stability chunker↔hasher)

- **Warrior action in `src/bonfire/knowledge/chunker.py`:** ensure every `VaultEntry` produced by `chunk_markdown` and `chunk_source_file` has `content_hash = bonfire.knowledge.hasher.content_hash(<that entry's content>)`. Cross-module invariant: no bypass paths.
- **v1 source check:** v1 `vault/chunker.py` already calls `content_hash` per-entry via `_make_chunk_entry`. Port is verbatim. No behavior change. Test pins it.

### From ADOPT 3 (scan_package __all__ lock)

- **Warrior action in `src/bonfire/scan/__init__.py`:** export exactly `__all__ = ["TechScanner", "DecisionRecorder"]`. No extra entries. No missing entries.
- **v1 source check:** v1 `scanners/__init__.py` exports both; verify verbatim port.

### From ADOPT 4 (factory keyword-only signature)

- **Warrior action in `src/bonfire/knowledge/__init__.py`:** `get_vault_backend` signature MUST be:
  ```python
  def get_vault_backend(
      *,  # keyword-only separator MANDATORY
      enabled: bool = True,
      backend: str = "memory",
      vault_path: str = ".bonfire/vault",
      embedding_provider: str = "mock",
      embedding_model: str = "nomic-embed-text",
      embedding_dim: int = 768,
      **kwargs: Any,
  ) -> VaultBackend:
  ```
- **v1 source check:** v1 `vault/__init__.py:14-22` uses `*,` separator. Port verbatim, flip D3.1/D3.2 defaults.

### From ADOPT 5 (manifest-language + factory-branch parametrize)

- **Warrior action in `src/bonfire/scan/tech_scanner.py`:** implement manifest detection for `pyproject.toml` → Python, `package.json` → JavaScript, `Cargo.toml` → Rust, `go.mod` → Go. v1 `scanners/fingerprinter.py` already covers all four.
- **Warrior action in `src/bonfire/knowledge/__init__.py`:** ensure all non-lancedb branches return a `VaultBackend` protocol-satisfying instance (InMemoryVaultBackend). Already locked in D3.3 + D3.1.

### From ADOPT 6 (malformed JSON resilience + backfill missing-dir)

- **Warrior action in `src/bonfire/scan/tech_scanner.py`:** wrap `json.loads(package_json)` in `try: ... except json.JSONDecodeError: ...`. Do not crash; continue to next manifest. v1 `scanners/fingerprinter.py` may already handle this — verify during port.
- **Warrior action in `src/bonfire/knowledge/backfill.py`:** `backfill_sessions(missing_dir)` + `backfill_memory(missing_dir)` return 0, do not raise `FileNotFoundError`. Check v1 `vault/backfill.py` for early-return pattern.

### From ADOPT 8b (positional-args-rejected memory)

- **Warrior action in `src/bonfire/knowledge/memory.py`:** `InMemoryVaultBackend.__init__(self) -> None` — NO positional args accepted. v1 `vault/memory.py:~16` already zero-arg; port verbatim.

### From ADOPT 9 (provenance propagation)

- **Warrior action in `src/bonfire/knowledge/chunker.py` + `src/bonfire/knowledge/ingest.py`:** ensure `source_path`, `project_name`, `git_hash` parameters flow through to every produced `VaultEntry`. v1 source already does this (chunker has `_make_chunk_entry(source_path=..., project_name=..., git_hash=...)` pattern). Port verbatim.

### Everything else in D9 stands unchanged.

---

## D-CL7 — Follow-up Ticket Drafts

### Ticket 1 — Expand knowledge submodule-importable sweep (consolidate to one package test)

- **Project:** Bonfire Free
- **Title:** Consolidate per-module import checks into `test_knowledge_package.py`
- **Size:** S
- **Priority:** Low
- **Labels:** `type:test`, `type:cleanup`
- **Description:**
  > Knight A's BON-341 RED work included a `TestKnowledgeSubmodulesImport` class in `test_knowledge_package.py` (9 tests, one per submodule). During contract-lock reconciliation these were filed as duplicative — the per-module dedicated test file already covers import surface. Consider: either adopt the submodule sweep as a single parametrized drift-guard (single test, 10 cells), OR delete the per-module redundant import-check tests. Cleanup-only ticket; no src/ changes needed. Source: `.claude/worktrees/bon-341-knight-a/tests/unit/test_knowledge_package.py:39-95`.

### Ticket 2 — Ingest empty/missing-file resilience tests

- **Project:** Bonfire Free
- **Title:** Add ingest resilience tests for empty + missing files
- **Size:** XS
- **Priority:** Low
- **Labels:** `type:test`
- **Description:**
  > Knight A's BON-341 RED work included `test_ingest_markdown_missing_file_returns_zero`, `test_ingest_session_missing_file_returns_zero`, `test_ingest_markdown_empty_file_returns_zero`. Filed as non-blocking per D-CL1 innovation 6. Add these to `tests/unit/test_knowledge_ingest.py` as follow-up resilience coverage. May require ingest() to return 0 (not raise) on missing path. Source: `.claude/worktrees/bon-341-knight-a/tests/unit/test_knowledge_ingest.py:51-58`.

### Ticket 3 — Consumer resilience across all 4 handlers

- **Project:** Bonfire Free
- **Title:** Expand KnowledgeIngestConsumer resilience to all 4 event handlers
- **Size:** XS
- **Priority:** Low
- **Labels:** `type:test`
- **Description:**
  > Knight A's BON-341 RED work included `test_each_handler_is_resilient_to_backend_failure` (parametrizes over StageCompleted / StageFailed / DispatchFailed / SessionEnded, asserting each catches backend.store() exceptions). Filed as non-blocking per D-CL1 innovation 6 — one representative handler suffices for contract. Add as forward-looking resilience matrix. Source: `.claude/worktrees/bon-341-knight-a/tests/unit/test_knowledge_consumer.py:284+`.

### Ticket 4 — Mock embedder edge coverage

- **Project:** Bonfire Free
- **Title:** Add mock embedder edge tests (empty input, provider error text)
- **Size:** XS
- **Priority:** Low
- **Labels:** `type:test`
- **Description:**
  > Knight A's BON-341 RED work included `test_mock_embedder_empty_input_returns_empty_output`, `test_get_embedder_unknown_provider_message_cites_name`, `test_embedding_provider_rejects_missing_methods`. Filtered out to avoid over-specifying error text. If error-message stability becomes a consumer concern, reintroduce these as a set. Source: `.claude/worktrees/bon-341-knight-a/tests/unit/test_knowledge_embeddings.py:64,99,124`.

### Ticket 5 — Pytest-as-test-framework detection

- **Project:** Bonfire Free
- **Title:** TechScanner — detect pytest in optional-dependencies as test_framework
- **Size:** S
- **Priority:** Medium
- **Labels:** `type:build`, `type:test`
- **Description:**
  > Knight A's BON-341 RED work included `test_detects_pytest_as_test_framework` — v1 `TechFingerprinter` may not emit `technology="pytest"` from `[project.optional-dependencies]`. Confirm v1 behavior via test; if gap exists, port then land. Potential addition to Front Door onboarding signal (BON-179 project workflow). Source: `.claude/worktrees/bon-341-knight-a/tests/unit/test_scan_tech_scanner.py:105-114`.

---

## D-CL8 — Open Questions

**Zero.** All reconciliation decisions are terminal.

Noted-but-closed:

1. **Should case-insensitive query be contracted?** — No. D8.2 says "substring match scores by word count" — case-sensitivity is orthogonal and was NOT in the contract. Knight B's conservative lens (no case lock) wins. Rejected.
2. **Byte-stable chunker↔hasher — can Warrior deviate from v1?** — No. Cross-module invariant is now a locked test (ADOPT 2). Warrior must honor.
3. **D10 passed floor — why jumped from 2935 to 3009?** — D8 originally locked 68 new knowledge tests + 15 new scan tests = 83 net expansion. D-CL2 expanded to 122 + 22 + 2 = 146 net expansion, per the ADOPT filter applying Knight A's durable edges. Arithmetic rechecked above.
4. **Merge-conflict risk on `test_architect_handler.py` between knight-a and knight-b?** — Zero. Knight A is pure superset (34 tests includes Knight B's 32 + 2 new meta-tests). `git checkout knight-a -- test_architect_handler.py` takes all of A.

---

## Appendix — Spot-check evidence

Verified during Phase 1 read:

- **Meta-test class** `TestNoStaleVaultXfails` exists at `.claude/worktrees/bon-341-knight-a/tests/unit/test_architect_handler.py:600-631` (2 tests, self-excluding assertion pattern).
- **Byte-stability chunker test** at `.claude/worktrees/bon-341-knight-a/tests/unit/test_knowledge_chunker.py:111-116` (markdown) + `:247-251` (source). Uses `content_hash as _ch` import.
- **scan_package __all__ lock** at `.claude/worktrees/bon-341-knight-a/tests/unit/test_scan_package.py:29-35`. Asserts `set(scan_pkg.__all__) == {"TechScanner", "DecisionRecorder"}`.
- **Factory keyword-only guard** at `.claude/worktrees/bon-341-knight-a/tests/unit/test_knowledge_factory.py:46-55`. Iterates `inspect.signature()` parameters, asserts `KEYWORD_ONLY` or `VAR_KEYWORD`.
- **Knight B file_hash bug** at `.claude/worktrees/bon-341-knight-b/tests/unit/test_knowledge_hasher.py:53`. Uses `hashlib.sha256(path.read_bytes()).hexdigest()` — WRONG per v1 `bonfire/src/bonfire/vault/hasher.py:29-31` (file_hash reads text + normalizes; Knight A's expression is correct).
- **BON-520 forever-guard precedent** at `/home/ishtar/Projects/bonfire-public/tests/unit/test_persona_builtins_dynamic_role_coverage.py:96` — matches TestNoStaleVaultXfails pattern family.
- **Knight A file sizes:** total new tests = 177 across 13 files; modified file additions = +2 meta-tests. Grep-verified.
- **Knight B file sizes:** total new tests = 91 across 13 files (D8.3 floor). Grep-verified.
- **After D-CL filter:** final new tests = 144 across 13 files + 2 meta-tests in modified file = **146 total new RED tests**.

---

## COMMAND (for the Wizard)

1. Memo path: `docs/audit/sage-decisions/bon-341-sage-contract-lock-20260423T013725Z.md`.
2. Canonical decision (corrected): **Warriors branch off `antawari/bon-341-red-canonical`. Final RED = 146 tests (144 new files + 2 meta-tests) + 17 xfails flip. Revised lock: `passed >= 3009 AND passed <= 3040`, `xfailed == 28`, `xpassed == 0`, `FAILED == 0`, `ERROR == 0`.**
3. Adoption table: D-CL1 (10 rows; 6 ADOPT, 2 ADOPT-partial, 2 REJECT, plus 2 additional flagged).
4. Follow-up tickets: 5 drafts in D-CL7, all Low/Medium priority, all XS/S size.
5. Open questions: **ZERO**.

End of memo. Wizard proceeds to D-CL3 execution.
