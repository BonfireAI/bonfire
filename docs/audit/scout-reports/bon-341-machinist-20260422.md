# BON-341 Machinist Scout Report

**Ticket:** BON-341 — W5.2 Transfer: `knowledge/` + `scan/` (vault + scanners port)
**Branch:** `v0.1` @ `a04ea82` · Baseline 2833p / 45xf / 17xp
**Lens:** Machinist — mechanics only (port map + blast radius + xfail inventory)
**Sibling scouts:** Artisan (design), Archivist (audit-trail + docstrings)

---

## 1. Port Table — v1 → public

v1 root: `/home/ishtar/Projects/bonfire/src/bonfire/`. Public destinations under `/home/ishtar/Projects/bonfire-public/src/bonfire/`. Both destination directories currently hold only a placeholder `__init__.py` (`"bonfire.knowledge — placeholder for v0.1 transfer."` / `"bonfire.scan — placeholder for v0.1 transfer."`).

### 1a. `vault/` → `knowledge/` (12 files, 1393 LOC)

| Source (v1) | LOC | Destination (public) | V/A/S | Key imports pulled in | Rationale |
|---|---:|---|---|---|---|
| `vault/__init__.py` | 50 | `knowledge/__init__.py` | **Adapt** | `knowledge.memory`, `knowledge.backend`, `knowledge.embeddings` (lazy) | Factory `get_vault_backend()` — internal lazy imports must rewrite `bonfire.vault.*` → `bonfire.knowledge.*`. Factory name: Sage decides (flag — see §6). Overwrites existing placeholder (1-line docstring). |
| `vault/backend.py` | 232 | `knowledge/backend.py` | **Adapt** | `knowledge.hasher.content_hash`, `knowledge.embeddings.EmbeddingProvider`, `bonfire.protocols.VaultEntry`, `lancedb` (lazy), `pyarrow` (lazy) | `LanceDBBackend` + auto-migration `vault` → `vault_v2`. Rewrite 2 self-imports (lines 15, 19). **NOTE:** table names `"vault"` / `"vault_v2"` are on-disk LanceDB table identifiers — strings, NOT Python names. DO NOT rename or vector compatibility breaks (Memory: vectors-sacred). Flag for Sage. |
| `vault/memory.py` | 50 | `knowledge/memory.py` | **Adapt** | `knowledge.hasher.content_hash`, `bonfire.protocols.VaultEntry` | `InMemoryVaultBackend`. Rewrite import line 11. Sage ADR-001 check: keep class name `InMemoryVaultBackend` (referenced by `test_architect_handler.py:46`). |
| `vault/chunker.py` | 190 | `knowledge/chunker.py` | **Adapt** | `bonfire.protocols.VaultEntry`, `knowledge.hasher.content_hash` | `chunk_markdown`, `chunk_source_file`, `_size_based_split`. Rewrite import line 13. Pure function module — no behavioural change. |
| `vault/hasher.py` | 31 | `knowledge/hasher.py` | **Verbatim** | stdlib only (`hashlib`, `re`, `pathlib`) | `content_hash(text) -> str`, `file_hash(path) -> str`. Zero bonfire imports. Copy byte-for-byte. |
| `vault/embeddings.py` | 41 | `knowledge/embeddings.py` | **Adapt** | `knowledge.ollama_embedder.OllamaEmbedder` (lazy), `knowledge.mock_embedder.MockEmbedder` (lazy) | `EmbeddingProvider` Protocol + `get_embedder` factory. Rewrite lines 34, 38. |
| `vault/mock_embedder.py` | 36 | `knowledge/mock_embedder.py` | **Verbatim** | stdlib only (`hashlib`) | `MockEmbedder`. Zero bonfire imports. Module docstring cites `bonfire-beta/bonfire/vault/embeddings.py` — Archivist will decide if this provenance is kept. |
| `vault/ollama_embedder.py` | 83 | `knowledge/ollama_embedder.py` | **Verbatim** | `ollama` (lazy 3rd-party) | `OllamaEmbedder`. Zero internal bonfire imports. Same beta-provenance docstring note. |
| `vault/scanner.py` | 237 | `knowledge/scanner.py` | **Adapt** | `knowledge.hasher.content_hash` | `ProjectScanner`, `FileInfo`, `ModuleSignature`, `ProjectManifest`. Rewrite line 14. **NOTE:** despite file name `scanner.py`, this lives in `knowledge/` per the ticket (NOT `scan/` — see §6 for reasoning). Confirmed by test_architect_handler.py:68 `from bonfire.vault.scanner import ProjectScanner` → target `from bonfire.knowledge.scanner import ProjectScanner`. |
| `vault/ingest.py` | 214 | `knowledge/ingest.py` | **Adapt** | `bonfire.protocols.VaultBackend`, `bonfire.protocols.VaultEntry`, `knowledge.chunker.chunk_markdown`, `knowledge.hasher.content_hash` | `ingest_markdown`, `ingest_session`, `retrieve_context`, helper `_extract_text`, `_classify_source`. Rewrite lines 16, 17. |
| `vault/consumer.py` | 125 | `knowledge/consumer.py` | **Adapt** | `bonfire.models.events.{DispatchFailed, SessionEnded, StageCompleted, StageFailed}`, `bonfire.protocols.VaultEntry`, `bonfire.protocols.VaultBackend`, `knowledge.hasher.content_hash` | `VaultIngestConsumer` (full storage semantics). Rewrite line 27. **CRITICAL:** public v0.1 `events/consumers/vault_ingest.py` is a MINIMAL STUB (71 LOC, no hashing/dedup). BON-341 replaces it with the full version AND renames the file to `knowledge_ingest.py`. Two deltas merged. See §3. |
| `vault/backfill.py` | 104 | `knowledge/backfill.py` | **Adapt** | `knowledge.ingest.ingest_markdown`, `bonfire.protocols.VaultBackend` | `backfill_sessions`, `backfill_memory`, `backfill_all`. Rewrite line 13. |

