# BON-341 Archivist Scout Report

**Ticket:** BON-341 — W5.2 Transfer: `knowledge/` + `scan/` (vault + scanners).
**Date:** 2026-04-22.
**Scout:** Archivist (audit-trail + documentation lens).
**Source tree:** `/home/ishtar/Projects/bonfire/src/bonfire/vault/` (12 files) + `/home/ishtar/Projects/bonfire/src/bonfire/scanners/` (3 files).
**Target:** `/home/ishtar/Projects/bonfire-public/` branch `v0.1` (tip `a04ea82`), module destinations `src/bonfire/knowledge/` + `src/bonfire/scan/` (per ADR-001 renames).

---

## 1. BON-36/37 strip list

Grep in v1 vault + scanners for `BON-36\|BON-37` yields **exactly two hits**:

| # | v1 file:line | Context (verbatim) | What it says | Recommended action |
|---|---|---|---|---|
| 1 | `bonfire/src/bonfire/scanners/fingerprinter.py:7` | Module docstring trailer: `Ticket: BON-36` | Attributes the file to Bonfire v1 ticket BON-36 (TechFingerprinter) | **STRIP** the entire `Ticket: BON-36` line from the module docstring during port. Private-lane ticket refs have no business in public code. |
| 2 | `bonfire/src/bonfire/scanners/decision_recorder.py:7` | Module docstring trailer: `Ticket: BON-37` | Attributes the file to Bonfire v1 ticket BON-37 (DecisionRecorder) | **STRIP** the entire `Ticket: BON-37` line from the module docstring during port. Same rationale. |

Vault files (`vault/*.py`) contain **zero** BON-36/37 references — they pre-date the internal ticket system. The only public-lane private-ticket-ref pollution is in the two scanner files.

Grep in public source/tests (`bonfire-public/src/ bonfire-public/tests/`) for same pattern yields **zero pre-existing hits** (the only match was `tests/e2e/scripts/e2e-runner.sh:6` referencing BON-359 — unrelated fixture work, not a vault or scanner file, no action needed).

**Linear spec matches:** The ticket description mandates "Remove BON-36/37 refs" — the two hits above are the entire strip surface.

---

## 2. Docstring survey — v1 vault/ + scanners/

Standard: **IS** = present-tense factual description of what the code does. **VISION** = aspirational / future / roadmap. **MIXED** = starts one, drifts to the other. Linear spec: "describe what it IS (vector store with provenance), not vision."

### Module docstrings

