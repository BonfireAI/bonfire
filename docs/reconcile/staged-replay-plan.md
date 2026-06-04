# Staged-Replay Plan — building the v1 release trunk from `main` ↔ `v0.1`

## Why this document exists

`bonfire-public` has two long-lived branches that have **truly forked**, not drifted:

- `origin/v0.1` — the branch that ships the released PyPI package (version **1.0.1**, Production/Stable). It is a deep, security-hardened tree, not a thin "opinion package."
- `origin/main` — a near-total rebuild carrying the newer Elegance-Law failure taxonomy, the retrieval/knowledge subsystem, the shared timeout resolver, the agent-as-subagent install rails, and a Mirror/verify protocol vocabulary.

Their merge-base is nearly empty — it contained essentially one model file. Everything else (`errors.py`, `envelope.py`, `events.py`, `config.py`, `plan.py`, the dispatch layer, the onboard scanners, the security layer) was **built independently on both sides**. A direct three-way merge produces ~131 conflicts, and many of `main`'s files are a **net removal** of safety that `v0.1` shipped.

The reconcile strategy is **Shape A — make a release trunk** by staging `main`'s genuine additions onto a branch that starts from `v0.1` (the shipped, hardened tree). The branch is `reconcile/v1-trunk`, which begins life byte-identical to `origin/v0.1`. Each topic below **surgically grafts a `main` addition onto the `v0.1` file** — it never full-file-ports from `main`, because a wholesale copy silently deletes hardening that `v0.1` already shipped.

This document is the ordered, executable plan: the topic sequence, the files each touches, the union landmines each must not trip, and the gate plan for each.

---

## The cardinal rule: the two-dot diff is the truth, the three-dot diff lies

Because the merge-base is nearly empty, the three-dot form `git diff origin/v0.1...origin/main` shows only `main`-side additions and presents many files as brand-new `+N/0` adds. That view is **misleading** — it hides every deletion `main` made relative to `v0.1`.

The load-bearing comparison is the **two-dot tip diff** `git diff origin/v0.1..origin/main -- <path>`, which exposes the deletions. Read the numstat for the model layer:

| File | two-dot numstat (`v0.1..main`) | reading |
|---|---|---|
| `errors.py` | `190 / 0` | a genuine, clean ADD (no `v0.1` counterpart) |
| `models/envelope.py` | `17 / 36` | a **net removal** wearing the mask of an add |
| `models/events.py` | `1 / 96` | `main` adds nothing; it only strips a validator import |
| `models/config.py` | `0 / 6` | pure removal |
| `models/plan.py` | `3 / 3` | a rename, not content |
| `models/__init__.py` | `1 / 1` | a rename consumer |

Every model file except `errors.py` is a **net removal on `main`**. The only way to lose `v0.1`'s security validators, the `trust_project_settings` gate, the richer failure events, `_safe_read`/`_safe_write`, the `install-skill` surface, the ISM package, and the optimized LanceDB path is a naive `git show origin/main:<file> > <file>` port.

**Worked example — the `envelope_id` path-traversal validator.** `v0.1`'s `models/envelope.py` carries `_ENVELOPE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}\Z")` plus the `@field_validator('envelope_id')` `_envelope_id_must_be_path_safe`. Because `envelope_id` is interpolated into checkpoint and session write paths, that validator rejects `../`, `/`, `\`, NUL, control characters, and the trailing-newline shape (the regex anchor is `\Z`, deliberately not `$`). Without it, an attacker-controlled `envelope_id` such as `../../etc/passwd` smuggles writes outside the operator directory. `main`'s `envelope.py` has **no validator at all** — it is a parallel build from the near-empty merge-base, not a deletion-with-intent. Porting `main`'s file wholesale would silently re-open the hole. The correct replay starts from `v0.1`'s `envelope.py`, **keeps** `import re` and the validator, and **adds only** the one `from_exception` classmethod (plus `import traceback`). The pinning test `tests/unit/test_session_id_path_traversal_reject.py` exists only on `v0.1` and must stay green throughout.

This same pattern — *"`main` thinned a `v0.1`-hardened path-traversal validator"* — recurs at `models/events.py` (`session_id`), `dispatch/security_hooks.py` (write-path canonicalization), `onboard/scanners/git_state.py` (credential stripping), and `onboard/scanners/vault_seed.py` (anti-DoS walk). Treat every one of them with the same surgical discipline.

---

## Dependency spine

```
Topic 1  errors.py taxonomy            (IN FLIGHT / done-context)
   │        (depends on envelope.from_exception, which it carries together)
   ├── Topic 2  envelope.from_exception        (root of the taxonomy graph)
   │
   ├── Topic 3  packaging + version truth       (foundational; no deps)
   ├── Topic 4  safe-IO guard                   (deps: 3)
   ├── Topic 5  protocols.py superset           (deps: envelope/ErrorDetail)
   ├── Topic 6  timeouts.py foundation          (leaf; no deps)
   │
   ├── Topic 7  retrieval Protocol seam         (deps: 5)
   │      └── Topic 8  Tier-1 provider + discovery   (deps: 7)
   │             └── Topic 9  retrieval MCP server    (deps: 6, 8)
   │      └── Topic 10 prebake seam (dormant)         (deps: 6, 7)
   │
   ├── Topic 11 knowledge observability + dedup (no deps)
   ├── Topic 12 knowledge backend union         (no deps; union, not port)
   │
   ├── Topic 13 dispatch runner terminality     (deps: 1)
   ├── Topic 14 sdk_backend + config reconcile  (deps: 1, 3)
   ├── Topic 15 ollama_embedder typed failure   (deps: 1)
   ├── Topic 16 dispatch security reconcile      (no rename dep; sibling of Topic 2)
   ├── Topic 17 handler-seam dispatch parity     (deps: 1 if it adopts ErrorDetail)
   │
   ├── Topic 18 WorkflowSpec rename             (SEPARATE; only if Anta wants it)
   │      └── Topic 19 engine StageExecutor + error_detail + Wave-11 union (deps: 1, 2, 18)
   │
   ├── Topic 20 agent/CLI backend-install + app.py two-way merge (deps: 3, 4)
   ├── Topic 21 ISM integrations + CI/dev tooling preserve        (deps: 3)
   └── Topic 22 doc reconcile (README/CHANGELOG/stratum guard)    (deps: 20)

NON-topic  events.py — do NOT replay from main. v0.1's is strictly richer + safer.
```

---

## Topic 1 — errors.py taxonomy + Elegance-Law containment (IN FLIGHT / done-context)

**Slug:** `topic-1-errors-taxonomy`
**Status:** already in flight in a separate lane worktree. Listed here as the dependency root so the rest of the plan sequences against it.

**Files added** (pure ADD — no `v0.1` counterpart to merge):

- `src/bonfire/errors.py`
- `tests/unit/test_errors.py`
- `tests/unit/test_errors_containment.py`
- `docs/adr/ADR-002-failure-architecture.md`

**What it adds.** The entire failure vocabulary: `BonfireError` base (with `is_terminal` ClassVar, `code` ClassVar, a `retryable` property, and a `context` dict) plus thirteen typed subclasses — `ConfigError`, `AgentError`, `RateLimitError`, `CLINotFoundError`, `ExecutorError` (terminal); `RetrievalError`, `SubprocessError`, `TimeoutError_`, `NetworkError`, `ValidationError`, `SchemaError`, `IsolationError` (recoverable) — together with the `contain_as_error` context manager and its `_ErrorBox` carrier (the never-raise shell). The module is import-cycle-free: it imports nothing from `bonfire.*` at load time and pulls `ErrorDetail` in lazily under `TYPE_CHECKING` plus a deferred import. Its only real coupling is `ErrorDetail.from_exception` from the envelope, which is why Topic 2 must land first within the taxonomy.