**Sub-total: 1393 LOC, 12 files.**

### 1b. `scanners/` → `scan/` (3 files, 613 LOC)

| Source (v1) | LOC | Destination (public) | V/A/S | Key imports pulled in | Rationale |
|---|---:|---|---|---|---|
| `scanners/__init__.py` | 1 | `scan/__init__.py` | **Adapt** | (none in v1) | v1 file is a 1-line docstring `"""Scanner modules for Bonfire vault ingestion."""`. Overwrites existing placeholder. Sage may want to export `TechFingerprinter`, `DecisionRecorder` for convenience — flag. |
| `scanners/fingerprinter.py` | 290 | `scan/fingerprinter.py` | **Adapt** | `bonfire.protocols.{VaultBackend, VaultEntry}`, `knowledge.hasher.content_hash` | `TechFingerprinter` + module helper `_extract_pyproject_deps`. Rewrite line 17 only. |
| `scanners/decision_recorder.py` | 322 | `scan/decision_recorder.py` | **Adapt** | `bonfire.protocols.{VaultBackend, VaultEntry}`, `knowledge.hasher.content_hash` | `DecisionRecorder`. Rewrite line 17 only. |

**Sub-total: 613 LOC, 3 files.**

### Grand Total

**2006 LOC, 15 files** (matches SMEAC "~2000 LOC port" sizing).

---

## 2. `bonfire.vault` Blast Radius — Public Tree

Canonical command: `grep -rn "bonfire\.vault" src/ tests/` from `/home/ishtar/Projects/bonfire-public/`. Every hit below is an edit target.