| File | Line range | First line | Classification | Rewrite needed? |
|---|---|---|---|---|
| `vault/__init__.py:1-5` | 1-5 | `"""Knowledge persistence — storage-agnostic interface.` | **IS** | No — factual. Also already uses "Knowledge" not "vault" at L1. Usable verbatim (drop "Lazy imports keep LanceDB…" line if LanceDB backend is out of scope; see note below). |
| `vault/backend.py:1-6` | 1-6 | `"""LanceDB-backed vault backend.` | **IS** | No — describes behavior (auto-migration, "vectors are NEVER re-embedded"). Factual and on-spec. |
| `vault/consumer.py:1-12` | 1-12 | `"""Vault ingest consumer — subscribes to pipeline events and stores knowledge.` | **IS** | No — three paragraphs describe listen / dedup / resilience. Pure present-tense. Update to say "Knowledge ingest consumer" and rename class per S006 scope expansion (`vault_ingest` → `knowledge_ingest`). |
| `vault/hasher.py:1-5` | 1-5 | `"""Content hashing utilities for vault dedup.` | **IS** | Minor — replace "vault" with "knowledge" to match ADR-001 rename. |
| `vault/ingest.py:1-6` | 1-6 | `"""Incremental vault ingestion with content-hash dedup.` | **MIXED** | **YES** — line 4-5 says "Ported from beta's proven patterns, adapted to v1's async VaultBackend protocol." The "ported from beta" is historical backstory (lineage prose, not IS behavior). Strip. Keep L1-3 + L6. |
| `vault/chunker.py:1-6` | 1-6 | `"""Content chunking for vault ingestion.` | **IS** | Minor — "canonical chunker — all callers delegate here" is factual. Rename "vault" → "knowledge". |
| `vault/memory.py:1-5` | 1-5 | `"""In-memory vault backend for testing.` | **IS** | No — factual. |
| `vault/embeddings.py:1-5` | 1-5 | `"""Embedding provider protocol and factory.` | **IS** | No — factual. |
| `vault/mock_embedder.py:1-5` | 1-5 | `"""Deterministic mock embedder for testing.` | **MIXED** | **YES** — line 4 says "Ported from bonfire-beta/bonfire/vault/embeddings.py (MockEmbedder)." Lineage prose. Strip. |
| `vault/ollama_embedder.py:1-5` | 1-5 | `"""Local embedding via Ollama server.` | **MIXED** | **YES** — line 3 says "Ported from bonfire-beta/bonfire/vault/embeddings.py (OllamaEmbedder)." Lineage prose. Strip. Keep L4 requirements. |
| `vault/scanner.py:1-5` | 1-5 | `"""Two-pass project scanner for vault ingestion.` | **IS** | No — two concrete pass descriptions. Rename "vault" → "knowledge". |
| `vault/backfill.py:1-6` | 1-6 | `"""Batch backfill for session handoffs and memory files.` | **IS** | No — factual. |
| `scanners/__init__.py:1` | 1 | `"""Scanner modules for Bonfire vault ingestion."""` | **IS** | Minor — rename "vault" → "knowledge" (module destination is `scan/`). |
| `scanners/fingerprinter.py:1-8` | 1-8 | `"""TechFingerprinter — one VaultEntry per detected technology.` | **IS** (but L7 `Ticket: BON-36` is the strip-target from §1) | Strip L7 only. Rename class per ADR-001: **TechFingerprinter → TechScanner**. Update L1 and class name. |
| `scanners/decision_recorder.py:1-8` | 1-8 | `"""DecisionRecorder — extract architectural decisions from markdown documents.` | **IS** (but L7 `Ticket: BON-37` is the strip-target from §1) | Strip L7 only. Class name stays per ADR-001 (no rename row for DecisionRecorder). |

### Class docstrings

| File | Class | Line | First line | Classification | Rewrite needed? |
|---|---|---|---|---|---|
| `vault/backend.py` | `LanceDBBackend` | 25 | `"""LanceDB-backed vault with auto-migration from v1 schema."""` | **IS** | Minor — "v1 schema" is historical context. Could stay as factual ("migrates from schema v1 to v2") since it describes data behavior. Optional polish. |
| `vault/consumer.py` | `VaultIngestConsumer` | 37 | `"""Subscribes to pipeline events and stores extracted knowledge in the vault."""` | **IS** | Rename class + docstring to `KnowledgeIngestConsumer` per ADR-001 + S006 scope expansion. |
| `vault/memory.py` | `InMemoryVaultBackend` | 18 | `"""In-memory vault for tests. No embeddings, substring matching."""` | **IS** | No. |
| `vault/embeddings.py` | `EmbeddingProvider` (Protocol) | 14 | `"""Protocol for embedding text into vectors."""` | **IS** | No. |
| `vault/mock_embedder.py` | `MockEmbedder` | 13 | `"""Deterministic mock embedder for testing."""` | **IS** | No. |
| `vault/ollama_embedder.py` | `OllamaEmbedder` | 16 | `"""Local embedding via Ollama server (nomic-embed-text by default).` | **IS** | No — factual, describes prefix + batch-chunk behavior. |
| `vault/scanner.py` | `FileInfo` (dataclass) | 21 | `"""Immutable record of a discovered file."""` | **IS** | No. |
| `vault/scanner.py` | `ModuleSignature` (dataclass) | 32 | `"""Extracted signature from a Python module via AST parsing."""` | **IS** | No. |
| `vault/scanner.py` | `ProjectManifest` (dataclass) | 43 | `"""Result of the discovery pass."""` | **IS** | No. |
| `vault/scanner.py` | `ProjectScanner` | 91 | `"""Two-pass project scanner.` | **IS** | No — factual two-pass description. |
| `scanners/fingerprinter.py` | `TechFingerprinter` | 108 | `"""Scan a project directory and produce one VaultEntry per technology."""` | **IS** | Rename class to **TechScanner** per ADR-001. Update "VaultEntry" to "KnowledgeEntry" if that rename lands (check Sage decision — BON-332 locked name as `VaultEntry` per protocols module, so may stay). |
| `scanners/decision_recorder.py` | `DecisionRecorder` | 81 | `"""Scan markdown files for architectural decision patterns."""` | **IS** | No. |