**Depends on.** `ErrorDetail.from_exception` (Topic 2). Strictly: envelope → errors → every call-site wiring.

**Union landmines.** None inside this topic — it is a clean add with no `v0.1` file to merge. Downstream topics (13, 14, 15, 19) are **gated** on it: `v0.1` has no `bonfire.errors` module at all, so any typed-failure conversion must wait for it.

**Stratum hygiene.** The ADR-002 doc body and the `errors.py` docstrings must stay tag-free (they currently are). Ticket and memo references belong in the commit/PR body, never in the shipped doc or docstring.

---

## Topic 2 — envelope.from_exception (root of the taxonomy graph)

**Slug:** `topic-2-envelope-from-exception`

**Files:**

- `src/bonfire/models/envelope.py`

**What it adds.** Onto `v0.1`'s `envelope.py`, add **only** the `ErrorDetail.from_exception(exc, *, stage_name)` classmethod plus `import traceback`. The classmethod builds `error_type=type(exc).__name__`, `message=str(exc)`, `traceback=traceback.format_exc()`, and `stage_name=...`; it must be called inside the `except` block so the traceback is live. `ErrorDetail`'s fields are byte-identical between the branches (`error_type`, `message`, `traceback`, `stage_name`) — `from_exception` is the sole real add. It is consumed in `main` by `dispatch/sdk_backend.py` (three sites), `engine/pipeline.py`, and `handlers/merge_preflight.py`.

**Depends on.** Nothing inside its own area — this is the root. Topic 1's errors module depends on it.

**Union landmines (the worked example).** Porting `main`'s `envelope.py` wholesale **deletes** `_ENVELOPE_ID_RE` and the `_envelope_id_must_be_path_safe` field validator and drops `import re`. The two-dot tip diff is `+17 / -36` — a net removal masquerading as an add. **Correct replay:** start from `v0.1`'s `envelope.py`, add only `from_exception` + `import traceback`, keep `import re` and the validator. The pinning test `tests/unit/test_session_id_path_traversal_reject.py` (present only on `v0.1`) must stay green.

**Gate plan.**

```
ruff check src/bonfire/models/envelope.py
ruff format --check src/bonfire/models/envelope.py
pytest tests/unit/test_session_id_path_traversal_reject.py -q
pytest tests/unit -q -k envelope
```

---

## Topic 3 — packaging + version truth (foundational, do early)

**Slug:** `topic-3-packaging-version-truth`

**Files:**

- `pyproject.toml`
- `src/bonfire/__init__.py`

**What it adds / preserves.** Lock the packaging contract before any other replay can regress it. The wheel-include list must be the **union**: keep `src/bonfire/skill/*.md` and `src/bonfire/integrations/builtins/*.ism.md` and `onboard/ui.html` and `py.typed`, and **add** `main`'s `src/bonfire/prompts/*.md`. Keep `v0.1`'s `version = "1.0.1"`, `Development Status :: 5 - Production/Stable`, and the pinned `ruff == 0.15.13`. In the package `__init__.py`, keep the `1.0.1` editable-fallback `__version__` but **add** `main`'s Verdict-family re-export and `__all__` entries.

**Depends on.** Nothing. Unblocks every later topic by freezing the version/packaging contract.

**Union landmines.**

- `pyproject.toml` — porting `main`'s `[tool.hatch.build.targets.wheel].include` drops the `skill/*.md` and `*.ism.md` globs (replacing them with `prompts/*.md` only), producing a wheel that ships no `SKILL.md` and no ISM manifests even if the source files survive — `install-skill` would have nothing to copy. The include must be the union.
- Do **not** take `main`'s `version = "0.1.0a2"`, `Development Status :: 3 - Alpha`, or `ruff >= 0.8`. **PyPI 1.0.1 is the truth.** The local `0.1.0a2` literal is stale.
- `src/bonfire/__init__.py` — porting `main`'s version regresses the editable fallback from `1.0.1` to `0.1.0a2`. Keep `1.0.1`; do add the Verdict-family re-export.

**Gate plan.**

```
ruff check src/bonfire/__init__.py
ruff format --check src/bonfire/__init__.py
python -c "import bonfire, sys; print(bonfire.__version__); sys.exit(0 if bonfire.__version__=='1.0.1' else 1)"
python -m build --wheel 2>/dev/null && unzip -l dist/*.whl | grep -E "SKILL.md|github.ism.md|prompts/.*\.md|ui.html|py.typed"
```

---

## Topic 4 — safe-IO guard (`_safe_read` / `_safe_write` survive)

**Slug:** `topic-4-safe-io-guard`

**Files (preserve as-is; this is a guard, not a port):**

- `src/bonfire/_safe_read.py`
- `src/bonfire/_safe_write.py`
- `tests/unit/test_safe_read.py`, `test_safe_write.py`, `test_safe_append.py`, `test_safe_read_capped.py`

**What it adds.** The trunk (starting from `v0.1`) already has these two security primitives: a size-capped, symlink-target-aware reader and a symlink-refusing `O_NOFOLLOW`+`O_EXCL` writer. `main` has **neither**, and none of the twelve files that route through them on `v0.1` use them. This topic establishes a guard rule: no later `main`-port may delete a `safe_read`/`safe_write` call site or downgrade it to a raw `read_text()`/`write_text()`.

**Depends on.** Topic 3 (the wheel/packaging contract).

**Union landmines.** `_safe_read.safe_read_text` is consumed by twelve `v0.1` modules — `init`, `install_skill`, `persona`, `cost/consumer`, `engine/checkpoint`, `onboard/config_generator`, the three `onboard/scanners/{claude_memory,mcp_servers,vault_seed}`, `scan/tech_scanner`, `session/persistence`, `xp/tracker` (plus `_safe_write` itself). Porting **any** of those twelve files from `main` silently strips the hardening at that call site. The guard ships a regression test that greps for the imports across the consumer set.

**Gate plan.**

```
ruff check src/bonfire/_safe_read.py src/bonfire/_safe_write.py
ruff format --check src/bonfire/_safe_read.py src/bonfire/_safe_write.py
pytest tests/unit/test_safe_read.py tests/unit/test_safe_write.py tests/unit/test_safe_append.py tests/unit/test_safe_read_capped.py -q
grep -rEl "safe_read_text|safe_write" src/bonfire | wc -l   # expect the full consumer web intact
```

---

## Topic 5 — protocols.py superset (additive block only)

**Slug:** `topic-5-protocols-superset`

**Files:**

- `src/bonfire/protocols.py`

**What it adds.** `main` is a strict class-superset of `v0.1`'s protocols (no `v0.1` protocol deleted; `AgentBackend`/`DispatchOptions`/`VaultEntry`/`VaultBackend`/`QualityGate`/`StageHandler` retained, several byte-identical). `main` adds the Mirror/verify vocabulary — `Severity`, `VerdictStatus`, `Finding`, `MuscleWriteReceipt`, `Verdict`, `ProbeFinding`, `AxiomVariantReceipt`, `ValidationOutcome`, `ArtificerReport`, `BracketPassReport` — plus the retrieval seam `ContextAtom` and the `@runtime_checkable RetrievalProvider` Protocol. Add these classes on top of `v0.1`'s retained core, with their `__all__` entries.