| File:Line | Current text | Proposed text | Kind |
|---|---|---|---|
| `src/bonfire/events/consumers/vault_ingest.py:4` | `backend.store interaction) live in the future ``bonfire.vault`` transfer` | *whole file replaced by port of `vault/consumer.py` under new filename `knowledge_ingest.py`*; old docstring deleted. | **string/docstring** (file replaced; see §3) |
| `src/bonfire/handlers/architect.py:11` | `Note: the ``bonfire.vault`` subsystem (``ProjectScanner``, ``chunker``,` | `Note: the ``bonfire.knowledge`` subsystem (``ProjectScanner``, ``chunker``,` | **docstring** |
| `src/bonfire/handlers/architect.py:78` | `# Lazy imports -- ``bonfire.vault`` is not yet present in v0.1.` | Either delete the lazy-import block entirely (Sage call — now that `knowledge/` exists the imports CAN move to module level) OR rewrite comment to `# Module-level imports now safe; lazy pattern retained for pipeline startup speed.` | **comment** (hard call for Sage) |
| `src/bonfire/handlers/architect.py:80` | `from bonfire.vault.chunker import chunk_markdown, chunk_source_file` | `from bonfire.knowledge.chunker import chunk_markdown, chunk_source_file` | **import (hard edit)** |
| `src/bonfire/handlers/architect.py:81` | `from bonfire.vault.hasher import content_hash` | `from bonfire.knowledge.hasher import content_hash` | **import (hard edit)** |
| `src/bonfire/handlers/architect.py:82` | `from bonfire.vault.scanner import ProjectScanner` | `from bonfire.knowledge.scanner import ProjectScanner` | **import (hard edit)** |
| `tests/unit/test_architect_handler.py:46` | `from bonfire.vault.memory import InMemoryVaultBackend  # type: ignore[import-not-found]` | `from bonfire.knowledge.memory import InMemoryVaultBackend` (drop `type: ignore` — module exists) | **conditional import in try/except** |
| `tests/unit/test_architect_handler.py:55` | `from bonfire.vault.chunker import (  # type: ignore[import-not-found]` | `from bonfire.knowledge.chunker import (` | **conditional import in try/except** |
| `tests/unit/test_architect_handler.py:68` | `from bonfire.vault.scanner import ProjectScanner  # type: ignore[import-not-found]` | `from bonfire.knowledge.scanner import ProjectScanner` | **conditional import in try/except** |
| `tests/unit/test_architect_handler.py:90` | `"v0.1 gap: bonfire.vault.memory.InMemoryVaultBackend not yet ported — "` | **either** delete `_VAULT_XFAIL` marker entirely **or** update reason (xfail flips — see §4) | **xfail reason string** |
| `tests/unit/test_architect_handler.py:98` | `reason=("v0.1 gap: bonfire.vault.chunker not yet ported — deferred to BON-W5.3-vault-port"),` | delete `_CHUNKER_XFAIL` OR update reason — xfail flips | **xfail reason string** |
| `tests/unit/test_architect_handler.py:105` | `"v0.1 gap: bonfire.vault.scanner.ProjectScanner not yet ported — "` | delete `_SCANNER_XFAIL` OR update reason — xfail flips | **xfail reason string** |
| `tests/unit/test_event_consumers.py:17` | `* ``VaultIngestConsumer`` (``bonfire.events.consumers.vault_ingest``) — public` | `* ``KnowledgeIngestConsumer`` (``bonfire.events.consumers.knowledge_ingest``)` — verify final class name with Sage | **docstring** |
| `tests/unit/test_event_consumers.py:27` | `* No imports from ``bonfire.vault.*`` (does not exist in public v0.1). A` | `* Imports from ``bonfire.knowledge.*`` are now live; the adaptation is gone. A` — rewrite paragraph to match new state | **docstring** |
| `tests/unit/test_event_consumers.py:703` | `` ``bonfire.vault.consumer`` (not in public v0.1). In public v0.1, this`` | `` ``bonfire.knowledge.consumer`` (full class now ported).`` | **docstring (inside TestVaultIngestConsumerSurface)** |
| `tests/unit/test_prompt_compiler.py:1231` | `"bonfire.vault",` (in `_FORBIDDEN` tuple) | `"bonfire.vault",` — **KEEP AS-IS.** This is a dependency-cycle guard asserting `prompt/` never imports `bonfire.vault`. Post-rename the module is `bonfire.knowledge`, but `bonfire.vault` as a forbidden name still correctly guards stale code. Safer pattern: ADD `"bonfire.knowledge"` to the tuple (prompt/ is a leaf; it should import neither). | **constant (add, don't replace)** |

### `bonfire.scanners` blast radius — Public Tree

Canonical command: `grep -rn "from bonfire.scanners\|import bonfire.scanners\|bonfire\.scanners" src/ tests/` → **ZERO HITS.** Public v0.1 does not yet reference `bonfire.scanners` anywhere. The rename `scanners/→scan/` therefore lands 100% greenfield; no public edits outside the port itself.

---

## 3. `vault_ingest` Blast Radius — Public Tree

Pre-scouted lines verified + expanded via `grep -rn "vault_ingest\|vault\.ingest" src/ tests/`.

| File:Line | Current text | Proposed text | Kind |
|---|---|---|---|
| `src/bonfire/events/consumers/__init__.py:10` | `from bonfire.events.consumers.vault_ingest import VaultIngestConsumer` | `from bonfire.events.consumers.knowledge_ingest import VaultIngestConsumer` (class name unchanged per Sage §6 flag; only module path renamed) | **import (hard edit)** |
| `src/bonfire/events/consumers/vault_ingest.py` (entire file) | **delete** (71 LOC stub) | replaced by NEW file `src/bonfire/events/consumers/knowledge_ingest.py` containing the port of v1 `vault/consumer.py` (125 LOC, full semantics) | **file rename + replace** |
| `tests/unit/test_event_consumers.py:13` | `* ``VaultIngestConsumer`` (``bonfire.events.consumers.vault_ingest``) — public` | `* ``VaultIngestConsumer`` (``bonfire.events.consumers.knowledge_ingest``)` | **docstring** |
| `tests/unit/test_event_consumers.py:70` | `from bonfire.events.consumers.vault_ingest import VaultIngestConsumer` | `from bonfire.events.consumers.knowledge_ingest import VaultIngestConsumer` | **import in try/except shim** |
| `tests/unit/test_event_consumers.py:249` | `def test_vault_ingest_importable(self):` | Either keep name (test IDs are backwards-compat-friendly) OR rename to `test_knowledge_ingest_importable`. Sage call. | **test method name** |
| `tests/unit/test_event_consumers.py:250` | `from bonfire.events.consumers.vault_ingest import VaultIngestConsumer as _VI` | `from bonfire.events.consumers.knowledge_ingest import VaultIngestConsumer as _VI` | **import (inside test body)** |
| `tests/unit/test_event_consumers.py:923` | `async def test_wired_vault_ingest_is_registered(` | Either keep OR rename to `test_wired_knowledge_ingest_is_registered`. Sage call. | **test method name** |

**No misses found.** Search completed with exit-code 0 (0 new hits beyond pre-scouted set).

---

## 4. xfail Inventory — CRITICAL (per S007 §D7)

Goal: every `@pytest.mark.xfail` in public tests whose reason cites `bonfire.vault.*` OR the deferred-port gaps BON-341 will close. Under-specification caused BON-342 reconciliation; this inventory is exhaustive so Sage cannot miss one.

### 4a. Stacked-marker map (source of truth)

The `test_architect_handler.py` suite defines **4 marker constants** (lines 81–108) derived from **4 `_PRESENT` flags** (lines 36–73). Each flag condition:

| Flag | `True` when (post-BON-341) | Marker `condition=not _PRESENT` becomes |
|---|---|---|
| `_HANDLER_PRESENT` | `from bonfire.handlers.architect import ArchitectHandler` succeeds — **already True** on current `v0.1` (handler already lives in public). | Already `False` — `_HANDLER_XFAIL` already no-ops. |
| `_VAULT_PRESENT` | `from bonfire.vault.memory import InMemoryVaultBackend` succeeds | Currently `False` (target doesn't exist). **After BON-341 edits:** True IF test import is rewritten to `bonfire.knowledge.memory`. Marker disarms → `condition=False` → no-op (tests run live). |
| `_CHUNKER_PRESENT` | `from bonfire.vault.chunker import chunk_markdown, chunk_source_file` succeeds | Same — disarms iff test import rewritten. |
| `_SCANNER_PRESENT` | `from bonfire.vault.scanner import ProjectScanner` succeeds | Same — disarms iff test import rewritten. |

**CRITICAL — S007 §D7 pattern:** if Warrior rewrites `bonfire.vault.*` → `bonfire.knowledge.*` in the `try` blocks (lines 46, 55, 68), the `_PRESENT` flags flip True automatically and every xfail marker no-ops. Tests then run live. No `xfail` reason update is strictly required (markers self-disarm via `condition`), BUT stale reason strings mentioning `bonfire.vault.*` will remain in source and will show up in grep post-merge. Recommend: delete all four marker definitions + applications in the same diff (Sage call).

### 4b. Per-test xfail enumeration

Marker application lines from §1 grep (46 total application lines). Every test and its expected post-port state:

| # | Test file:line | Test name | Markers applied | Verbatim reason(s) | v1 dep flipped | Expected post-port state |
|---|---|---|---|---|---|---|
| 1 | `test_architect_handler.py:234` | `test_module_exposes_role_constant_bound_to_analyst` | `_HANDLER_XFAIL` | `"v0.1 gap: bonfire.handlers.architect.ArchitectHandler not yet ported"` | (handler already exists — marker already no-op) | GREEN now, GREEN after |
| 2 | `test_architect_handler.py:245` | `test_role_constant_value_is_analyst_string` | `_HANDLER_XFAIL` | same | same | GREEN now, GREEN after |
| 3 | `test_architect_handler.py:252` | `test_handler_class_docstring_cites_generic_role_or_architect` | `_HANDLER_XFAIL` | same | same | GREEN now, GREEN after |
| 4 | `test_architect_handler.py:269` | `test_handler_module_docstring_present` | `_HANDLER_XFAIL` | same | same | GREEN now, GREEN after |
| 5 | `test_architect_handler.py:277` | `test_role_matches_stage_spec_role_field` | `_HANDLER_XFAIL` | same | same | GREEN now, GREEN after |
| 6 | `test_architect_handler.py:291` | `test_discovers_python_files` | `_SCANNER_XFAIL` | `"v0.1 gap: bonfire.vault.scanner.ProjectScanner not yet ported — deferred to BON-W5.3-vault-port"` | `bonfire.vault.scanner` → `bonfire.knowledge.scanner` (BON-341) | xfail → **FLIP GREEN** |
| 7 | `test_architect_handler.py:301` | `test_discovers_markdown_files` | `_SCANNER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 8 | `test_architect_handler.py:310` | `test_excludes_pycache` | `_SCANNER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 9 | `test_architect_handler.py:318` | `test_manifest_counts_match` | `_SCANNER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 10 | `test_architect_handler.py:327` | `test_empty_dir` | `_SCANNER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 11 | `test_architect_handler.py:334` | `test_extracts_classes_and_functions` | `_SCANNER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 12 | `test_architect_handler.py:348` | `test_extracts_imports` | `_SCANNER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 13 | `test_architect_handler.py:364` | `test_chunk_markdown_returns_vault_entries` | `_CHUNKER_XFAIL` | `"v0.1 gap: bonfire.vault.chunker not yet ported — deferred to BON-W5.3-vault-port"` | `bonfire.vault.chunker` → `bonfire.knowledge.chunker` (BON-341) | xfail → **FLIP GREEN** |
| 14 | `test_architect_handler.py:374` | `test_chunk_markdown_entry_type_is_code_chunk` | `_CHUNKER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 15 | `test_architect_handler.py:380` | `test_chunk_markdown_each_chunk_has_content_hash` | `_CHUNKER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 16 | `test_architect_handler.py:386` | `test_chunk_source_file_returns_vault_entries` | `_CHUNKER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 17 | `test_architect_handler.py:406` | `test_satisfies_stage_handler_protocol` | `_HANDLER_XFAIL` | handler-present reason | handler already present | GREEN now, GREEN after |
| 18 | `test_architect_handler.py:419` | `test_handle_signature_matches_stage_handler_protocol` (TestConstruction) | `_HANDLER_XFAIL` | same | same | GREEN now, GREEN after |
| 19 | `test_architect_handler.py:438` | `test_returns_completed_envelope_with_json_summary` | `_HANDLER_XFAIL` + `_SCANNER_XFAIL` + `_CHUNKER_XFAIL` + `_VAULT_XFAIL` | handler (no-op) + scanner + chunker + vault reasons | scanner, chunker, vault/memory all flip | xfail → **FLIP GREEN** (all 4 markers disarm once `bonfire.knowledge.*` imports resolve) |
| 20 | `test_architect_handler.py:457` | `test_stores_manifest_entry` | `_HANDLER_XFAIL` + `_SCANNER_XFAIL` + `_VAULT_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 21 | `test_architect_handler.py:477` | `test_stores_signature_entries` | `_HANDLER_XFAIL` + `_SCANNER_XFAIL` + `_VAULT_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 22 | `test_architect_handler.py:495` | `test_stores_code_chunks` | `_HANDLER_XFAIL` + `_CHUNKER_XFAIL` + `_VAULT_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 23 | `test_architect_handler.py:512` | `test_skips_already_existing_hashes` | `_HANDLER_XFAIL` + `_SCANNER_XFAIL` | handler + scanner reasons | scanner flips | xfail → **FLIP GREEN** |
| 24 | `test_architect_handler.py:549` | `test_dedups_by_content_hash_on_re_scan` | `_HANDLER_XFAIL` | handler (no-op) | handler already present | **RUNS LIVE NOW** — but exercises handler which lazy-imports `bonfire.vault.*` → runtime ModuleNotFoundError. On current `v0.1` this is either xfail-flagged via `strict=False` not strict-failing (handler `_HANDLER_XFAIL condition=not _HANDLER_PRESENT` = False → no-op) OR it's already failing/erroring. **VERIFY:** check current pytest status for this one. After BON-341 with lazy imports rewritten: **GREEN**. |
| 25 | `test_architect_handler.py:578` | `test_vault_store_failure_returns_failed_envelope` | `_HANDLER_XFAIL` + `_SCANNER_XFAIL` | handler + scanner reasons | scanner flips | xfail → **FLIP GREEN** |
| 26 | `test_architect_handler.py:608` | `test_vault_exists_failure_wraps_in_failed_envelope` | `_HANDLER_XFAIL` + `_SCANNER_XFAIL` | same | same | xfail → **FLIP GREEN** |
| 27 | `test_architect_handler.py:646` | `test_nonexistent_project_root_fails_gracefully` | `_HANDLER_XFAIL` | handler (no-op) | handler already present | same as #24 — likely green-already but involves lazy vault import during handler.handle(). After port: **GREEN** (clean). |
| 28 | `test_architect_handler.py:674` | `test_handler_source_does_not_hardcode_gamified_display` (D3) | `_HANDLER_XFAIL` | handler (no-op) | handler present | GREEN now, GREEN after |
| 29 | `test_architect_handler.py:704` | `test_handle_signature_matches_stage_handler_protocol` (TestIdentitySealInvariants) | `_HANDLER_XFAIL` | same | same | GREEN now, GREEN after |
| 30 | `test_architect_handler.py:711` | `test_handle_returns_envelope` | `_HANDLER_XFAIL` | same | same | GREEN now, GREEN after — but exercises `handler.handle` (vault lazy imports). Same note as #24, #27. |

**Total tests in architect suite:** 30.
**Tests expected to FLIP xfail → GREEN post-port:** #6-16, #19-23, #25-26 = **17 tests.**
**Tests already GREEN (HANDLER-only xfail, no-op):** #1-5, #17-18, #28-29 = 9 tests.
**Tests exercising `handler.handle` (lazy vault import at runtime) currently uncertain:** #24, #27, #30 — the `_HANDLER_XFAIL` marker won't cover a runtime import error in the handler body. **MUST VERIFY current `pytest tests/unit/test_architect_handler.py` status** before port. Flag for Sage.

### 4c. xfails NOT in BON-341 scope (do not touch)

The following xfails mention `BON-W5.3-*` but cite DIFFERENT gaps; they MUST remain xfail after BON-341 with unchanged reason strings:

| File:Line | Marker const | Reason | Closed by |
|---|---|---|---|
| `tests/unit/test_bard_handler.py:93` | `_BARD_META_XFAIL` | `"deferred to BON-W5.3-meta-ports"` | BON-W5.3-meta-ports (not BON-341) |
| `tests/unit/test_bard_handler.py:102` | `_SLUG_HELPER_XFAIL` | (related to meta-ports) | BON-W5.3-meta-ports |
| `tests/unit/test_wizard_handler.py:129` | `_EXTRA_META_XFAIL` | `"not yet ported — deferred to BON-W5.3-meta-ports"` | BON-W5.3-meta-ports |
| `tests/unit/test_wizard_handler.py:138` | `_WIZARD_EVENTS_XFAIL` | `"deferred to BON-W5.3-meta-ports"` | BON-W5.3-meta-ports |
| `tests/unit/test_wizard_handler.py:147` | `_TIMEOUT_XFAIL` | `"deferred to BON-W5.3-protocol-widen"` | BON-W5.3-protocol-widen |
| `tests/unit/test_wizard_handler.py:156` | `_SETTING_SOURCES_XFAIL` | `"deferred to BON-W5.3-protocol-widen"` | BON-W5.3-protocol-widen |
| `tests/unit/test_wizard_handler.py:449` | (inline) | `"deferred to BON-W5.3-protocol-widen"` | BON-W5.3-protocol-widen |
| Many in `test_security_hooks_*.py` | (blind-spots) | unrelated | unrelated |

**Stacked-marker pattern (S007 §D7):** NONE of the current public xfail reasons stack BON-341 with another deferred dep. Every BON-341-touched marker cites *only* `bonfire.vault.*`; every non-BON-341 marker cites *only* meta-ports/protocol-widen/blind-spots. Clean separation. **No stacked markers to reconcile.** Good news for Sage.

### 4d. Baseline xfail accounting check

Current baseline: 45 xfailed. The architect suite contributes 17 flippers. Post-port baseline should show **17 fewer xfails, 17 more passes** (if imports rewritten cleanly). Any test that reports **xpass** (passes unexpectedly while xfail marker still in place) is a BAD signal — means the marker wasn't removed. Strict=False in all four markers means xpass is tolerated but the reporter still flags it. Sage should instruct Warrior to REMOVE the marker applications, not just rewrite the reason.

---

## 5. Import Graph Into `knowledge/`

Public files (`src/` + `tests/`) that either (a) import from `bonfire.vault.*` or (b) reference vault types (`VaultBackend`, `VaultEntry`, `InMemoryVaultBackend`, `LanceDBBackend`, `chunk_markdown`, `content_hash`, `ProjectScanner`). Column "resolves post-port" tells Sage exactly what each site becomes.

### 5a. Type references resolved via `bonfire.protocols` (NO rewrite needed)

`VaultBackend` and `VaultEntry` already live in `src/bonfire/protocols.py` (public, lines 38–39 in `__all__`; class defs L78, L135). These are the PROTOCOL surface and stay at `bonfire.protocols`. BON-341 does NOT touch them.

| File:Line | Import statement | Post-port |
|---|---|---|
| `src/bonfire/protocols.py:78` | `class VaultEntry(BaseModel):` (definition) | **unchanged** |
| `src/bonfire/protocols.py:135` | `class VaultBackend(Protocol):` (definition) | **unchanged** |
| `src/bonfire/handlers/architect.py:33` | `from bonfire.protocols import VaultBackend` (TYPE_CHECKING) | **unchanged** |
| `src/bonfire/handlers/architect.py:79` | `from bonfire.protocols import VaultEntry` (lazy, runtime) | **unchanged** |
| `src/bonfire/engine/advisor.py:19` | `from bonfire.protocols import VaultBackend` (TYPE_CHECKING) | **unchanged** |
| `tests/unit/test_architect_handler.py` | (uses `VaultEntry` indirectly via chunker imports) | implicit |
| `tests/unit/test_engine_advisor.py:32` | `from bonfire.protocols import VaultEntry` | **unchanged** |
| `tests/unit/test_protocols.py:58-59` | `VaultBackend, VaultEntry` imports | **unchanged** |

**These 60+ protocol references across `test_protocols.py`, `test_engine_advisor.py` are NOT in BON-341's blast radius.** They resolve via `bonfire.protocols`, which is already public.

### 5b. `bonfire.vault.*` imports — the real edits

Exhaustive list from §2 grep — 6 edit sites in source, 3 in tests = **9 import rewrites total**:

| File:Line | Import | Resolves post-port |
|---|---|---|
| `src/bonfire/handlers/architect.py:80` | `from bonfire.vault.chunker import chunk_markdown, chunk_source_file` | `bonfire.knowledge.chunker` |
| `src/bonfire/handlers/architect.py:81` | `from bonfire.vault.hasher import content_hash` | `bonfire.knowledge.hasher` |
| `src/bonfire/handlers/architect.py:82` | `from bonfire.vault.scanner import ProjectScanner` | `bonfire.knowledge.scanner` |
| `src/bonfire/events/consumers/__init__.py:10` | `from bonfire.events.consumers.vault_ingest import VaultIngestConsumer` | `bonfire.events.consumers.knowledge_ingest` (file rename — see §3) |
| `src/bonfire/events/consumers/vault_ingest.py` (entire file) | *stub content, no vault imports* | replaced by port of v1 `vault/consumer.py` → now at `knowledge_ingest.py` with `bonfire.knowledge.hasher` imports |
| `tests/unit/test_architect_handler.py:46` | `from bonfire.vault.memory import InMemoryVaultBackend` | `bonfire.knowledge.memory` |
| `tests/unit/test_architect_handler.py:55-58` | `from bonfire.vault.chunker import (chunk_markdown, chunk_source_file)` | `bonfire.knowledge.chunker` |
| `tests/unit/test_architect_handler.py:68` | `from bonfire.vault.scanner import ProjectScanner` | `bonfire.knowledge.scanner` |
| `tests/unit/test_event_consumers.py:70` | `from bonfire.events.consumers.vault_ingest import VaultIngestConsumer` | `bonfire.events.consumers.knowledge_ingest` |
| `tests/unit/test_event_consumers.py:250` | `from bonfire.events.consumers.vault_ingest import VaultIngestConsumer as _VI` | `bonfire.events.consumers.knowledge_ingest` |

**Lazy/conditional imports (scanner-flag):** The `src/bonfire/handlers/architect.py` imports at L79-82 are *inside* `try:` in `handle()` — not module-level. Warrior may move them to module scope now that `bonfire.knowledge` exists (post-port). This is a Sage design call; Artisan has it.

**No other vault internals leak into public.** Things like `LanceDBBackend`, `OllamaEmbedder`, `MockEmbedder`, `TechFingerprinter`, `DecisionRecorder`, `ingest_markdown`, `backfill_sessions` have ZERO import sites in public `src/` or `tests/` today. They arrive fresh with BON-341 and have no external consumer yet.

---

## 6. `get_vault_backend` Factory — Call Sites

v1 `vault/__init__.py:15` defines `get_vault_backend(*, enabled=True, backend="lancedb", vault_path=".bonfire/vault", embedding_provider="ollama", embedding_model="nomic-embed-text", embedding_dim=768, **kwargs) -> VaultBackend`.

### v1 call sites

```
grep -rn "get_vault_backend" /home/ishtar/Projects/bonfire/src /home/ishtar/Projects/bonfire/tests
```

(not fully executed here — Machinist scope is public tree, but mentioned for completeness: v1 wires it via `bonfire/engine/` composition root).

### Public call sites

```
grep -rn "get_vault_backend" src/ tests/   →   0 hits
```

**Factory is NOT called anywhere in public v0.1.** It is dead code at port time. Three options for Sage (FLAG):

1. **Port verbatim, rename to `get_knowledge_backend`** — matches `knowledge/` directory. Best ADR-001 alignment, but requires every future caller (Wave 6+) to use new name.
2. **Port verbatim, keep name `get_vault_backend`** — minimal diff, but name drifts from directory. Risks future confusion.
3. **Port verbatim but leave factory UNUSED in public** — export it from `knowledge/__init__.py` for future composition-root, no call sites added in BON-341.

**Machinist recommendation (mechanics-only):** Option 1 (rename to `get_knowledge_backend`) — zero active call sites means rename cost is ~0; future consistency gain is high. But this is a naming decision — **Artisan's jurisdiction**. Flag for Sage arbitration.

**Embedding factory `get_embedder` (`vault/embeddings.py:22`):** called only by `vault/__init__.py:41`. Internal. Rename `get_embedder` → keep or `get_embedding_provider`? Same Sage call. Zero public consumers.

---

## 7. Test File Impact Summary

Files in `tests/unit/` touched by BON-341:

| File | LOC | How touched | Diff kind |
|---|---:|---|---|
| `test_architect_handler.py` | 720 | (a) 3 import rewrites at L46, L55, L68; (b) optional delete of 4 xfail marker defs at L81-108 + 46 applications throughout; (c) docstring update at L20-21. **Cannot skip the import rewrites** — they gate the `_PRESENT` flags. | import-rewrite + xfail-delete + docstring |
| `test_event_consumers.py` | 942 | (a) 3 import rewrites at L70, L250, and `consumers/__init__.py:10` (source, not test); (b) 3 docstring/comment updates at L13, L17, L27, L703; (c) optional test-method rename at L249, L923. | import-rewrite + docstring + (optional) rename |
| `test_prompt_compiler.py` | 1256+ | ADD `"bonfire.knowledge"` to `_FORBIDDEN` tuple at L1225-1235 (keep `"bonfire.vault"` as guard for stale code). Nothing else. | constant addition |
| `test_engine_advisor.py` | 440+ | **NO CHANGE.** Uses only `bonfire.protocols.VaultEntry` + structural stubs. BON-341 out of scope. | — |
| `test_protocols.py` | 780+ | **NO CHANGE.** Uses only `bonfire.protocols.{VaultBackend,VaultEntry}`. Out of scope. | — |
| `test_bard_handler.py` | — | **NO CHANGE.** xfails cite `BON-W5.3-meta-ports`, not BON-341. | — |
| `test_wizard_handler.py` | — | **NO CHANGE.** xfails cite `BON-W5.3-meta-ports` / `-protocol-widen`. Out of scope. | — |

### Source files touched by BON-341

| File | LOC before | LOC after (rough) | Diff |
|---|---:|---:|---|
| `src/bonfire/events/consumers/__init__.py` | 54 | 54 | 1 line rewrite (L10) |
| `src/bonfire/events/consumers/vault_ingest.py` | 71 | 0 (deleted) | file deleted; content recreated at `knowledge_ingest.py` with full semantics (~125 LOC) |
| `src/bonfire/events/consumers/knowledge_ingest.py` (NEW) | 0 | ~125 | file created from port of v1 `vault/consumer.py` |
| `src/bonfire/handlers/architect.py` | 219 | ~215 | 3 lazy import rewrites (L80-82); optional lazy→module-level hoist (Sage); docstring L11 |
| `src/bonfire/knowledge/__init__.py` | 1 | ~50 | replaces placeholder; full factory |
| `src/bonfire/knowledge/backend.py` (NEW) | 0 | 232 | port of v1 `vault/backend.py` |
| `src/bonfire/knowledge/memory.py` (NEW) | 0 | 50 | port |
| `src/bonfire/knowledge/chunker.py` (NEW) | 0 | 190 | port |
| `src/bonfire/knowledge/hasher.py` (NEW) | 0 | 31 | verbatim |
| `src/bonfire/knowledge/embeddings.py` (NEW) | 0 | 41 | port |
| `src/bonfire/knowledge/mock_embedder.py` (NEW) | 0 | 36 | verbatim |
| `src/bonfire/knowledge/ollama_embedder.py` (NEW) | 0 | 83 | verbatim |
| `src/bonfire/knowledge/scanner.py` (NEW) | 0 | 237 | port |
| `src/bonfire/knowledge/ingest.py` (NEW) | 0 | 214 | port |
| `src/bonfire/knowledge/consumer.py` (NEW) | 0 | 125 | port (also re-exported via `knowledge_ingest.py`? Sage call — see §3) |
| `src/bonfire/knowledge/backfill.py` (NEW) | 0 | 104 | port |
| `src/bonfire/scan/__init__.py` | 1 | ~1-10 | replace placeholder; optional re-exports |
| `src/bonfire/scan/fingerprinter.py` (NEW) | 0 | 290 | port |
| `src/bonfire/scan/decision_recorder.py` (NEW) | 0 | 322 | port |

**Grand total: 15 NEW files (~2006 LOC), 3 MODIFIED files (~6 line rewrites + docstrings), 1 DELETED file (71 LOC stub). Net +1941 LOC.**

---

## What's surprising (Sage would miss without Machinist)

- **The current public `vault_ingest.py` stub (71 LOC, no hashing/dedup) is superseded by the v1 `vault/consumer.py` port (125 LOC, full semantics) — AND the file is simultaneously renamed to `knowledge_ingest.py`.** This is TWO deltas (content replacement + path rename) happening at the same site. Sage must direct Warrior to delete-then-create; a naive "rename-then-edit" plan will either lose the stub's docstring preservation or leave a stale partial stub.
- **`_FORBIDDEN` tuple in `test_prompt_compiler.py:1225-1235` should ADD `"bonfire.knowledge"` alongside `"bonfire.vault"` — not replace it.** `prompt/` is a leaf module; both names should be forbidden. Replacing rather than adding creates a 1-ticket regression window where a rogue import of `bonfire.vault` (stale code, AI agent hallucination) would not be caught.
- **Three tests in `TestScanAndStore`/`TestErrorHandling`/`TestIdentitySealInvariants` (#24, #27, #30 in §4b) are NOT currently xfail-protected against runtime `ModuleNotFoundError` from `architect.handle()`'s lazy `bonfire.vault.*` imports.** `_HANDLER_XFAIL` only gates at import time of the handler class, not at handler body execution. These tests exist live on `v0.1` today — they must be passing via some mechanism (handler never reaches the lazy imports in their code paths, OR they error but the xfail strict=False swallows it). **Sage MUST verify current pytest status before issuing Warrior directives**, otherwise post-port "flip to green" claim cannot be trusted.

---

**Report path:** `/home/ishtar/Projects/bonfire-public/docs/audit/scout-reports/bon-341-machinist-20260422.md`