### Module function docstrings (spot-check)

All public async functions in `vault/ingest.py` (`ingest_markdown`, `ingest_session`, `retrieve_context`) — **IS**. Factual behavior + return-value semantics. No rewriting needed beyond the module-level `vault` → `knowledge` rename.

### Summary — vision debt

Three files carry MIXED docstrings where the "port from beta" lineage prose must be stripped:

1. `vault/ingest.py:1-6` — L4-5 "Ported from beta's proven patterns…"
2. `vault/mock_embedder.py:1-5` — L4 "Ported from bonfire-beta/…"
3. `vault/ollama_embedder.py:1-5` — L3 "Ported from bonfire-beta/…"

No docstring in either directory contains **aspirational/roadmap** language (no "will" / "future" / "eventually" / "planned"). The vision-debt surface is small: just the "ported from" lineage prose. All other docstrings already describe what the code IS.

---

## 3. Frozen audit records (DO-NOT-MODIFY)

BON-341 work MUST NOT edit any file below. These records are frozen historical evidence and must be preserved verbatim to retain audit integrity. Sage MUST include this list in Warrior SMEACs as an explicit write-denylist.

### Retrospective (`docs/audit/retrospective/`)

| File | Hit count | Hit type | Line(s) |
|---|---|---|---|
| `code-reviewer-20260418T025952Z.md` | 1 | Code-reference (checklist row) | `L36`: "VaultIngest Option A — minimal in-file stub, no vault/protocols imports" + `vault_ingest.py:13-23` path cite |
| `code-reviewer-20260418T025952Z.json` | 3 | Code-reference (structured review finding) | `L81`, `L83`, `L84`: file field + summary quoting `bonfire.vault` / `bonfire.protocols` imports absence |
| `wizard-20260418T024502Z.md` | 4 | Decision-log rationale + V1-cross-check narrative | `L91` (path), `L96` ("No `bonfire.vault.*` or `bonfire.protocols.*` imports"), `L100` (V1 cross-check narrative), `L132` (file-by-file table row) |
| `wizard-20260418T024502Z.json` | 2 | Lens-6 rationale field | `L40` ("lens_6_vault_stub": "PASS — …"), `L48` (file-comment field) |

**Total retrospective hits:** 10 lines across 4 files. All are **code-reference or decision-log rationale** — none are docstring quotes of vault code. All four are **Wave 2.3 retro artifacts** that documented the BON-333 Sage Option-A decision. Modifying any of these would corrupt the audit trail that proved the W2.3 close-PR's correctness.

### Sage decisions (`docs/audit/sage-decisions/`)

| File | Hit count | Hit type | Line(s) |
|---|---|---|---|
| `bon-333-sage-20260418T004958Z.md` | 10 | Decision-log rationale + V1 code quotes (evidence block) | `L39` ("V1 evidence — bonfire/.../vault_ingest.py"), `L42` (quoted `from bonfire.vault.consumer import VaultIngestConsumer`), `L46` ("real class lives at `bonfire.vault.consumer`"), `L48` ("`bonfire.vault.hasher.content_hash`"), `L54`, `L59`, `L66`, `L67`, `L125`, `L219` |
| `bon-342-sage.md` | 3 | Forward-reference to deferred vault-port (BON-516 lineage) | `L240` ("Depends on `bonfire.vault.scanner`..."), `L246` (BON-W5.3-vault-port specification), `L251` ("`bonfire.vault.scanner.ProjectScanner`...") |

**Total sage-decisions hits:** 13 lines across 2 files. `bon-333-sage` is the **authoritative decision log** for Option-A vault-stub. `bon-342-sage` references the **deferred vault-port** (which is this ticket: BON-341/BON-516 lineage — see §5). Modifying either would break decision-log traceability.

### Consolidated DO-NOT-MODIFY list (Warrior SMEAC instruction)

```
docs/audit/retrospective/code-reviewer-20260418T025952Z.md
docs/audit/retrospective/code-reviewer-20260418T025952Z.json
docs/audit/retrospective/wizard-20260418T024502Z.md
docs/audit/retrospective/wizard-20260418T024502Z.json
docs/audit/sage-decisions/bon-333-sage-20260418T004958Z.md
docs/audit/sage-decisions/bon-342-sage.md
```