**Depends on.** The added pydantic models reference the broader `main` type tree; verify imports resolve (envelope/ErrorDetail in particular). The core `AgentBackend`/`StageHandler` half is rename- and errors-independent and can go early.

**Union landmines.** `protocols.py` is a **shared file across multiple lanes** — a topic that rewrites the whole file collides with other lanes' additions. **Append** the new class blocks onto `v0.1`'s `protocols.py`; do not regenerate the file. Leave `v0.1`'s retained Protocols intact. Coordinate so the retrieval lane (Topic 7) and the verify-vocabulary additions land as appends, not a rewrite.

**Gate plan.**

```
ruff check src/bonfire/protocols.py
ruff format --check src/bonfire/protocols.py
python -c "import bonfire.protocols as p; [getattr(p, n) for n in ('AgentBackend','StageHandler','VaultBackend','ContextAtom','RetrievalProvider','Verdict','Finding')]"
pytest tests/unit -q -k "protocol or retrieval_provider_protocol"
```

---

## Topic 6 — timeouts.py foundation (leaf, land first in the timeout/retrieval chain)

**Slug:** `topic-6-timeouts-foundation`

**Files:**

- `src/bonfire/timeouts.py`
- `tests/unit/test_timeouts.py`

**What it adds.** A shared timeout-resolution module that `v0.1` lacks entirely (every timeout there is an inline literal). It ships `DEFAULT_TIMEOUTS` (`version=5.0`, `capability=2.0`, `git=5.0`, `pytest=300.0`, `retrieve=30.0`, `dispatch=None`), `resolve_timeout(kind, override=, env_var=)` with precedence override > env > default and a `KeyError` on unknown kind, plus the per-call `retrieve_timeout()` / `DEFAULT_RETRIEVE_TIMEOUT_S` / env `BONFIRE_RETRIEVE_TIMEOUT_S`. Then re-route `v0.1`'s inline literals through `resolve_timeout(...)` **only where behavior-preserving**: `cli_toolchain` (version/capability), and `git_state`'s git timeout (while keeping `v0.1`'s `sanitize_remote_url` — that is a union, handled in Topic 16, not a port).

**Depends on.** Nothing — pure stdlib `os.getenv`, zero-conflict new file. The `pytest=300/600` re-route in `merge_preflight` belongs to the handlers lane, not here.

**Union landmines.** None for the new module itself. When re-routing `git_state`'s timeout, do not touch the credential-stripping body (Topic 16's territory).

**Gate plan.**

```
ruff check src/bonfire/timeouts.py
ruff format --check src/bonfire/timeouts.py
pytest tests/unit/test_timeouts.py -q
```

---

## Topic 7 — retrieval Protocol seam

**Slug:** `topic-7-retrieval-protocol-seam`

**Files:**

- `src/bonfire/protocols.py` (the `ContextAtom` + `RetrievalProvider` block — coordinate with Topic 5)
- `tests/unit/test_retrieval_provider_protocol.py`
- `tests/unit/test_vaultbackend_stable_surface_docs.py`

**What it adds.** `ContextAtom` (a `BaseModel` with `key`, `body`, `source_path`, `score`) and the `@runtime_checkable RetrievalProvider` Protocol (`async retrieve(query, seed_keys=None, token_budget=4000) -> list[ContextAtom]`). For this topic, port **only** those two classes plus their two `__all__` entries.

**Depends on.** Nothing structural (pydantic `BaseModel` + `typing.Protocol`). Land as an append to avoid the shared-file collision (see Topic 5).

**Union landmines.** Same shared-file caution as Topic 5 — append, never rewrite, `protocols.py`.

**Gate plan.**

```
ruff check src/bonfire/protocols.py
ruff format --check src/bonfire/protocols.py
pytest tests/unit/test_retrieval_provider_protocol.py tests/unit/test_vaultbackend_stable_surface_docs.py -q
```

---

## Topic 8 — Tier-1 provider + discovery

**Slug:** `topic-8-tier1-provider-discovery`

**Files:**

- `src/bonfire/knowledge/retrieval_provider.py`
- `src/bonfire/_discovery.py`
- `tests/unit/test_ripgrep_retrieval_provider.py`

**What it adds.** `RipgrepRetrievalProvider`, an async wrapper over `VaultBackend.query()` that maps `VaultEntry` → `ContextAtom` (uniform `score=1.0`; `seed_keys`/`token_budget` accepted-but-ignored at Tier 1, honored at Tier 2/Pantheon). And `discover_retrieval_provider()` (`lru_cache maxsize=1`), which tries the optional `bonfire.arachne.provider:ArachneRetrievalProvider` (Tier 2) and falls back to `RipgrepRetrievalProvider` built from `bonfire.knowledge.get_vault_backend()`. The `try/except ImportError` gate keeps `bonfire-public` PyPI-safe with no Pantheon dependency.

**Depends on.** Topic 7 (`ContextAtom`/`RetrievalProvider`) and the existing `knowledge.get_vault_backend` (identical on both branches).

**Union landmines.** None unique — uses `VaultBackend`, byte-identical across branches.

**Gate plan.**

```
ruff check src/bonfire/knowledge/retrieval_provider.py src/bonfire/_discovery.py
ruff format --check src/bonfire/knowledge/retrieval_provider.py src/bonfire/_discovery.py
pytest tests/unit/test_ripgrep_retrieval_provider.py -q
```

---

## Topic 9 — retrieval MCP server

**Slug:** `topic-9-retrieval-mcp-server`

**Files:**

- `src/bonfire/mcp/__init__.py`
- `src/bonfire/mcp/retrieval_server.py`
- `tests/integration/test_retrieval_mcp_server.py`
- `tests/integration/test_retrieval_mcp_server_timeout.py`

**What it adds.** A new `mcp/` package (absent on `v0.1`) plus the `retrieve_context` stdio server. The public `handle_retrieve_context(query, token_budget=4000, provider=None)` runs the discovered provider under `asyncio.wait_for(timeout=retrieve_timeout())`, formats atoms as a tool string, and contains all failure (timeout → message; any exception → typed message). `_main()` launches an `mcp.server.Server` stdio server with a `try/except ImportError -> exit 2` if the optional `mcp` package is missing, while the handler stays an in-process callable. No `pyproject` `mcp` dependency or console-script is added — it is launched via `python -m bonfire.mcp.retrieval_server`.

**Depends on.** Topic 6 (`retrieve_timeout`) and Topic 8 (`discover_retrieval_provider`). `mcp` is an **optional runtime import, not a hard dep**.

**Union landmines.** None — no `pyproject` dependency or console-script addition (keep it optional-import only, so Topic 3's packaging contract is unaffected).

**Gate plan.**

```
ruff check src/bonfire/mcp/__init__.py src/bonfire/mcp/retrieval_server.py
ruff format --check src/bonfire/mcp/__init__.py src/bonfire/mcp/retrieval_server.py
pytest tests/integration/test_retrieval_mcp_server.py tests/integration/test_retrieval_mcp_server_timeout.py -q
```

---

## Topic 10 — prebake seam (dormant)

**Slug:** `topic-10-prebake-seam`

**Files:**

- `src/bonfire/prompt/precompose.py`
- `tests/unit/test_prebake_retrieval.py`

**What it adds.** A second retrieval call site, `prebake_retrieval(task, *, provider, token_budget=4000)`, returning a dict shaped for `reach_context.update(...)` (`{'retrieved_atoms': [atom.model_dump() ...]}`). It is import-cheap; `provider=None` returns `{}`; all failure (timeout / any exception) logs WARN and returns `{}` — retrieval never breaks dispatch. It is a **dormant seam**: its own docstring notes that no dispatch entry wires it in yet, so there is no dispatch-side coupling to port.

**Depends on.** Topic 6 (`retrieve_timeout`) and Topic 7 (`RetrievalProvider`). Shares the resolver with the MCP server (single source of truth).

**Union landmines.** None — no dispatch wiring.

**Gate plan.**

```
ruff check src/bonfire/prompt/precompose.py
ruff format --check src/bonfire/prompt/precompose.py
pytest tests/unit/test_prebake_retrieval.py -q
```

---

## Topic 11 — knowledge observability + event-id-scoped dedup

**Slug:** `topic-11-knowledge-observability-dedup`

**Files:**

- `src/bonfire/knowledge/scanner.py`
- `src/bonfire/knowledge/consumer.py`
- `tests/unit/test_knowledge_consumer_event_id_dedup.py`

**What it adds.** Scanner DEBUG narration on the three skip paths (unreadable file, unreadable Python file, unparseable Python file), so silent drops in the manifest/signature scan become observable — purely additive over `v0.1`. And a dedup-key change in the consumer from `content_hash(content)` to `content_hash(f'{event.event_id}\n{content}')`, so two distinct events with identical content text are both stored while a re-fired event (same `event_id`) is still suppressed. This is a genuine improvement, not a regression — port it **with its test**.

**Depends on.** Nothing; independent of the retrieval seam.

**Union landmines.** None — both deltas are additive over `v0.1`.

**Gate plan.**

```
ruff check src/bonfire/knowledge/scanner.py src/bonfire/knowledge/consumer.py
ruff format --check src/bonfire/knowledge/scanner.py src/bonfire/knowledge/consumer.py
pytest tests/unit/test_knowledge_consumer_event_id_dedup.py -q
```

---

## Topic 12 — knowledge backend union (do carefully; union, not port)

**Slug:** `topic-12-knowledge-backend-union`

**Files:**

- `src/bonfire/knowledge/backend.py`
- `src/bonfire/knowledge/memory.py`
- `tests/unit/test_memory_vault.py` (keep, `v0.1`)
- `tests/unit/test_knowledge_memory_performance.py` (keep, `main`)
- `tests/unit/test_vaultbackend_stable_surface_docs.py`

**What it adds.** Keep `v0.1`'s **optimized** LanceDB `exists()` — the filter-only `.search().where(content_hash=...)` with no query vector — and add **only** `main`'s one-line `logger.warning('Vault exists check failed: %s', exc)` on the except path (`v0.1` swallows it silently). Net: `v0.1` perf plus `main` observability. For `memory.py`, reconcile the same O(1)/no-re-lower optimization that both branches forked under different private attribute names; pick one scheme and keep **both** performance tests green.

**Depends on.** Nothing; pure union.

**Union landmines.**

- `backend.py` — porting `main`'s `exists()` **reverts** `v0.1`'s filter-only optimization back to the zero-vector ANN scan (`search([0.0]*dim)`) plus a redundant `count_rows()==0` short-circuit (a perf regression that scores a zero vector against the ANN index). Keep `v0.1`'s body; graft only the warning line.
- `memory.py` — `v0.1` uses `_hash_set`/`_lower_cache` (lazy lower on first query); `main` uses `_hashes`/`_lower_content` (eager lower at store, dict keyed by `entry_id`). No `v0.1` test asserts the private names, so a rename is safe — but `main`'s `query()` pre-filters candidates by `entry_type` and reads `_lower_content[e.entry_id]` (assumes `entry_id` uniqueness across the dict). Whichever version wins, keep `test_memory_vault.py` **and** `test_knowledge_memory_performance.py` green so neither the no-re-lower nor the O(1)-exists property regresses.

**Gate plan.**

```
ruff check src/bonfire/knowledge/backend.py src/bonfire/knowledge/memory.py
ruff format --check src/bonfire/knowledge/backend.py src/bonfire/knowledge/memory.py
pytest tests/unit/test_memory_vault.py tests/unit/test_knowledge_memory_performance.py tests/unit/test_vaultbackend_stable_surface_docs.py -q
```

---

## Topic 13 — dispatch runner terminality → typed taxonomy

**Slug:** `topic-13-runner-terminality`

**Files:**

- `src/bonfire/dispatch/runner.py`

**What it adds.** Rewire retry terminality from `v0.1`'s hard-coded `_TERMINAL_ERROR_TYPES` frozenset to the typed taxonomy: build `_ERROR_CODE_TO_CLASS` by reflecting over `bonfire.errors` `BonfireError` subclasses, and read `cls.is_terminal` via a new `_is_terminal_error_type(error_type)` helper. An unknown `error_type` stays retryable (preserves the prior default).

**Depends on.** Topic 1 — a **hard** dependency. `runner.py` imports `from bonfire.errors import BonfireError` and `from bonfire import errors as errors_module`. Cannot replay before Topic 1 lands.

**Union landmines.** None unique — but it is errors-gated; do not stub the import.

**Gate plan.**

```
ruff check src/bonfire/dispatch/runner.py
ruff format --check src/bonfire/dispatch/runner.py
pytest tests/unit -q -k "runner or terminal or retry"
```

---

## Topic 14 — sdk_backend + config reconcile (two-way merge, highest security risk)

**Slug:** `topic-14-sdk-backend-config-reconcile`

**Files:**

- `src/bonfire/dispatch/sdk_backend.py`
- `src/bonfire/dispatch/_cost.py`
- `src/bonfire/models/config.py`
- `tests/unit/test_sdk_backend_setting_sources_gate.py`
- `tests/dispatch/test_trust_project_settings_key.py`
- `tests/unit/test_sdk_backend_traceback_redaction.py`

**What it adds.** Add `main`'s Elegance-Law typed-failure path — `ErrorDetail.from_exception`, typed `AgentError`/`RateLimitError` raised-and-captured, and `dispatch/_cost.safe_cost_from_attr` — **into** `v0.1`'s `sdk_backend.py`, while keeping `v0.1`'s security guards.

**Depends on.** Topic 1 (errors.py) and Topic 3 (packaging). Apply as an ADD-into-the-`v0.1`-file, never a wholesale port.

**Union landmines (two-way, same shape as Topic 2's envelope landmine).**

- `sdk_backend.py` — porting `main`'s file **deletes** (a) `_resolve_setting_sources` / `_bonfire_toml_opts_in`, the deny-by-default project-settings gate (`main` hardcodes `setting_sources=['project']`, which silently ingests a foreign repo's `CLAUDE.md` / `.claude/settings.json` into every dispatched agent's system prompt — an arbitrary-instruction-injection primitive); and (b) `_summarise_traceback` / `_format_error_traceback`, the `BONFIRE_DEBUG_TRACEBACKS`-gated redaction that strips local-frame repr (prompt text, env-derived options, often secrets) from persisted JSONL error logs. The replay must add `main`'s typed-error path **while keeping** the setting-sources gate and the traceback redaction layered under it.
- `models/config.py` — porting `main`'s `PipelineConfig` deletes the `trust_project_settings: bool = False` field (the typed opt-in backing the gate). Keep the field and its doc comment. The two-dot diff is `0 / 6` (pure removal).

**Gate plan.**

```
ruff check src/bonfire/dispatch/sdk_backend.py src/bonfire/dispatch/_cost.py src/bonfire/models/config.py
ruff format --check src/bonfire/dispatch/sdk_backend.py src/bonfire/dispatch/_cost.py src/bonfire/models/config.py
pytest tests/unit/test_sdk_backend_setting_sources_gate.py tests/dispatch/test_trust_project_settings_key.py tests/unit/test_sdk_backend_traceback_redaction.py -q
```

---

## Topic 15 — ollama_embedder typed failure

**Slug:** `topic-15-ollama-embedder-typed-failure`

**Files:**

- `src/bonfire/knowledge/ollama_embedder.py`

**What it adds.** Swap `raise RuntimeError(...)` → `raise NetworkError(...)` / `raise RetrievalError(...)` from `bonfire.errors` (the Elegance-Law typed-failure conversion).

**Depends on.** Topic 1 — `v0.1` has no `bonfire.errors` module at all, so this file's port is gated on the taxonomy landing first. Sequence after Topic 1.

**Union landmines.** None unique — purely a typed-exception swap.

**Gate plan.**

```
ruff check src/bonfire/knowledge/ollama_embedder.py
ruff format --check src/bonfire/knowledge/ollama_embedder.py
pytest tests/unit -q -k "ollama or embedder"
```

---

## Topic 16 — dispatch security surface reconciliation (high risk)

**Slug:** `topic-16-dispatch-security-reconcile`

**Files:**

- `src/bonfire/dispatch/security_hooks.py`
- `src/bonfire/dispatch/security_patterns.py`
- `src/bonfire/dispatch/__init__.py`
- `src/bonfire/dispatch/tool_policy.py`
- `src/bonfire/onboard/scanners/git_state.py`
- `src/bonfire/onboard/scanners/vault_seed.py`
- `src/bonfire/onboard/flow.py`
- the C-pattern + security-hooks + git_state + vault_seed + onboard-flow tests (`test_git_state_sanitize.py`, `test_onboard_scanner_git_state.py`, `test_vault_seed_hardening.py`, `test_onboard_flow_timeout.py`, `test_security_hooks_*`)

**What it adds.** This topic is **all union, no port** — it is the sibling cluster of Topic 2's `envelope_id` validator landmine. `main` is a pre-hardening era of these scanners and security helpers; the only `main` bits worth taking are timeout-wiring and a couple of log lines. Everything else stays `v0.1`.

**Depends on.** Largely independent of the rename. Coordinate philosophy with Topic 2/Topic 14 so the path-traversal hardening is consistent across envelope, sdk_backend, and these scanners.

**Union landmines.**

- `security_hooks.py` — `v0.1` is the richer side (1327 lines vs 871). Porting `main`'s thinner version **deletes** `_strip_windows_unc_or_extlen`, `_resolve_dot_segments`, `_canonicalize_write_edit_path`, `_canonicalize_write_edit_path_with_underflow` (underflow detection), `_is_case_insensitive_fs`, and `_match_write_edit_sensitive_path`. Reconcile per-helper; do not wholesale-port either direction.
- `security_patterns.py` — porting `main` (50 rule_ids) deletes two shipped shell-escape DENY rules `v0.1` has (52): `C6.3-ifs-bypass` (the `$IFS`/`${IFS}` space-substitution obfuscation regex) and `C6.6-unicode-lookalike`. Union both rules back in.
- `dispatch/__init__.py` — porting `main` drops `ToolPolicy`, `DefaultToolPolicy`, and `SecurityHooksConfig` from the public `__all__` + imports (the Trust-Triangle opinion-package config surface). Keep the exports.
- `tool_policy.py` — `v0.1` (120 lines) carries `_build_generic_to_gamified()` role-name mapping feeding `DefaultToolPolicy.tools_for`; `main` (59 lines) lacks it. Keep the gamified-role → generic translation; verify against `v0.1` role fixtures before dropping anything.
- `onboard/scanners/git_state.py` — keep `v0.1`'s `urlsplit`-based `sanitize_remote_url` **verbatim** (it strips `?token=` query-string creds, `x-access-token:GHSA...@` GitHub-App tokens, port-with-userinfo, SCP `git@host:path`, with a no-host fallback). Take **only** `main`'s `_GIT_TIMEOUT = resolve_timeout('git')` wiring and the `_log.debug` narration. A wholesale port of `main`'s 2-regex stripper is a credential-leak regression.
- `onboard/scanners/vault_seed.py` — keep `v0.1`'s version as-is: the `os.fwalk(follow_symlinks=False)` symlink-safe walk (with the `os.walk` Windows fallback), the `_SCAN_ENTRY_CAP = 50_000` (dirs+files, WARN+partial on cap), and the `safe_read_text(...)` pyproject read with `_PYPROJECT_READ_MAX_BYTES = 1 MiB` (env `BONFIRE_VAULT_SEED_PYPROJECT_MAX_BYTES`). `main`'s naive `rglob('*')` + `pyproject.read_text()` adds nothing worth taking — do not port it.
- `onboard/flow.py` — keep `v0.1`'s rich onboarding-timeout machinery (`ConversationTimeoutError(TimeoutError)`, `DEFAULT_CONVERSATION_TIMEOUT = 300.0`, the browser-disconnected runtime error distinct from wall-clock timeout, and the Act-II wall-clock cap). `main`'s 22-line flow is the older, thinner shape; do not regress it.

**Gate plan.**

```
ruff check src/bonfire/dispatch/security_hooks.py src/bonfire/dispatch/security_patterns.py src/bonfire/dispatch/__init__.py src/bonfire/dispatch/tool_policy.py src/bonfire/onboard/scanners/git_state.py src/bonfire/onboard/scanners/vault_seed.py src/bonfire/onboard/flow.py
ruff format --check (same file list)
pytest tests/unit -q -k "security_hooks or security_patterns or tool_policy or git_state or vault_seed_hardening or onboard_flow_timeout"
python -c "from bonfire.dispatch import ToolPolicy, DefaultToolPolicy, SecurityHooksConfig"
```

---

## Topic 17 — handler-seam dispatch parity

**Slug:** `topic-17-handler-seam-parity`

**Files:**

- `src/bonfire/dispatch/handler_runner.py`
- `tests/unit/test_wave_11_handler_dispatch_helper.py`
- (and routing `handlers/sage_correction_bounce.py` through it)

**What it adds.** Preserve `dispatch/handler_runner.py` and `run_handler_dispatch` (the helper that wraps a handler-owned `backend.execute` with `DispatchStarted`/`DispatchCompleted`/`DispatchFailed` emits plus cost stamping, closing the bus-vs-PipelineResult parity gap at the handler seam). Route the handler path through it instead of a raw `backend.execute`.

**Depends on.** Topic 1 only if the handler path adopts `ErrorDetail`. Coordinate with whoever owns the handlers area.

**Union landmines.** `main` has **no** `handler_runner.py`; `main`'s `sage_correction_bounce.py` calls a raw `_call_backend_execute` directly — exactly the parity gap `v0.1` fixed. Porting `main`'s handlers wholesale regresses the fix: handler-owned dispatches stop emitting `Dispatch*` events, so the cost tracker / cost-ledger consumer / knowledge-ingest consumer / budget watchdog silently miss the spend and the envelope returns `cost_usd=0.0`. Keep `handler_runner.py` (or re-route through an equivalent emit + cost-stamp shim).

**Gate plan.**

```
ruff check src/bonfire/dispatch/handler_runner.py
ruff format --check src/bonfire/dispatch/handler_runner.py
pytest tests/unit/test_wave_11_handler_dispatch_helper.py -q
```

---

## Topic 18 — WorkflowSpec rename (SEPARATE; only if Anta wants it)

**Slug:** `topic-18-workflowspec-rename`

**Files:**

- `src/bonfire/models/plan.py`
- `src/bonfire/models/__init__.py`
- `src/bonfire/workflow/registry.py`, `research.py`, `standard.py`, `__init__.py`
- all test references (the rename touches ~260 references across `test_plan.py`, `test_workflow.py`, `test_engine_pipeline.py`, `test_engine_pipeline_tool_policy.py`, `test_engine_checkpoint.py`, `test_budget_enforcement.py`, `test_merge_preflight_pipeline.py`, `test_bon_1072_cost_accounting_close.py`, `test_wave_11_halt_branch_completeness.py`, `test_wave_11_pipeline_outer_exception_failed_emit.py`)

**What it adds.** `main` renames `WorkflowPlan` → `WorkflowSpec` (class only; file stays `plan.py`). The rename is byte-identical content after normalizing the name — `plan.py`, `models/__init__.py`, `workflow/registry.py`, `workflow/research.py` are pure-rename; `workflow/standard.py` (+4 docstring lines `WorkflowPlans`→`WorkflowSpecs`) and `workflow/__init__.py` (+8 docstring lines) are near-pure. The `name` field keeps its `AliasChoices('name','task')` and frozen + `populate_by_name` config. `main` ships **no back-compat alias** (a hard rename).

**Depends on.** Nothing — foundational *within its own subtree*. If chosen, must land **before** Topic 19, because every engine/workflow/dispatch file that imports the class breaks otherwise. **This is an Anta decision** — see Open Questions. Default is **SKIP** (keep `v0.1`'s `WorkflowPlan`); it carries no errors-taxonomy value and has a 9–10-file blast radius. If a topic does port `plan.py` from `main`, it **must** also rename every importer or the build breaks.

**Union landmines.** None destructive (it is a rename), but if a different topic ports `plan.py` from `main` without renaming importers, the build breaks. Keep `v0.1`'s `WorkflowPlan` unless this rename is deliberately chosen as its own topic.

**Gate plan.**

```
ruff check src/bonfire/models/plan.py src/bonfire/workflow/
ruff format --check src/bonfire/models/plan.py src/bonfire/workflow/
git grep -n "WorkflowPlan" src tests   # expect empty if the rename is complete
pytest tests/unit -q -k "plan or workflow"
```

---

## Topic 19 — engine StageExecutor + error_detail + Wave-11 union (high risk)

**Slug:** `topic-19-engine-executor-wave11-union`

**Files:**

- `src/bonfire/engine/executor.py` (new)
- `src/bonfire/engine/pipeline.py`
- `src/bonfire/engine/checkpoint.py`
- `src/bonfire/engine/__init__.py`
- `tests/unit/test_wave_11_pipeline_outer_exception_failed_emit.py` (keep)
- `tests/unit/test_wave_11_halt_branch_completeness.py` (keep)
- `tests/unit/test_pipeline_result_error_detail.py`

**What it adds.** Port the new `StageExecutor` class into `engine/executor.py` (strategy-based single + parallel stage dispatch, never-raises, imports `execute_with_retry` at module scope for test-patching), have `pipeline.py` re-export and delegate to it, and add `error_detail: ErrorDetail | None` to `PipelineResult`, populated via `ErrorDetail.from_exception(exc)` inside the outer-except — **while preserving** `v0.1`'s Wave-11 outer-exception emit.

**Depends on.** Topic 1 + Topic 2 (`ErrorDetail.from_exception`), and Topic 18 if the rename is chosen (the engine imports the workflow class). The core union landmine lives here — do it as one careful topic, not a file swap.

**Union landmines.** The outer-exception branch. `main`'s `run()` except-branch returns `PipelineResult(error=str(exc), error_detail=ErrorDetail.from_exception(exc))` but does **not** emit `PipelineFailed` and does not pre-seed `stages_completed`/`total_cost`. `v0.1`'s branch emits `PipelineFailed(failed_handler='__outer__', total_cost=<reconstructed from stages_seen>, stages_completed=len(stages_seen))` **before** returning — the Wave-11 bus-parity fix (the `'__outer__'` sentinel exists only on `v0.1`; `main` has four `PipelineFailed` emits to `v0.1`'s many, and the outer one is gone). A naive port of `main`'s `pipeline.py` deletes the outer-halt bus-emit, so the cost-ledger / display / XP consumers silently miss outer-exception halts. **Correct replay = union:** keep `v0.1`'s outer `PipelineFailed` emit + `stages_seen` pre-seed **and** add `main`'s `error_detail`. `main` also drops the two guarding tests `test_wave_11_pipeline_outer_exception_failed_emit.py` and `test_wave_11_halt_branch_completeness.py` — keep them.

**Gate plan.**

```
ruff check src/bonfire/engine/
ruff format --check src/bonfire/engine/
pytest tests/unit/test_wave_11_pipeline_outer_exception_failed_emit.py tests/unit/test_wave_11_halt_branch_completeness.py tests/unit/test_pipeline_result_error_detail.py -q
pytest tests/unit -q -k "engine or pipeline or executor or checkpoint"
```

---

## Topic 20 — agent/CLI backend-install + app.py two-way merge (headline CLI landmine)

**Slug:** `topic-20-cli-app-two-way-merge`

**Files:**

- `src/bonfire/cli/app.py`
- `src/bonfire/cli/commands/install_agents.py`, `build_agents.py`
- `src/bonfire/cli/commands/install_skill.py` (preserve)
- `src/bonfire/cadre/__init__.py`
- `src/bonfire/agent/role_metadata.py`
- `src/bonfire/dispatch/_cost.py` (if not already landed in Topic 14)
- `.claude-plugin/plugin.json`
- `agents/*.md` (knight, warrior, sage, wizard, scout-conservative, scout-innovative, bonfire-powered)
- `src/bonfire/prompts/*.md`
- `src/bonfire/skill/SKILL.md` (preserve)
- `tests/unit/test_bon_1100_install_skill.py` (preserve)

**What it adds.** `main`'s genuinely new agent-as-Claude-Code-subagents install rails — `install-agents` / `uninstall-agents` / `list-agents` / `build-agents`, the `agents/*.md` plugin definitions, `.claude-plugin/plugin.json`, `cadre/__init__.py` (`CADRE_CONTRACT_VERSION`), and `prompts/*.md` — added **alongside** `v0.1`'s `install-skill` surface.

**Depends on.** Topic 3 (the `prompts/*.md` packaging) and Topic 4 (`install_skill` uses `_safe_write`).

**Union landmines (headline).**

- `cli/app.py` — porting `main`'s `app.py` **deletes** the `install-skill` command registration **and** the `LazyLoadingGroup` lazy-import architecture (cold-start perf), replacing them with eager imports and the install-agents/build-agents commands. The reconciled `app.py` must register **both** command sets: keep `v0.1`'s `install-skill` + `LazyLoadingGroup` + locally-built cost/persona shims, and add `main`'s `install-agents`/`uninstall-agents`/`list-agents`/`build-agents` + the `--persona` global flag. This is a two-way merge, not a port.
- `install_skill.py` + `skill/SKILL.md` — the headline opinion-package surface (`pip install bonfire-ai && bonfire install-skill` drops the Claude Code skill so `/bonfire scan` works in-chat — the shipped 1.0.1 README's primary onboarding path). `main` has neither. Do not let a CLI port silently delete them. The command does copy-not-symlink + refuse-overwrite-divergent, all writes via `_safe_write` (security-load-bearing).

**Gate plan.**

```
ruff check src/bonfire/cli/app.py src/bonfire/cli/commands/install_agents.py src/bonfire/cli/commands/build_agents.py src/bonfire/cli/commands/install_skill.py
ruff format --check (same list)
bonfire --help | grep -E "install-skill|install-agents|build-agents|list-agents"
pytest tests/unit/test_bon_1100_install_skill.py -q
pytest tests/unit -q -k "install_agents or build_agents or cli_app"
```

---

## Topic 21 — ISM integrations + CI/dev tooling preserve

**Slug:** `topic-21-ism-and-ci-tooling`

**Files (preserve + keep CI steps):**

- `src/bonfire/integrations/__init__.py`, `document.py`, `loader.py`
- `src/bonfire/integrations/builtins/github.ism.md`
- `docs/specs/ism-v1.md`
- `tests/unit/test_integrations_document.py`, `test_integrations_loader.py`, `test_integrations_github_ism.py`
- `.pre-commit-config.yaml`
- `scripts/check_protocol_doc_citations.py` + `tests/scripts/test_check_protocol_doc_citations.py`
- `scripts/petri_conversational_driver.py` + `tests/scripts/test_petri_conversational_driver.py`
- `.github/workflows/ci.yml`, `release.yml`

**What it adds.** The ISM (Instruction Set Markup) v1 package is a published, tested public extension surface (`ISMDocument`, `ISMLoader`, the four detection-rule models, `ISMCategory`, `ISMSchemaError`) that `main` lacks entirely — keep it. Keep the dev/CI tooling that `main` thins: the pinned `ruff v0.15.13` pre-commit config, the protocol-doc citation drift check (and its CI step), and the petri driver.

**Depends on.** Topic 3 (packaging includes the ISM manifest glob).

**Union landmines.**

- `release.yml` — porting `main`'s regresses the `pypa/gh-action-pypi-publish` pin from `v1.14.0` (supports Metadata-Version 2.4, needed for the SPDX `license = Apache-2.0` wheels) back to `v1.12.2` (which rejects those wheels with `InvalidDistribution`). Keep `v0.1`'s `v1.14.0` pin.
- `ci.yml` — porting `main`'s deletes the "Protocol-doc citation drift check" step and drops the `v0.1` branch from triggers. Keep the citation-check step.
- `.pre-commit-config.yaml` — `main` loosens ruff to `>= 0.8`; keep `v0.1`'s `== 0.15.13` (matches `pyproject`'s exact pin and the CI-lint-pin discipline).

**Gate plan.**

```
ruff check src/bonfire/integrations/
ruff format --check src/bonfire/integrations/
pytest tests/unit/test_integrations_document.py tests/unit/test_integrations_loader.py tests/unit/test_integrations_github_ism.py -q
pytest tests/scripts/test_check_protocol_doc_citations.py -q
grep -n "v1.14.0\|gh-action-pypi-publish" .github/workflows/release.yml
grep -n "check_protocol_doc_citations" .github/workflows/ci.yml
```

---

## Topic 22 — doc reconcile (LAST in area)

**Slug:** `topic-22-doc-reconcile`

**Files:**

- `README.md`
- `CHANGELOG.md`
- `tests/test_no_internal_tracker_refs_in_source.py` (preserve)
- `tests/unit/test_no_persona_names_in_public_docs.py` (preserve)
- `tests/unit/test_version_literal_doc_sweep.py` (reconcile to 1.0.1)

**What it adds.** Hand-merge the README: keep `v0.1`'s hero, the install-skill quickstart, the "Your First Scan" walkthrough, the open-core "tier = free" framing, and the entire "Trusting Project Settings (security)" section documenting `trust_project_settings`; fold in `main`'s "Cadre as Claude Code Subagents" / agents-install section; **drop** `main`'s "Alpha — v0.1.0a2" banner (version is 1.0.1). Fold `main`'s agents-as-subagents Added block into a new versioned CHANGELOG entry **above** the real shipped `[1.0.1] — 2026-05-17` entry. Preserve the stratum-leak guard test and scrub any internal-tracker vocab `main` drags in.

**Depends on.** Topic 20 (the agents surface must be final before documenting it).

**Union landmines.**

- `README.md` — porting `main`'s deletes the install-skill quickstart, the "Your First Scan" conversation, the open-core framing, and the security section. Hand-merge, do not port.
- `CHANGELOG.md` — porting `main`'s deletes the real `[1.0.1] — 2026-05-17` entry (`main`'s top is `[Unreleased]`). Keep the `[1.0.1]` history.
- The stratum-leak guard test fails CI if internal-tracker IDs or internal persona/process vocab appear in `src/bonfire/` or `tests/integration/`. `main`'s tree carries audit artifacts that would trip it — keep the guard **and** scrub `main`'s incoming source/docs to pass it, or the public ship leaks internal-tracker vocabulary.

**Gate plan.**

```
pytest tests/test_no_internal_tracker_refs_in_source.py tests/unit/test_no_persona_names_in_public_docs.py tests/unit/test_version_literal_doc_sweep.py -q
grep -nE "0\.1\.0a2|Alpha" README.md   # expect no alpha banner survives
grep -n "1.0.1" CHANGELOG.md            # expect the shipped entry survives
```

---

## NON-topic — events.py: do NOT replay from `main`

**Explicit no-op.** `v0.1`'s `models/events.py` is strictly richer and safer; `main`'s adds nothing the event-type set does not already have. The two-dot tip diff is `+1 / -96` — `main`'s only "add" is *removing* `field_validator` from the import line. Any topic that touches `events.py` must use `v0.1`'s version as the base.

What `v0.1` has that `main` lacks:

- the `_SESSION_ID_RE` path-traversal validator and `_validate_session_id()` (with the empty-string sentinel for outside-session events) and the `@field_validator('session_id')` on `BonfireEvent` — the same path-traversal class as the envelope, applied to `session_id`, which flows to `session/persistence.py` (`{session_id}.jsonl`) and `engine/checkpoint.py` (`{session_id}.json`).
- the richer failure events: `PipelineFailed.failed_handler` (str|None), `.duration_seconds` (float=0.0), `.stages_completed` (int=0); and the `DispatchFailed.cost_usd` doc-comment. These carry the cost-ledger + XP-penalty symmetry on the failure path (bounce-target identity, real run-length, stage-progress at halt).

---

## Consolidated UNION landmine register

Every row is a `v0.1` surface that a naive `main` port would delete. The correct move is **graft the `main` add onto the `v0.1` file**, never a full-file copy. Verify with the two-dot diff `git diff origin/v0.1..origin/main -- <file>`, never the three-dot form.

| # | File | What a naive `main` port deletes | Correct move | Pinning test / signal | Topic |
|---|---|---|---|---|---|
| L1 | `models/envelope.py` | `_ENVELOPE_ID_RE` + `_envelope_id_must_be_path_safe` validator + `import re` (the worked example) | start from `v0.1`; add only `from_exception` + `import traceback` | `test_session_id_path_traversal_reject.py` | 2 |
| L2 | `models/events.py` | `_SESSION_ID_RE` + `_validate_session_id` + `session_id` validator; `PipelineFailed.failed_handler`/`.duration_seconds`/`.stages_completed` | do not replay from `main`; keep `v0.1` verbatim | event-type symmetry; `+1/-96` numstat | NON-topic |
| L3 | `models/config.py` | `trust_project_settings: bool = False` (CLAUDE.md / `.claude` ingest opt-in gate) | keep `v0.1`'s field + doc comment | `test_trust_project_settings_key.py` | 14 |
| L4 | `dispatch/sdk_backend.py` | `_resolve_setting_sources` / `_bonfire_toml_opts_in` deny-by-default gate; `_summarise_traceback` / `_format_error_traceback` redaction | ADD typed-error path; KEEP both guards | `test_sdk_backend_setting_sources_gate.py`, `test_sdk_backend_traceback_redaction.py` | 14 |
| L5 | `dispatch/security_hooks.py` | Windows-UNC / extended-length / dot-segment-underflow / case-insensitive-FS write-path canonicalization (1327L vs 871L) | per-helper union; do not wholesale-port | `test_security_hooks_*` | 16 |
| L6 | `dispatch/security_patterns.py` | `C6.3-ifs-bypass` + `C6.6-unicode-lookalike` DENY rules (52 vs 50) | union both rules back in | C-pattern tests | 16 |
| L7 | `dispatch/__init__.py` | `ToolPolicy` / `DefaultToolPolicy` / `SecurityHooksConfig` public exports | keep them in `__all__` + imports | `from bonfire.dispatch import ToolPolicy, ...` | 16 |
| L8 | `dispatch/tool_policy.py` | `_build_generic_to_gamified()` role-name mapping (120L vs 59L) | keep the gamified→generic translation | role-resolution fixtures | 16 |
| L9 | `onboard/scanners/git_state.py` | `urlsplit`-based `sanitize_remote_url` (query-string + GHSA + port-userinfo + SCP stripping) | keep `v0.1` body; take only `main`'s timeout wiring + DEBUG log | `test_git_state_sanitize.py` | 16 |
| L10 | `onboard/scanners/vault_seed.py` | `os.fwalk` symlink-safe walk + `_SCAN_ENTRY_CAP=50_000` + 1 MiB pyproject cap | keep `v0.1` as-is; do not port `main` | `test_vault_seed_hardening.py` (10 tests) | 16 |
| L11 | `onboard/flow.py` | `ConversationTimeoutError` / browser-disconnected / `DEFAULT_CONVERSATION_TIMEOUT` / Act-II cap | keep `v0.1`'s rich flow | `test_onboard_flow_timeout.py` (7 tests) | 16 |
| L12 | `knowledge/backend.py` | filter-only LanceDB `exists()` optimization (revert to zero-vector ANN scan) | keep `v0.1` body; graft only the warning line | `test_vaultbackend_stable_surface_docs.py` | 12 |
| L13 | `knowledge/memory.py` | no-re-lower / O(1)-exists optimization (fork: different private attr names) | pick one scheme; keep both perf tests green | `test_memory_vault.py` + `test_knowledge_memory_performance.py` | 12 |
| L14 | `dispatch/handler_runner.py` | the whole `run_handler_dispatch` bus-parity helper (handler-seam `Dispatch*` emits + cost stamp) | keep it; route handlers through it | `test_wave_11_handler_dispatch_helper.py` | 17 |
| L15 | `engine/pipeline.py` | outer-exception `PipelineFailed(failed_handler='__outer__', …)` emit + `stages_seen` pre-seed | union: keep `v0.1` outer emit + add `main`'s `error_detail` | `test_wave_11_pipeline_outer_exception_failed_emit.py`, `test_wave_11_halt_branch_completeness.py` | 19 |
| L16 | `cli/app.py` | `install-skill` registration + `LazyLoadingGroup` lazy-import architecture | two-way merge: register BOTH command sets + `--persona` | `bonfire --help` shows both | 20 |
| L17 | `cli/commands/install_skill.py` + `skill/SKILL.md` | the entire shipped opinion-package install surface | keep both install paths | `test_bon_1100_install_skill.py` | 20 |
| L18 | `_safe_read.py` / `_safe_write.py` | the two security IO primitives (12 consumer files route through them) | guard: no port may delete a call site | `test_safe_read.py` / `test_safe_write.py` | 4 |
| L19 | `integrations/*` + `docs/specs/ism-v1.md` | the entire published ISM v1 extension package | keep it | `test_integrations_*` | 21 |
| L20 | `pyproject.toml` | wheel-include `skill/*.md` + `*.ism.md` globs; version `1.0.1`; ruff `==0.15.13` | union the include; keep version + pin | wheel-content check | 3 |
| L21 | `src/bonfire/__init__.py` | `1.0.1` editable fallback `__version__` | keep `1.0.1`; add Verdict re-export | `bonfire.__version__ == '1.0.1'` | 3 |
| L22 | `README.md` | install-skill quickstart, "Your First Scan", open-core framing, "Trusting Project Settings" section | hand-merge; add agents section; drop alpha banner | manual review | 22 |
| L23 | `CHANGELOG.md` | the real `[1.0.1] — 2026-05-17` entry | keep it; fold agents entry above | manual review | 22 |
| L24 | `.github/workflows/release.yml` | `pypa/gh-action-pypi-publish` `v1.14.0` pin (Metadata-Version 2.4 for SPDX license wheels) | keep `v1.14.0` | release-yml grep | 21 |
| L25 | `.github/workflows/ci.yml` | "Protocol-doc citation drift check" step + `v0.1` branch triggers | keep the citation step | ci-yml grep | 21 |
| L26 | `.pre-commit-config.yaml` | pinned `ruff v0.15.13` | keep the pin | pre-commit grep | 21 |
| L27 | stratum-leak guard tests | `test_no_internal_tracker_refs_in_source.py` (+ persona-names guard) | keep guards; scrub `main`'s incoming source/docs | the guard tests | 22 |
| L28 | hardening test set (~40 RED tests) | session-id reject, symlink reject, scanner size-caps, TOML escape, NUL-byte, adversarial canonicalizer | keep all of them | the listed tests | 16, 2 |

---

## Open questions for Anta

1. **Version string.** The reconciled trunk should ship `version = "1.0.1"` (the PyPI truth), not `main`'s stale `0.1.0a2`. The next release after the agents surface lands needs a new number (e.g. `1.1.0` for the agents-as-subagents feature). Confirm the next version, and whether `main`'s alpha banner is fully retired in the README/CHANGELOG.

2. **README + CHANGELOG shape.** Topic 22 proposes keeping `v0.1`'s hero + install-skill quickstart + "Trusting Project Settings" security section, folding in `main`'s agents-install section, and dropping the alpha banner. Confirm that framing (open-core "tier = free" + install-skill as the primary onboarding path, with agents-as-subagents as the new headline feature).

3. **WorkflowSpec rename (Topic 18).** Default is **SKIP** — keep `v0.1`'s `WorkflowPlan`. The rename carries no failure-taxonomy value, ships no back-compat alias, and has a ~260-reference blast radius. Adopt the rename as its own topic only if you want the `Spec`-implies-frozen-contract vocabulary on the trunk. Decision needed before Topic 19 (engine) sequences, since the engine imports the class.

4. **Both install paths or deprecate one?** Topic 20 keeps **both** `install-skill` (the `v0.1` opinion-package surface) and `install-agents`/`build-agents` (`main`'s new rails) coexisting. Confirm they coexist, or name a deprecation path for one — but do not let a CLI port silently delete `install-skill` either way.

5. **Taxonomy growth is Wizard-gated.** The Elegance Law keeps the failure vocabulary small and shared. Topics 1, 13, 14, 15 thread the existing taxonomy through call sites; none of them add a new error class. If any reconcile step appears to need a new `BonfireError` subclass, that is a Wizard-gated decision, not a free-for-all — flag it rather than minting one.

6. **Concurrency / merge order.** `protocols.py` (Topics 5, 7), `sdk_backend.py` + `_cost.py` (Topics 14, 20), and `dispatch/__init__.py` (Topic 16) are touched by more than one topic. The sequence above orders them so the shared files are appended-to, not rewritten — confirm the lane assignments so two topics do not rewrite the same file in parallel.