**Rule for Sage SMEAC:** "BON-341 touches `src/` + `tests/` only. Under `docs/audit/` only the NEW scout-reports for this ticket + the NEW sage-decision for this ticket may be added. No existing file in `docs/audit/retrospective/` or `docs/audit/sage-decisions/` may be edited. These files reference `vault_ingest` / `bonfire.vault` as historical evidence of prior decisions; their text is load-bearing exactly as written."

---

## 4. Docs policy compliance (bonfire-public/docs/ top-level)

Grep + read of every file directly under `bonfire-public/docs/` (not subdirectories): 4 files total. Plus 1 ADR (docs/adr/ADR-001-naming-vocabulary.md) which is the naming policy source.

| File | References "vault"? | References "knowledge"? | Recommendation |
|---|---|---|---|
| `docs/adr/ADR-001-naming-vocabulary.md` | **YES** — L45 row `vault/` → `knowledge/` rename table | **YES** — L45 same row | **No change.** This IS the naming policy that mandates the rename. BON-341 must match it. |
| `docs/release-gates.md` | **NO** | **NO** | No change needed. Release gate discipline is module-agnostic. |
| `docs/release-gate-tickets.md` | **NO** | **NO** | No change needed. Staging doc for BON-421 epic. |
| `docs/release-policy.md` | **NO** | **NO** | No change needed. PEP 440 + yank policy, module-agnostic. |

**Result:** **Zero drift risk from docs policy.** The top-level public docs are clean. ADR-001 row 45 is the canonical contract BON-341 must honor (`vault/` → `knowledge/`, `scanners/` → `scan/`, `TechFingerprinter` → `TechScanner`).

One soft observation: neither release doc references "knowledge" as a subsystem name. That's fine — they shouldn't. Subsystem naming is ADR territory.

---

## 5. BON-333 lineage summary

Source: `docs/audit/sage-decisions/bon-333-sage-20260418T004958Z.md` (270 lines, fully read).

**What Sage decided for `vault_ingest.py` in BON-333 (Option A inline stub):**

1. BON-333's mission was W2.3 — transfer the `events/` package (EventBus + 4 consumers) to public v0.1.
2. `VaultIngestConsumer` is one of the 4 consumers — but in V1 the file at `bonfire/events/consumers/vault_ingest.py` is a **5-line re-export** from `bonfire.vault.consumer` (the real 126-LOC class).
3. The real class depends on `bonfire.protocols.VaultEntry`, `bonfire.vault.hasher.content_hash`, and a `VaultBackend` protocol.
4. Public v0.1 at BON-333 time did not have `bonfire.vault/` or `bonfire.protocols/` (though protocols shipped in BON-332 concurrent).
5. Sage declared the VaultIngestConsumer **hybrid contract**: test only the **public surface** that W2.3 owns — importability, constructor `(backend=, project_name=)`, `register(bus)` method, and 4-type subscription set `{StageCompleted, StageFailed, DispatchFailed, SessionEnded}`.
6. **Explicitly OUT of W2.3 scope** (deferred): content hashing / dedup, backend.store details, entry content format, resilience internals.
7. Sage chose **Option A (preferred)** for Warrior GREEN: inline minimal class in `src/bonfire/events/consumers/vault_ingest.py` — no imports of `bonfire.vault.*` or `bonfire.protocols.*`. Stub handlers call `backend.store(...)` if available, else no-op. 71 LOC total.
8. Sage rejected **Option B** (matching V1's re-export by stubbing a `bonfire.vault.consumer` module) because it pulled `bonfire.vault` scope forward.
9. The canonical test suite (`TestVaultIngestConsumerSurface`, 5 tests) locks ONLY the surface — backend-store semantics unchecked at W2.3.
10. The PR #21 / `e00a062` W2.3 close carried the Option-A stub into v0.1. Retrospective (Wizard `wizard-20260418T024502Z.md:L91-132`) confirms: "in-file stub (71 LOC), 4 typed subscriptions, backend.store() wrapped in try/except, no bonfire.vault.* imports."

**What was explicitly deferred (to whatever wave ports `bonfire.vault/`):**

11. The Option-A stub docstring at `src/bonfire/events/consumers/vault_ingest.py:1-12` of public v0.1 must, at BON-341 time, be **replaced** by a real consumer that imports the now-available `bonfire.knowledge.hasher.content_hash` + `bonfire.protocols.VaultEntry` (plus `VaultBackend` backend).
12. Content-hash dedup logic (v1 `consumer.py:107-110`: `if await self.backend.exists(c_hash): return`) must land.
13. VaultEntry construction with `session_id` + `event_id` metadata (v1 `consumer.py:118-122`) must land.
14. The 4 handlers (`on_stage_completed`, `on_stage_failed`, `on_dispatch_failed`, `on_session_ended`) must produce their specific `entry_type` values (`dispatch_outcome`, `error_pattern`, `error_pattern`, `session_insight`).
15. Backend-failure resilience internals (the try/except around `_store` at v1 `consumer.py:124`) — now in scope.

**What changes in BON-341 that supersedes or evolves Option A:**

- **Supersedes `bon-333 §2`** — `VaultIngestConsumer` contract expands from surface-only to full semantics.
- **Supersedes `bon-333 §Scope exclusions` L267** — "`VaultEntry` / `VaultBackend` protocol / dedup / content hash" moves from OUT-of-scope to **IN-scope**.
- **Does NOT supersede** the Option-A re-export choice — the correct move per S006 scope expansion is to **rename** the file `events/consumers/vault_ingest.py` → `events/consumers/knowledge_ingest.py` AND class `VaultIngestConsumer` → `KnowledgeIngestConsumer`, not revert to V1's re-export pattern. The inline-class approach stays; only the file/class names change and the body grows.
- **Does NOT supersede** the surface contract (constructor signature, `register(bus)`, 4-subscription set). Those are stable; new tests add semantic coverage on top.

**Recommended decision-log cite for BON-341 Sage:**

> "Supersedes `bon-333 §2` VaultIngestConsumer hybrid contract: surface-only contract expands to full semantic contract as `bonfire.knowledge.hasher` and `bonfire.protocols.VaultEntry` are now in public v0.1. Option-A inline stub at `src/bonfire/events/consumers/vault_ingest.py` is REPLACED (not re-exported) with a full `KnowledgeIngestConsumer` at `src/bonfire/events/consumers/knowledge_ingest.py`. S006 scope-expansion mandates the rename per ADR-001."

---

## 6. Prior session continuity

Sources: `2026-04-20-bonfire-public-s006-handoff.md` (298 lines, fully read) + `2026-04-21-bonfire-public-s007-handoff.md` (273 lines, fully read).

**Confirmed scope expansion (S006 → BON-341):**

- S006 handoff `L13`: "BON-341 scope-expanded with vault_ingest rename."
- S006 `L142`: "BON-341 scope-expanded via comment `9cc2e08f-711f-4cc3-b8c6-634c9c13c543` — adds the `vault_ingest` → `knowledge_ingest` rename to W5.2 scope. Bundled per Anta's direction; the rename rides the parent vault→knowledge wave rather than a standalone follow-up."
- S006 `L237`: "BON-341 knowledge/ + scan/ — vault seam. Consider a single vault-design scout before Knights. Also absorbs the `events/consumers/vault_ingest` rename per S006 scope expansion."
- S007 `L53`: "BON-341 (knowledge/ + scan/ — vault seam + events/consumers/vault_ingest → knowledge_ingest rename per S006 scope expansion)."
- S007 `L195`: "BON-341 knowledge/ + scan/ (absorbs events/consumers/vault_ingest → knowledge_ingest rename per S006 scope expansion)."

**No additional rename plans found.** The scope expansion is exactly one file + one class rename on top of the port. No hidden renames in S006/S007 that affect `vault` / `knowledge` terminology beyond ADR-001's locked list.

**Related v1-follow-up tickets that touch BON-341 scope:**

- **BON-516** (filed S007, `W5.3 follow-up: vault-port`) — handoff S007 `L144`: "When **BON-516 vault-port** lands, it will flip 7 stacked-xfail architect tests GREEN via the per-dep marker chain Sage §D7 designed." S007 `L225`: "`/home/ishtar/Projects/bonfire/src/bonfire/vault/{memory,scanner,chunker}.py` — source for BON-516." Per S007 `L140`, BON-516 targets: "bonfire.vault.memory + scanner + chunker". **NOTE:** BON-516 and BON-341 overlap heavily — BON-341 is the broader W5.2 port (all 12 vault files + 2 scanner files). Sage should verify with Anta whether BON-341 subsumes BON-516 or whether BON-516 is a strict subset that ships inside BON-341. (S006 `L245` Sage-proposal entry originally scoped BON-W5.3-vault-port as: "memory + scanner + chunker{chunk_markdown, chunk_source_file, content_hash}" — a subset of the full 12-file vault.)
- **BON-514** (filed S007, `W5.3 follow-up: meta-ports`) — orthogonal to BON-341; touches `bonfire.models.envelope` + `bonfire.models.events`, not vault.
- **BON-515** (filed S007, `W5.3 follow-up: protocol-widen`) — orthogonal; touches `bonfire.protocols.DispatchOptions` + `PipelineConfig`, not vault.

**Cross-wave hazard reminder (S007 `L157-158`):**

> "Sibling-batch Sages synthesizing independently can produce contracts that interfere on merge. Current mitigation: Wizard manually runs `PYTHONPATH=<merged-tip>/src pytest tests/` preflight."

BON-341 is a solo ticket in Sub-batch 2b with BON-344 (xp/). BON-344 touches `src/bonfire/xp/` — zero overlap with `knowledge/` or `scan/`. Cross-wave collision risk is **low**, but Wizard must still run preflight before merging the second of the two PRs per BON-519 discipline.

**Editable-install hazard (S007 `L161` + extended memory):**

> "Worktree-isolated pytest needs `PYTHONPATH=<worktree>/src pytest` not just for module imports but also for `importlib.resources.files()` resource loading."

BON-341 does not ship TOML assets (vault + scanners are pure Python), so the `importlib.resources` extension does not apply. But the Mode-1 hazard (`PYTHONPATH=<worktree>/src pytest` during Warrior verification) still applies.

**Operation Splatter context:**

S007 spun up **Operation Splatter** (Linear project `3d6aeffb-22a8-49cd-86c1-3c655efaeeb3`) — blocks BON-355 (v0.1.0 tag). BON-341 is NOT in Operation Splatter; it's feature work in the main Bonfire Free project. But any pipeline defects discovered during BON-341 execution (e.g., another cross-wave interaction, another under-marked xfail) should be filed into Operation Splatter, not bundled into this ticket.

---

## Historical gotchas — three bullets for Sage

- **`events/consumers/vault_ingest.py` IS NOT a virgin port target** — Option-A inline stub shipped at `e00a062` and is frozen in PR #21 retrospectives. BON-341 must **replace + rename** the file (to `knowledge_ingest.py`) and **replace + rename** the class (to `KnowledgeIngestConsumer`). Don't pretend the stub isn't there; the decision log at `bon-333-sage-20260418T004958Z.md §2` explicitly deferred semantic depth to "whatever wave transfers `bonfire.vault/`" — that wave is now.
- **Three "Ported from beta" lineage docstrings must be stripped** (`vault/ingest.py:4-5`, `vault/mock_embedder.py:4`, `vault/ollama_embedder.py:3`) along with the two `Ticket: BON-36/37` module-docstring lines in scanners. Public code carries no private-lineage prose; the Linear spec rule "describe what it IS, not vision" catches both the lineage prose and the ticket-ref prose under the same standard.
- **BON-516 (vault-port follow-up) overlaps BON-341** — BON-516 was filed S007 targeting `bonfire.vault.{memory,scanner,chunker}` as a 3-file subset to unblock stacked-xfail architect tests. BON-341's full W5.2 port is a 15-file superset. Sage should verify with Anta whether BON-341 **subsumes** BON-516 (close BON-516 as done-by-BON-341) or **ships it separately first** (land BON-516 as a narrow unblocker, then BON-341 as the remainder). Test-baseline impact: BON-516 alone flips 7 stacked-xfail architect tests GREEN (per S007 `L144`) — BON-341 will also flip those plus any consumer-semantic xfails created in BON-333 testing.

---

**Report path:** `/home/ishtar/Projects/bonfire-public/docs/audit/scout-reports/bon-341-archivist-20260422.md`
