# BON-351 — Dispatch engine integration of per-role model tier resolver (Sage memo, D1-D10)

**Stamp:** 2026-04-27T20:30:00Z
**Ticket:** BON-351 — "W7.2 — A7: dispatch engine integration of routing + cost attribution"
**Size:** M (advertised) · stays **M** post-audit. · **Priority:** High.
**Role:** Sage (single, post-scout). The keystone wiring of BON-350's `resolve_model_for_role` into the dispatch flow plus per-model cost attribution.
**Canonical branch:** `antawari/bon-351-sage` off `v0.1@a07e118` (post-BON-350 merge — `Merge pull request #29 from BonfireAI/antawari/bon-350-warrior-a`).
**Scout report:** `docs/audit/scout-reports/bon-351-scout-20260427T183204Z.md` (250 lines, sections A/B/C/D/E).
**Prior Sage refs honored:** BON-337 (D4 — `DispatchOptions.role`), BON-338 (D9/D11 — nested-Pydantic config precedent), BON-340 (role vocabulary tension), BON-345 (D4 — `persona` precedent), BON-346 (W5.7 — `cost/` package contract), BON-350 (D1-D10 — resolver primitive), BON-353 (no ticket tags in source docstrings).
**Authority:** This memo is the single source of truth for naming, surface, signatures, defaults, test names, and Wizard preflight numbers for BON-351 dispatch. Cite by D-id when implementing.

---

## Summary (5 bullets)

1. **What BON-351 ships:** wires `resolve_model_for_role(stage.role, settings)` into the THREE existing dispatch call sites that today read `self._config.model` raw — `engine/executor.py:266`, `engine/pipeline.py:498`, AND the missing role on `handlers/wizard.py:315-322`. Adds a per-model cost attribution slice to `DispatchCompleted` events and to `DispatchRecord` ledger rows. Adds `CostAnalyzer.model_costs() -> list[ModelCost]` aggregator. **No widening of `DispatchOptions`. No widening of `Envelope`. No new TOML section.**
2. **Schema migrations that land:** `DispatchRecord` gains `model: str = ""` (default keeps existing JSONL rows valid). `DispatchCompleted` event gains `model: str = ""` (default keeps existing emitters & registry tests valid). `ModelCost` is a NEW Pydantic model in `cost/models.py` (4 fields). **No `tier` field is added to `DispatchRecord` in v0.1** — deferred to D-FT C; per-model is the v0.1 deliverable, per-tier rolls up by joining model→tier through the resolver lookup table.
3. **Call sites changed:** (a) `engine/executor.py:266` — model precedence becomes `envelope.model OR resolve_model_for_role(stage.role, settings) OR self._config.model`. (b) `engine/pipeline.py:498` — `spec.model_override OR resolve_model_for_role(spec.role, settings) OR self._config.model`. (c) `handlers/wizard.py:303-322` — pass `role=ROLE.value` into `DispatchOptions` AND swap `stage.model_override or self._config.model` for the resolver-aware precedence (review = REASONING tier by default). (d) `dispatch/runner.py:184-193` — emit `model=options.model` on `DispatchCompleted`. (e) `cost/consumer.py:30-37` — read the new event field, persist to ledger.
4. **Tests added/extended:** ~32 net-new tests across 5 files. `test_cost_models.py` (+5 for `model` field on `DispatchRecord` + `ModelCost`), `test_cost_analyzer.py` (+8 for `model_costs()`), `test_cost_consumer.py` (+4 for event-field passthrough), `test_events.py` (+3 for `DispatchCompleted.model`), `test_engine_executor.py` + `test_engine_pipeline.py` + `test_wizard_handler.py` (+12 for resolver wiring + role-passing + precedence). **No new test files.**
5. **What's deferred:** `tier: str` field on `DispatchRecord` (D-FT C — needs `tier` in DispatchOptions or a separate event field, neither in scope). `CostAnalyzer.tier_costs()` (D-FT D — trivially derivable post-fact). `bonfire cost --model` CLI flag (D-FT E). Per-attempt model breakdown across retries (D-FT F — runner aggregates `cumulative_cost` agnostically). Backend rejection of unknown model strings (D-FT G).

---

## Context: what the v0.1 codebase already has (post-BON-350)

- `src/bonfire/agent/tiers.py` (BON-350, just merged at a07e118) ships `ModelTier`, `DEFAULT_ROLE_TIER`, `GAMIFIED_TO_GENERIC`, and `resolve_model_for_role(role: str, settings: BonfireSettings) -> str`. Pure synchronous, never raises on string input, falls back to `BALANCED` tier for unknown roles. **This is the public primitive BON-351 consumes.**
- `src/bonfire/models/config.py:160` ships `models: ModelsConfig = ModelsConfig()` on `BonfireSettings` (BON-350 D5). Defaults: `reasoning="claude-opus-4-7"`, `fast="claude-haiku-4-5"`, `balanced="claude-sonnet-4-6"`.
- `src/bonfire/protocols.py:60-75` ships `DispatchOptions` with **10 fields** (BON-337 added `role: str = Field(default="", strict=True)` line 72; BON-338 added `security_hooks: SecurityHooksConfig = Field(default_factory=...)` line 75). The sentinel test is `test_protocols.py::test_has_exactly_eight_fields` (line 620) — **misnamed but locked at 10**, NOT 8 (its docstring says "the v0.1 field inventory is ten").
- `src/bonfire/dispatch/sdk_backend.py:110` consumes `options.model` verbatim into `ClaudeAgentOptions(model=...)`. **No resolver call here — that's intentional.** Resolution happens UPSTREAM at envelope-construction time, not at SDK-call time. (See D2 rationale.)
- `src/bonfire/dispatch/runner.py:103-111` emits `DispatchStarted(model=options.model, ...)`. `runner.py:184-193` emits `DispatchCompleted(...)` WITHOUT a `model` field today.
- `src/bonfire/cost/models.py:14-22` declares `DispatchRecord` with 6 fields: `type`, `timestamp`, `session_id`, `agent_name`, `cost_usd`, `duration_seconds`. **No model. No tier. No role.**
- `src/bonfire/cost/consumer.py:30-37` builds `DispatchRecord` from `DispatchCompleted`. Today it can't pass a model field — the event doesn't carry one.
- `src/bonfire/cost/analyzer.py` ships 5 public methods: `cumulative_cost`, `session_cost`, `agent_costs`, `all_sessions`, `all_records`. **None aggregate by model.**
- `src/bonfire/handlers/wizard.py:303-322` builds `Envelope(model=stage.model_override or self._config.model, metadata={"role": ROLE.value})` (line 303-308) and `DispatchOptions(model=review_envelope.model, max_turns=5, ..., tools=["Read","Grep","Glob"], permission_mode="dontAsk")` (line 315-322) — **note: `role=` is NOT passed into DispatchOptions**, so the wizard handler is the one site where role is invisible at the runner layer (Scout §C, line 164). The metadata-level role (line 307) does not flow through to `DispatchOptions`.
- `src/bonfire/engine/executor.py:259-281` ships `_dispatch_backend` which DOES pass `role=stage.role` (line 271). Model: `envelope.model or self._config.model` (line 266). No resolver.
- `src/bonfire/engine/pipeline.py:497-504` ships pipeline-mode dispatch; same shape: `role=spec.role` (line 503), `model=spec.model_override or self._config.model` (line 498).

---

## D1 — Role vocabulary keying (KEYSTONE — Knights cannot proceed without this)

### WHAT
**The resolver accepts BOTH gamified strings (`scout`/`knight`/`warrior`/`prover`/`assayer`/`bard`/`wizard`/`herald`/`sage`/`architect`) AND canonical professional strings (`AgentRole` enum: `researcher`/`tester`/`implementer`/`verifier`/`publisher`/`reviewer`/`closer`/`synthesizer`/`analyst`).** BON-351's call sites pass through the role string they HAVE — no translation, no normalization at the call site.

Concretely:
- `engine/executor.py:266` and `engine/pipeline.py:498` pass `stage.role` / `spec.role` directly. These flow from `workflows/standard.py` and `workflows/research.py`, which emit gamified strings.
- `handlers/wizard.py` passes `ROLE.value` where `ROLE = AgentRole.REVIEWER` (line 55, 307). This is a CANONICAL string ("reviewer"), not gamified.
- The resolver internally normalizes via the path locked in BON-350: `AgentRole(normalized)` → `GAMIFIED_TO_GENERIC[normalized]` → `BALANCED` fallback. Both vocabularies hit the same tier table.

**No new translation layer is introduced. Both vocabularies remain valid. The two-vocabulary state is preserved (BON-340 verdict honored).**

### WHY
Scout §E (lines 213-214) flags this as the keystone tension. BON-350 D7 (memo lines 402-440) ALREADY locked the dual-vocabulary contract: the resolver's fallback chain accepts both via `GAMIFIED_TO_GENERIC` aliasing. BON-350 §D-CL.4 (lines 638-640) explicitly says *"BON-351 passes `stage.role` (gamified workflow value) into the resolver, NOT `options.role`"* — i.e., the call-side discipline is to use whichever role string the call site already has, and let the resolver normalize.

The wizard handler is the canonical-string case: `AgentRole.REVIEWER.value == "reasoner"` is wrong — it's `"reviewer"` (per `roles.py:38`). The gamified alias `"wizard"` ALSO maps to `AgentRole.REVIEWER` (per `tiers.py:52`). Both routes resolve to `DEFAULT_ROLE_TIER[REVIEWER] = REASONING` → `settings.models.reasoning` → `"claude-opus-4-7"`. **Same answer either way.** This is the correctness guarantee that lets us pass whatever string the call site has.

### HOW TO TEST
Knight A spine (in `test_engine_executor.py`):
```python
def test_executor_passes_gamified_role_to_resolver(monkeypatch):
    captured = {}
    def fake_resolver(role, settings): captured["role"] = role; return "X"
    monkeypatch.setattr("bonfire.engine.executor.resolve_model_for_role", fake_resolver)
    # ... dispatch a stage with role="warrior" ...
    assert captured["role"] == "warrior"
```

Knight A spine (in `test_wizard_handler.py`):
```python
async def test_wizard_passes_canonical_role_to_resolver(monkeypatch):
    captured = {}
    def fake_resolver(role, settings): captured["role"] = role; return "claude-opus-4-7"
    monkeypatch.setattr("bonfire.handlers.wizard.resolve_model_for_role", fake_resolver)
    # ... handle ...
    assert captured["role"] == "reviewer"  # AgentRole.REVIEWER.value
```

Knight B innovation: assert that BOTH vocabularies resolve to the same model for paired roles (`"warrior"` → fast == `"implementer"` → fast; `"wizard"` → reasoning == `"reviewer"` → reasoning).

### AMBIG
None at the resolver-input layer — BON-350 closed it. The remaining ambiguity is whether the wizard handler's call-site model precedence should be `(stage.model_override OR resolver-result OR config.model)` OR strictly `(stage.model_override OR resolver-result)` (skipping `config.model`). **D2 resolves this.**

---

## D2 — Resolver call site (LOCKED)

### WHAT
The resolver is called at **envelope-construction time**, NOT inside the SDK backend. Three call sites each gain ONE line:

**(a) `engine/executor.py:266` — `_dispatch_backend`:**
```python
options = DispatchOptions(
    model=envelope.model or resolve_model_for_role(stage.role, self._settings) or self._config.model,
    ...
)
```

**(b) `engine/pipeline.py:498` — pipeline-mode dispatch:**
```python
options = DispatchOptions(
    model=spec.model_override or resolve_model_for_role(spec.role, self._settings) or self._config.model,
    ...
)
```

**(c) `handlers/wizard.py:303-308` — review envelope construction:**
```python
review_envelope = Envelope(
    task=prompt,
    agent_name="review-agent",
    model=stage.model_override or resolve_model_for_role(ROLE.value, self._settings) or self._config.model,
    metadata={"role": ROLE.value},
)
```

**Precedence order (LOCKED for all three sites):**
1. **Per-stage explicit override** (`envelope.model` / `spec.model_override`) — wins. Operator escape hatch.
2. **Resolver result** for the role — wins next. The new behavior.
3. **Pipeline default** (`self._config.model`) — final fallback.

**`config.model` is NOT removed.** It remains the safety net when (a) the resolver returns the empty string (which it cannot today — see BON-350 D7 fallback chain) AND (b) no per-stage override exists. The `or` chain treats empty string as falsy — Python's standard truthiness — so the precedence collapses correctly.

### WHY
- **Why envelope-construction time, not SDK-call time?** Three reasons: (1) `DispatchStarted(model=options.model)` already fires at runner.py:109 BEFORE the backend executes — the SDK-time decision would emit a wrong model on the started event. (2) Cost capture rounds-trip through `DispatchCompleted` which closes well after the SDK call; the model name must be observable at envelope construction so it can be threaded through the runner. (3) Other backends (`PydanticAIBackend`) read `options.model` verbatim too (`pydantic_ai_backend.py:57`); the SDK is not the only consumer. Centralizing at the SDK seam would force a duplicate edit per backend.
- **Why three sites, not a single helper?** A `_resolve_options_model(stage, envelope, config, settings)` helper IS appealing but would have to live somewhere — `bonfire.dispatch.options` doesn't exist; `bonfire.engine` is the natural home but the wizard handler isn't an `engine` consumer. The cost is one duplicated line per site (3 sites). The benefit of inline-at-call-site is zero hidden indirection: a grep for `resolve_model_for_role` reveals every routing decision. **Decision: inline at all three sites.**
- **Why preserve `self._config.model`?** Removing it is a behavior change: today, an empty-role stage falls back to `config.model`. With the resolver-only precedence, the resolver's BALANCED fallback (`config.balanced`) would intercept first. `config.balanced` happens to default to `"claude-sonnet-4-6"`, which IS `PipelineConfig.model`'s default — but a user with `[bonfire] model = "claude-opus-4-7"` and an unspecified `[models]` section would silently regress. Keeping the third fallback preserves user-visible behavior for the empty-role case.
- **`PydanticAIBackend` no-op:** the alternate backend reads `options.model` (line 57). Nothing in BON-351 changes for it — it gets the resolved model for free.

### HOW TO TEST
Knight A spine (executor):
```python
def test_executor_resolves_model_via_role(monkeypatch):
    monkeypatch.setattr(
        "bonfire.engine.executor.resolve_model_for_role",
        lambda role, settings: "claude-haiku-4-5" if role == "warrior" else "X",
    )
    backend = FakeBackend()
    # ... build executor with stage.role="warrior", envelope.model="" ...
    await executor._dispatch_backend(stage, envelope)
    assert backend.captured_options.model == "claude-haiku-4-5"

def test_executor_envelope_model_wins_over_resolver(monkeypatch):
    monkeypatch.setattr("bonfire.engine.executor.resolve_model_for_role", lambda r,s: "RESOLVER")
    # ... stage.role="warrior", envelope.model="OVERRIDE" ...
    await executor._dispatch_backend(stage, envelope)
    assert backend.captured_options.model == "OVERRIDE"

def test_executor_config_model_wins_when_resolver_empty(monkeypatch):
    monkeypatch.setattr("bonfire.engine.executor.resolve_model_for_role", lambda r,s: "")
    # ... stage.role="" (empty), config.model="claude-sonnet-4-6" ...
    assert backend.captured_options.model == "claude-sonnet-4-6"
```

Knight A spine (pipeline): identical shape, target `engine/pipeline.py:498`.
Knight A spine (wizard): identical shape, target `handlers/wizard.py:303-308`.

### AMBIG
- **Self._settings access:** `StageExecutor` and `Pipeline` and `WizardHandler` need a `BonfireSettings` reference at construction. **D-CL.1 below resolves this** — settings flow through the dependency-injection seam already used for `PipelineConfig`.

---

## D3 — DispatchOptions widening (LOCKED — NO WIDENING)

### WHAT
**`DispatchOptions` does NOT gain a new field.** The 10-field inventory locked at `test_protocols.py:620-636` stays at 10. BON-351 is a CONSUMER of `options.model` and `options.role`, not an extender of `DispatchOptions`.

No `model_routing: ModelRoutingConfig`. No `tier: str`. No `models_config: ModelsConfig`. The resolver's two inputs (`role`, `settings`) are sourced separately:
- `role` → `stage.role` / `spec.role` / `ROLE.value` at the call site (already present).
- `settings` → injected into the executor / pipeline / handler at construction (D-CL.1).

### WHY
- **BON-338 precedent applies in spirit, not in letter.** BON-338 added `security_hooks` because the SDK seam needed config that the runner had no other way to plumb. Here, the SDK seam doesn't need anything new — `options.model` is already the right knob. The resolver is upstream of `DispatchOptions` construction, not parallel to it.
- **Minimal blast radius.** Adding a field to a frozen Pydantic model with a sentinel-pinned inventory test means: (a) bump the sentinel, (b) update every test that constructs `DispatchOptions`, (c) update every code path that iterates `model_fields`. Avoiding all three is a clean win when the data is already passable through `model`.
- **The resolver returns a string; `options.model` is a string.** Round trip is byte-identical to the existing behavior. The runner emits `DispatchStarted.model=options.model` and that string is correct.
- **`test_protocols.py::test_has_exactly_eight_fields` does NOT bump.** Stays at 10.

### HOW TO TEST
Knight A spine (in `test_protocols.py`):
```python
def test_has_exactly_eight_fields_unchanged_by_bon351(self):
    """BON-351 does not widen DispatchOptions."""
    assert len(DispatchOptions.model_fields) == 10
```
This test ALREADY exists at `test_protocols.py:620` — Knight A asserts it survives unchanged (effectively a non-regression smoke).

### AMBIG
None. The non-widening decision is final.

---

## D4 — DispatchCompleted event widening (LOCKED — ADD `model: str = ""`)

### WHAT
Add ONE field to `DispatchCompleted` in `src/bonfire/models/events.py:132-136`:
```python
class DispatchCompleted(BonfireEvent):
    event_type: Literal["dispatch.completed"] = "dispatch.completed"
    agent_name: str
    cost_usd: float
    duration_seconds: float
    model: str = ""  # NEW — BON-351
```

`runner.py:184-193` emits with the new field:
```python
DispatchCompleted(
    session_id=session_id,
    sequence=0,
    agent_name=agent_name,
    cost_usd=cumulative_cost,
    duration_seconds=duration,
    model=options.model,
)
```

**Default is `""` (empty string).** Test data factories (`test_events.py:609-613` `_minimal_kwargs` registry) do NOT need updating — Pydantic accepts the existing minimal kwargs because the new field has a default.

### WHY
- **Backward compatibility for the registry sentinel.** `test_events.py:608-613` ships an exhaustive minimal-kwargs map (`DispatchCompleted: {"agent_name": "a", "cost_usd": 0.0, "duration_seconds": 0.0}`). Without a default, every entry would need `model=""` added. With a default, ZERO entries change.
- **Symmetry with `DispatchStarted.model`.** Started and Completed should carry the same identifier. The runner has `options.model` in scope at both emission points. No new wiring.
- **Why not bump it on `DispatchFailed` and `DispatchRetry` too?** Those events are NOT consumed by the cost ledger (`consumer.py:24-27` subscribes to Completed + PipelineCompleted only). Failed/Retry don't aggregate cost. Defer to D-FT B if surface needs grow.
- **Default empty-string vs `None`.** Empty string matches the existing `DispatchOptions.model: str = ""` convention (BON-337 D4 — empty-string-as-unset). `None` would force `Optional[str]` and a Literal-style validator. Empty string is the project convention.

### HOW TO TEST
Knight A spine (in `test_events.py`):
```python
def test_dispatch_completed_has_model_field(self):
    e = DispatchCompleted(agent_name="x", cost_usd=0.0, duration_seconds=0.0, **SESSION)
    assert e.model == ""

def test_dispatch_completed_accepts_model(self):
    e = DispatchCompleted(
        agent_name="x", cost_usd=0.0, duration_seconds=0.0,
        model="claude-opus-4-7", **SESSION,
    )
    assert e.model == "claude-opus-4-7"
```

Knight A spine (in `test_dispatch_runner.py`):
```python
async def test_dispatch_completed_carries_options_model():
    options = DispatchOptions(model="claude-haiku-4-5")
    # ... run with capturing event_bus ...
    completed = [e for e in bus.events if isinstance(e, DispatchCompleted)][0]
    assert completed.model == "claude-haiku-4-5"
```

### AMBIG
- **Should `DispatchCompleted.model` reflect the model AT START (started.model) or LAST ATTEMPT (potentially different on retry)?** Today `cumulative_cost` aggregates retries indiscriminately (Scout §A line 82). BON-351 emits the START model — the model the dispatch was REQUESTED with, not the model the LAST retry happened to use. Retries use the same `options.model` (the runner does not mutate options between attempts), so this is unambiguous in practice. Tests assert the model on Completed equals the model on Started for any single dispatch.

---

## D5 — DispatchRecord schema migration (LOCKED — ADD `model: str = ""`, DEFER `tier`)

### WHAT
Add ONE field to `DispatchRecord` in `src/bonfire/cost/models.py:14-22`:
```python
class DispatchRecord(BaseModel):
    type: Literal["dispatch"] = "dispatch"
    timestamp: float
    session_id: str
    agent_name: str
    cost_usd: float
    duration_seconds: float
    model: str = ""  # NEW — BON-351
```

Add a NEW Pydantic model `ModelCost` at the end of the same file (after `AgentCost`):
```python
class ModelCost(BaseModel):
    """Cumulative cost for one model across all sessions."""
    model: str
    total_cost_usd: float
    dispatch_count: int
    total_duration_seconds: float
```

**`tier` field is OUT OF SCOPE for v0.1 BON-351 — deferred to D-FT C.** Rationale: the resolver maps role→tier→model; the model string IS the tier-disambiguated identifier. Per-tier roll-up at analysis time can be derived by mapping `record.model` back through `ModelsConfig` reverse-lookup OR by running the resolver against historical role data. Adding `tier` now would require either (a) widening `DispatchOptions` (forbidden by D3) OR (b) computing tier inside the runner from a settings handle the runner doesn't have. Either is a larger blast radius than the v0.1 ticket allows.

### WHY
- **Backward-compatible JSONL.** Existing rows in `~/.bonfire/cost/cost_ledger.jsonl` lack a `model` field. Pydantic accepts them with the default. Per BON-346's `_read_records()` permissive contract (Scout §B line 136), this is a zero-risk migration.
- **`ModelCost` shape mirrors `AgentCost`.** Same four-field shape (`name-key`, `total_cost_usd`, `dispatch_count`, `aggregated-secondary`). Difference: `AgentCost.avg_cost_usd` vs `ModelCost.total_duration_seconds`. Duration is more informative per-model than average — a high-spend per-dispatch model is interesting; an aggregate burn-time-per-model is operationally interesting in a way average-cost is not (and avg can be derived: `total_cost / dispatch_count`).
- **`type: Literal["dispatch"]` discriminator unchanged.** `_read_records()` (analyzer.py:50) routes by `record_type == "dispatch"`. No new discriminator needed.
- **NOT adding `role` to `DispatchRecord`.** The `agent_name` field today carries the role-shaped string in practice (gamified). Adding `role` separately would force consumers to pick which one to query. Defer to D-FT D if the need emerges.
- **NOT adding `tier`.** Per above. The resolver's role→tier table is the source of truth — derive at query time.

### HOW TO TEST
Knight A spine (in `test_cost_models.py`):
```python
class TestDispatchRecordModel:
    def test_dispatch_record_has_model_default_empty(self):
        r = DispatchRecord(timestamp=0.0, session_id="s", agent_name="a",
                           cost_usd=0.0, duration_seconds=0.0)
        assert r.model == ""

    def test_dispatch_record_accepts_model(self):
        r = DispatchRecord(timestamp=0.0, session_id="s", agent_name="a",
                           cost_usd=0.0, duration_seconds=0.0, model="claude-opus-4-7")
        assert r.model == "claude-opus-4-7"

    def test_legacy_jsonl_row_without_model_loads(self):
        legacy = '{"type":"dispatch","timestamp":0.0,"session_id":"s","agent_name":"a","cost_usd":0.0,"duration_seconds":0.0}'
        r = DispatchRecord.model_validate_json(legacy)
        assert r.model == ""

class TestModelCost:
    def test_model_cost_construction(self):
        m = ModelCost(model="claude-opus-4-7", total_cost_usd=1.0,
                      dispatch_count=3, total_duration_seconds=12.5)
        assert m.model == "claude-opus-4-7"
        assert m.dispatch_count == 3
```

Knight B innovation: round-trip a corpus of mixed legacy + new rows through the analyzer and assert no exceptions.

### AMBIG
- **Sort order on `model_costs()`.** Decision: descending by `total_cost_usd`, mirroring `agent_costs()` (analyzer.py:135). Same comparator; same UX.
- **Empty-string model grouping.** Decision: GROUP `""` rows into a single bucket called `""` in the output. Don't skip them — operators want to see legacy/unattributed spend. (Tests assert this in D8.)

---

## D6 — handlers/wizard.py:315-322 fix (LOCKED — pass `role=ROLE.value`)

### WHAT
Modify `handlers/wizard.py:315-322` to pass `role=ROLE.value`:
```python
options = DispatchOptions(
    model=review_envelope.model,
    max_turns=5,
    max_budget_usd=0.0,
    thinking_depth=thinking_depth,
    tools=["Read", "Grep", "Glob"],
    permission_mode="dontAsk",
    role=ROLE.value,  # NEW — BON-351 — surfaces "reviewer" to the runner
)
```

`ROLE` is bound at module level (line 55: `ROLE: AgentRole = AgentRole.REVIEWER`). `ROLE.value == "reviewer"`. The model line 303-308 ALSO becomes resolver-aware (per D2(c) above) — the two changes are paired in the same edit.

### WHY
- Scout §C line 164 flags this as the ONLY call site where role is invisible to the runner. Without this fix, the wizard handler dispatch emits `DispatchStarted(model=...)` with the right model BUT the SDK-side hooks and downstream consumers see `options.role == ""`, breaking the assumed invariant that a non-trivial dispatch has a role string.
- The metadata-level `{"role": ROLE.value}` at line 307 is on the ENVELOPE, not the OPTIONS. Envelope metadata is for the agent's own context; DispatchOptions.role is for the runner/backend's own decisions. They serve different purposes — both stay.
- BON-337 D4 invariant (`role: str = Field(default="", strict=True)`) is honored — `ROLE.value` is a non-empty `str`. No `None`, no enum-passing.

### HOW TO TEST
Knight A spine (extend `test_wizard_handler.py::TestDispatchOptionsPlumbing`):
```python
@pytest.mark.asyncio
async def test_role_is_reviewer(self) -> None:
    handler, backend, _ = _make_handler()
    await handler.handle(_make_stage(), _make_envelope(), {})
    assert backend.captured_options.role == "reviewer"
```

Knight B innovation: assert the DispatchStarted event carries `model` derived from `ROLE.value` resolution path (i.e., `claude-opus-4-7` by default).

### AMBIG
None. The fix is one line.

---

## D7 — CostLedgerConsumer (LOCKED — read-and-pass model field)

### WHAT
Modify `cost/consumer.py:30-37` to pass the new `model` field through:
```python
async def _on_dispatch_completed(self, event: DispatchCompleted) -> None:
    record = DispatchRecord(
        timestamp=event.timestamp,
        session_id=event.session_id,
        agent_name=event.agent_name,
        cost_usd=event.cost_usd,
        duration_seconds=event.duration_seconds,
        model=event.model,  # NEW — BON-351
    )
    self._append(record)
```

**No-op fallback for old events.** Because `DispatchCompleted.model` defaults to `""` (D4), any event constructed without setting it (e.g. test fixtures that don't pass `model=`) lands with `record.model == ""`. The ledger row is still valid; the `model_costs()` aggregator groups them under `""`.

### WHY
- One-line consumer-side widening, mirrors the producer-side widening at D4. The append-mode JSONL ledger gracefully accepts the wider shape.
- **No JSONL migration required.** Existing rows lack the field; new rows have it. `_read_records()` (analyzer.py:27) parses both via Pydantic's default-fill behavior (BON-346 D-CL.4 invariant honored).

### HOW TO TEST
Knight A spine (in `test_cost_consumer.py`):
```python
async def test_dispatch_completed_with_model_persisted(tmp_path):
    consumer = CostLedgerConsumer(tmp_path / "ledger.jsonl")
    event = DispatchCompleted(
        agent_name="warrior", cost_usd=0.05, duration_seconds=2.0,
        model="claude-haiku-4-5", session_id="s", sequence=0, timestamp=0.0,
    )
    await consumer._on_dispatch_completed(event)
    line = (tmp_path / "ledger.jsonl").read_text().splitlines()[0]
    record = DispatchRecord.model_validate_json(line)
    assert record.model == "claude-haiku-4-5"

async def test_dispatch_completed_without_model_persists_empty():
    # event constructed with default model=""
    # ... record.model == ""
```

Knight B innovation: replay a 100-event sequence with random model assignments; assert ledger faithfulness.

### AMBIG
None.

---

## D8 — CostAnalyzer per-model aggregator (LOCKED — `model_costs() -> list[ModelCost]`)

### WHAT
Add a sixth public method to `CostAnalyzer` in `cost/analyzer.py`, slotted between `agent_costs()` and `all_sessions()`:
```python
def model_costs(self) -> list[ModelCost]:
    """Cumulative cost per model, sorted by spend descending.

    Records lacking a model string (legacy or unattributed) are grouped
    under model="". Empty-string is preserved as a visible bucket -- operators
    want to see how much spend predates per-model attribution.
    """
    dispatches, _ = self._read_records()

    by_model: dict[str, list[DispatchRecord]] = defaultdict(list)
    for d in dispatches:
        by_model[d.model].append(d)

    results = []
    for model_name, records in by_model.items():
        total = sum(r.cost_usd for r in records)
        count = len(records)
        duration = sum(r.duration_seconds for r in records)
        results.append(
            ModelCost(
                model=model_name,
                total_cost_usd=total,
                dispatch_count=count,
                total_duration_seconds=duration,
            )
        )

    results.sort(key=lambda m: m.total_cost_usd, reverse=True)
    return results
```

Imports: add `ModelCost` to the existing import-from at `analyzer.py:10-16`.

### WHY
- **Mirror `agent_costs()` shape.** Same `defaultdict(list)` group-by, same `.sort(key=..., reverse=True)`. Same `O(M)` time, same memory. Same UX expectations downstream (CLI table rendering, anomaly detection).
- **Empty-string bucket preserved.** Operator value > clean output. A "$X.XX of unattributed legacy spend" line in `bonfire cost --by-model` is more informative than silent dropout.
- **Sort = descending by `total_cost_usd`.** Same as `agent_costs()` (line 135). Consistent UX.
- **Pure read-side method.** `_read_records()` handles all parsing/permissiveness. `model_costs()` is a transformer.

### HOW TO TEST
Knight A spine (in `test_cost_analyzer.py`):
```python
class TestModelCosts:
    def test_empty_ledger_returns_empty_list(self, tmp_path):
        analyzer = CostAnalyzer(tmp_path / "absent.jsonl")
        assert analyzer.model_costs() == []

    def test_groups_records_by_model(self, tmp_path):
        # write 2 rows model="A", 1 row model="B" -- assert 2 entries, A first
        ...

    def test_sort_descending_by_cost(self, tmp_path):
        ...

    def test_legacy_empty_model_grouped_visible(self, tmp_path):
        # write rows with model="" alongside model="claude-opus-4-7"
        # assert "" appears as a bucket
        ...

    def test_dispatch_count_correct(self, tmp_path):
        ...

    def test_total_duration_summed(self, tmp_path):
        ...
```

Knight B innovation: pathological case — 10000 records, mix of 5 models, assert sort is stable and counts are correct.

### AMBIG
- **Should we omit the `""` bucket if it's empty?** Decision: `defaultdict` behavior — if no record has `model=""`, the empty bucket never materializes. Consistent with `agent_costs()` behavior for empty `agent_name`.
- **Should `model_costs()` accept a `since: float` filter?** Decision: NO. Defer to D-FT E. v0.1 ships the un-filtered aggregate, mirroring `agent_costs()`.

---

## D9 — Knight contract split

### Knight A — Conservative spine (TDD coverage of D1-D8 minimum-viable contracts)

**Branch:** `antawari/bon-351-knight-a` (already pre-staged by main session)

**Files Knight A writes RED tests in:**
- `tests/unit/test_cost_models.py` — append `TestDispatchRecordModel` (3 tests for `model` field on `DispatchRecord`) and `TestModelCost` (2 tests for the new `ModelCost` class). **Total: +5 tests.**
- `tests/unit/test_cost_consumer.py` — append `TestModelFieldPassthrough` (2 tests: with-model and without-model). **Total: +2 tests.**
- `tests/unit/test_cost_analyzer.py` — append `TestModelCosts` (6 tests covering empty ledger / grouping / sort / legacy bucket / dispatch_count / total_duration). **Total: +6 tests.**
- `tests/unit/test_events.py` — append two tests inside the existing `TestDispatchEvents` class (`test_dispatch_completed_has_model_field`, `test_dispatch_completed_accepts_model`) and update the `_minimal_kwargs` registry comment. **Total: +2 tests, 0 modified registry rows.**
- `tests/unit/test_dispatch_runner.py` — append one test inside the existing event-emission class (`test_dispatch_completed_carries_options_model`). **Total: +1 test.**
- `tests/unit/test_engine_executor.py` — append `TestModelResolution` class with three tests (`test_executor_passes_role_to_resolver`, `test_executor_envelope_model_wins`, `test_executor_config_model_wins_when_resolver_empty`). **Total: +3 tests.**
- `tests/unit/test_engine_pipeline.py` — append `TestModelResolution` class mirroring the executor tests. **Total: +3 tests.**
- `tests/unit/test_wizard_handler.py` — append two tests (`test_role_is_reviewer` inside `TestDispatchOptionsPlumbing`; `test_resolver_called_for_review_model` inside a new class). **Total: +2 tests.**

**Knight A RED commit:** `BON-351 Knight RED: dispatch engine integration of per-role model tier resolver`. **Net: +24 RED tests.** Knight A does NOT touch source files.

### Knight B — Innovation surface (resilience + paired-vocabulary coverage)

**Branch:** `antawari/bon-351-knight-b` (pre-staged)

**Files Knight B writes RED tests in (NO file overlap with Knight A):**
- `tests/unit/test_cost_analyzer.py` — append `TestModelCostsResilience` class with 3 tests: pathological 10k-record corpus, mixed-legacy-and-new rows in same file, sort stability for tied costs. **Total: +3 tests.**
- `tests/unit/test_dispatch_runner.py` — append `TestModelOnRetry` (2 tests: `test_model_unchanged_across_retries`, `test_completed_model_equals_started_model`). **Total: +2 tests.**
- `tests/unit/test_engine_executor.py` — append `TestVocabularyParity` (3 tests: `test_warrior_and_implementer_resolve_same`, `test_wizard_and_reviewer_resolve_same`, `test_unknown_role_falls_through_to_balanced`). **Total: +3 tests.**

**Knight B RED commit:** `BON-351 Knight RED: dispatch resolver resilience + vocabulary parity`. **Net: +8 RED tests.** Knight B does NOT touch source files.

### Combined Knight RED total

**~32 net-new tests across 5 files (no new test files).** No file overlap between Knight A and Knight B — the two branches merge cleanly into the canonical contract-lock branch.

### Sage post-Knight contract-lock

After both Knights commit, Sage rebases their RED tests onto a single `antawari/bon-351-contract-lock` branch (precedent from BON-344, BON-347, BON-348, BON-350). Same Wizard preflight gate applies (D10).

---

## D10 — Warrior surface map (file edits, LOC estimates, edit order)

### Single Warrior pair will solve this in dual

Both Warriors implement against the SAME contract-lock branch. Conservative wins for execution per `feedback_conservative_wins_execution.md` — minimal blast radius is the goal.

### Edit order (schema-first, then producers, then consumers)

| Order | File | Lines added | Lines removed | Notes |
|---|---|---:|---:|---|
| 1 | `src/bonfire/models/events.py:132-136` | +1 | 0 | Add `model: str = ""` field to `DispatchCompleted`. |
| 2 | `src/bonfire/cost/models.py:14-22` | +1 | 0 | Add `model: str = ""` to `DispatchRecord`. |
| 3 | `src/bonfire/cost/models.py` (after `AgentCost`) | +6 | 0 | New `ModelCost` Pydantic class. |
| 4 | `src/bonfire/cost/models.py` (no change) | 0 | 0 | (Confirm `__all__` exports include `ModelCost` if the file has one — currently it does NOT have `__all__`, so no edit.) |
| 5 | `src/bonfire/dispatch/runner.py:184-193` | +1 | 0 | Pass `model=options.model` into `DispatchCompleted(...)`. |
| 6 | `src/bonfire/cost/consumer.py:30-37` | +1 | 0 | Pass `model=event.model` into `DispatchRecord(...)`. |
| 7 | `src/bonfire/cost/analyzer.py:10-16` | +1 | 0 | Add `ModelCost` to the import block. |
| 8 | `src/bonfire/cost/analyzer.py` (between agent_costs and all_sessions) | +25 | 0 | New `model_costs()` method. |
| 9 | `src/bonfire/engine/executor.py:266` | +1 | -1 | Replace `model=envelope.model or self._config.model` with the resolver-aware precedence. Add `from bonfire.agent.tiers import resolve_model_for_role` to imports. |
| 10 | `src/bonfire/engine/executor.py` (constructor) | +1-3 | 0 | Plumb `BonfireSettings` through `__init__` if not already present. **D-CL.1 below details this.** |
| 11 | `src/bonfire/engine/pipeline.py:498` | +1 | -1 | Replace `model=spec.model_override or self._config.model` with the resolver-aware precedence. Same import addition. |
| 12 | `src/bonfire/engine/pipeline.py` (constructor) | +1-3 | 0 | Same settings plumbing. |
| 13 | `src/bonfire/handlers/wizard.py:303-308` | +1 | -1 | Replace `model=stage.model_override or self._config.model` with resolver-aware precedence. |
| 14 | `src/bonfire/handlers/wizard.py:315-322` | +1 | 0 | Add `role=ROLE.value` kwarg. |
| 15 | `src/bonfire/handlers/wizard.py` (constructor) | +1-3 | 0 | Same settings plumbing if not already present. |

**Total approximate LOC delta: ~50 added, ~3 removed across 8 files.** No deletions of public surface.

### Files NOT to TOUCH (negative invariants)

- `src/bonfire/protocols.py` — D3 forbids `DispatchOptions` widening.
- `src/bonfire/agent/tiers.py` — BON-350 owns; this ticket consumes only.
- `src/bonfire/agent/roles.py` — canonical taxonomy; immutable here.
- `src/bonfire/dispatch/sdk_backend.py` — model is consumed at line 110 unchanged.
- `src/bonfire/dispatch/pydantic_ai_backend.py` — same; consumes `options.model` unchanged.
- `src/bonfire/dispatch/tier.py` — `TierGate` is a stub for commercial tiers, unrelated.
- `src/bonfire/dispatch/tool_policy.py` — role-tools mapping is owned elsewhere.
- `src/bonfire/models/envelope.py` — D-CL.4 says no envelope widening; the `model` field already exists at `envelope.py:76`.
- `src/bonfire/naming.py` — display layer untouched.
- `pyproject.toml` — no new deps.

### Knight RED → Warrior GREEN sequencing

1. **Knight A + Knight B (RED phase, parallel):** Land RED tests as listed in D9 on their respective branches. ~32 tests total. NO source modifications.
2. **Sage contract-lock:** Sage rebases both Knight branches into `antawari/bon-351-contract-lock`. Optional: deduplicates any overlapping test names. (Knight contracts in D9 explicitly avoid overlap.)
3. **Warrior GREEN (single Warrior pair, dual workflow against the contract-lock branch):** Warriors implement the 15 edits above. All ~32 RED tests pass + zero regressions on the existing baseline. Commit: `BON-351 Warrior GREEN: dispatch engine integration of per-role model tier resolver`.
4. **Wizard preflight gate (LOCKED below).**
5. **Bard PR + Wizard review on the PR diff (per `feedback_wizard_always_opus.md`: AFTER PR creation, BEFORE merge).**

---

## Test inventory — every existing test file plus extensions

| File | Existing | New tests | Modified tests | Notes |
|---|---:|---:|---:|---|
| `tests/unit/test_cost_models.py` | 5 classes (TestDispatchRecord, TestPipelineRecord, TestSessionCost, TestAgentCost, TestModelsEdge) | +5 (3 in TestDispatchRecordModel, 2 in TestModelCost) | 0 | New classes appended at bottom. |
| `tests/unit/test_cost_consumer.py` | 2 classes (TestCostLedgerConsumer + TestConsumerEdge) | +2 (in new TestModelFieldPassthrough class) | 0 | |
| `tests/unit/test_cost_analyzer.py` | 2 classes (TestCostAnalyzer + TestAnalyzerEdge) | +9 (6 TestModelCosts + 3 TestModelCostsResilience) | 0 | |
| `tests/unit/test_events.py` | TestDispatchEvents + registry sentinel | +2 (in TestDispatchEvents) | 0 | `_minimal_kwargs` registry unchanged because `model` defaults to `""`. |
| `tests/unit/test_dispatch_runner.py` | runner classes | +3 (1 main + 2 retry parity) | 0 | |
| `tests/unit/test_engine_executor.py` | executor classes | +6 (3 TestModelResolution + 3 TestVocabularyParity) | 0 | |
| `tests/unit/test_engine_pipeline.py` | pipeline classes | +3 (TestModelResolution) | 0 | |
| `tests/unit/test_wizard_handler.py` | TestDispatchOptionsPlumbing + others | +2 (1 in plumbing class + 1 in new resolver class) | 0 | |
| `tests/unit/test_protocols.py` | 8 classes | 0 | 0 | `test_has_exactly_eight_fields` confirmed unchanged at 10 fields (existing assertion survives). |
| `tests/unit/test_dispatch_options_role.py` | 9 classes (BON-337) | 0 | 0 | All BON-337 assertions preserved — no role-shape change. |
| `tests/unit/test_dispatch_options_security_hooks.py` | classes (BON-338) | 0 | 0 | Untouched. |
| `tests/unit/test_dispatch_sdk_backend.py` | classes | 0 | 0 | `options.model` consumption unchanged. |
| `tests/unit/test_dispatch_pydantic_ai_backend.py` | classes | 0 | 0 | Same. |
| `tests/unit/test_dispatch_tier.py` | TierGate stub tests | 0 | 0 | `TierGate` ≠ `ModelTier`; no collision. |
| `tests/unit/test_envelope.py` | 13-field sentinel | 0 | 0 | No envelope widening. |

**Net: ~32 new tests, 0 modified, 0 new files.**

---

## D-CL — Constraint Lemmas (sweep-test guards + naming guards)

### D-CL.1 — `BonfireSettings` plumbing through dispatch sites

The resolver needs `settings: BonfireSettings`. The three call sites (executor, pipeline, wizard handler) need access. **Decision: settings injected at constructor time via a new optional kwarg `settings: BonfireSettings | None = None`.** When `None`, callers fall back to `BonfireSettings()` (loads from `bonfire.toml` + env + defaults — Pydantic does the right thing). The pipeline-construction site (CLI / SDK entry) passes the loaded settings explicitly. **Pattern mirrors `PipelineConfig` injection (`config: PipelineConfig`).**

Concrete edit shape (executor as exemplar):
```python
class StageExecutor:
    def __init__(self, ..., config: PipelineConfig, settings: BonfireSettings | None = None):
        self._config = config
        self._settings = settings or BonfireSettings()
```

This is a NON-BREAKING change — existing callers pass `config=`; settings defaults to a fresh `BonfireSettings()` which loads defaults. Tests can opt-in via `StageExecutor(..., settings=test_settings)`.

### D-CL.2 — Resolver import shape

Each of the 3 call sites adds:
```python
from bonfire.agent.tiers import resolve_model_for_role
```
NOT `from bonfire.agent import resolve_model_for_role` (BON-350 D2 re-exports it from the package, but the directly-from-module import is the codebase convention for non-public-surface dependencies — same pattern as `from bonfire.agent.roles import AgentRole` in `handlers/wizard.py:32`). Either path works; pick the module-direct form for grep-friendliness.

### D-CL.3 — `tier` word collision audit (re-affirmed from BON-350 §D-CL.3)

BON-351 introduces NO new `tier` symbol. The three existing uses are unchanged:
- `bonfire.dispatch.tier.TierGate` — commercial tier.
- `bonfire.models.config.PipelineConfig.tier: str = "free"` — same commercial concept (line 42).
- `bonfire.agent.tiers.ModelTier` — capability tier.

The user-cited "PipelineConfig.tier is never read by dispatch" (Scout §C line 171) remains true — BON-351 does NOT make it real. Defer to D-FT B.

### D-CL.4 — `Envelope.model` is the per-stage override channel

`Envelope.model: str = ""` (envelope.py:76) IS the per-stage operator override. The executor reads `envelope.model` first, before the resolver. This is the path callers use to FORCE a specific model regardless of role/tier. The wizard handler builds an envelope with `model=stage.model_override or resolve_model_for_role(...)` — so the resolver result IS what lands on `envelope.model` for the wizard's downstream dispatch, and the executor will pass it through unchanged.

### D-CL.5 — Empty-string model handling at the SDK seam

`sdk_backend.py:110` does `ClaudeAgentOptions(model=options.model, ...)`. If `options.model == ""`, the SDK uses its own default. The resolver in BON-350 NEVER returns `""` for known roles (it falls back to `BALANCED` → `settings.models.balanced` → `"claude-sonnet-4-6"`) — but it DOES return `settings.models.balanced` if the user sets `[models].balanced = ""` in TOML. This is a user pathology, not a bug. The SDK's own default applies. No new validation in BON-351.

### D-CL.6 — Purity test for executor/pipeline imports

Add a single AST-level purity test (in `test_engine_executor.py` or `test_engine_pipeline.py`) asserting that importing `bonfire.engine.executor` and `bonfire.engine.pipeline` does NOT pull in `bonfire.dispatch.sdk_backend`. The resolver lives in `bonfire.agent.tiers` which is upstream of dispatch. If a future refactor moved the resolver into dispatch, this test fails — early signal of layering drift. Pattern matches BON-350 D-CL.5.

### D-CL.7 — Default tier on empty role at the call sites

`stage.role` is `""` in the rare case of pre-BON-337 plans or hand-constructed envelopes. Resolver returns `settings.models.balanced` per BON-350 D7 fallback. This IS the "graceful degradation" path. Tests assert this round-trip.

### D-CL.8 — `agent_name` vs `role` on the ledger

`DispatchRecord.agent_name` carries role-shaped strings today (Scout §B line 113). This memo does NOT add `role` to the ledger. Operators querying "which roles spent the most" use `agent_costs()` (already aggregates by `agent_name`). Operators querying "which models spent the most" use the new `model_costs()`. Per-role-and-per-model crosstab: defer to D-FT D.

---

## Open ambiguities for Knights or main session to adjudicate

1. **Settings construction default** (D-CL.1). `BonfireSettings()` reads `bonfire.toml` from cwd. In test environments, this can leak host-config. **Recommendation:** tests pass an explicit `settings=BonfireSettings(_env_file=None)` or use `monkeypatch.chdir(tmp_path)` patterns already established in `test_config.py`. Knights should check if existing executor/pipeline tests already establish this pattern; if so, follow it.
2. **PipelineConfig.tier removal** (D-CL.3). The field is dead weight. NOT removing it in BON-351 (out of scope), but flag for D-FT B audit cleanup.
3. **Should `DispatchFailed` and `DispatchRetry` ALSO carry `model`?** Defer to D-FT B. Current scope: only `DispatchCompleted` + `DispatchStarted` have `model`. Failed / Retry do not.
4. **Should `model_costs()` filter records by date range or session?** No (D-FT E). v0.1 ships the un-filtered aggregate.
5. **What if `BonfireSettings()` raises during executor construction (e.g., malformed TOML)?** Today, tests construct `BonfireSettings()` defensively. BON-351 should not make this a new failure mode — wrap in try/except in the constructor IF tests reveal the issue. **Recommendation:** Knights write a test for `monkeypatch.chdir(non-toml-dir)` and `BonfireSettings()` succeeds; if it does, no defensive wrapping needed.
6. **Wizard handler's `_config` reference** — does it have access to a `BonfireSettings`? The current `__init__` shape (per `wizard.py` and `test_wizard_handler.py:_make_handler`) takes `config: PipelineConfig`. Adding `settings: BonfireSettings | None = None` is a non-breaking constructor extension — same pattern as the executor/pipeline. Confirm in Knight RED that the handler tests can be parameterized with a settings instance.

---

## D-FT — Follow-up tickets (NOT BON-351 scope)

| Ticket | Milestone | Scope |
|---|---|---|
| **D-FT A** — `bonfire cost --by-model` CLI | W7 routing | Surface `model_costs()` through the CLI. Tabular output. |
| **D-FT B** — `tier` field on cost records + DispatchRecord | W7 routing | Add `tier: str = ""` to `DispatchOptions`, propagate through `DispatchCompleted` and `DispatchRecord`. Adds `CostAnalyzer.tier_costs()`. Requires DispatchOptions widening (test sentinel bumps from 10 → 11). |
| **D-FT C** — `tier` on `DispatchFailed` / `DispatchRetry` events | low | Symmetry with `DispatchCompleted`. Useful for failure attribution by tier. |
| **D-FT D** — Per-role-and-per-model crosstab | W7 / W8 | New `CostAnalyzer.role_model_matrix()` returning `dict[role, dict[model, float]]`. |
| **D-FT E** — `model_costs(since: float, until: float)` | low | Date-range filter for the aggregator. |
| **D-FT F** — Per-attempt model breakdown across retries | low | Today the runner aggregates `cumulative_cost` indiscriminately (Scout §A line 82). If a retry switches models (e.g., fallback to a cheaper model on rate limit), the ledger loses that signal. Adds per-attempt records. |
| **D-FT G** — Backend rejection of unknown model strings | low | Smoke test that a typo'd `settings.models.reasoning = "claude-opus-9-9"` surfaces a clean `model_not_found` envelope error. |
| **D-FT H** — Workflow vocabulary alignment (carried from BON-350 D-FT D) | W7/W8 cleanup | Rename workflow stage `prover` → `assayer` per ADR-001. |

---

## D-W — Wizard preflight gate (LOCKED)

### Baseline

Wizard MUST snapshot fresh from tip of `v0.1@a07e118` (or the actual tip at dispatch time): `passed_before`, `failed_before` (must be 0), `xfailed_before`, `xpassed_before`, `errors_before` (must be 0). This memo does NOT bake a baseline integer — upstream merges shift the count between memo and dispatch.

### Expected delta after BON-351 GREEN

- `passed_after − passed_before == +32 ± 4` (exact: 5 + 2 + 9 + 2 + 3 + 6 + 3 + 2 = 32; tolerance covers parameterization variance and any test that splits across paramaterize).
- `failed_after == 0`, `errors_after == 0`.
- `xfailed_after − xfailed_before == 0`.
- `xpassed_after − xpassed_before == 0`.

### Hard fails (Wizard rejects)

- Any `failed > 0` or `errors > 0`.
- `xfailed` / `xpassed` deltas non-zero.
- `passed` delta outside `[+28, +36]`.
- Any change in `src/bonfire/protocols.py` (D3 forbids).
- Any change in `src/bonfire/agent/tiers.py` (BON-350 owns).
- Any change in `src/bonfire/dispatch/sdk_backend.py:110` (D-CL.5 forbids).
- Any new entry in `pyproject.toml` dependencies.
- Any change to `_CURRENT_SCHEMA_VERSION` in `models/config.py` (no schema migration in BON-351).
- A bumped `len(DispatchOptions.model_fields)` (D3 forbids — must stay at 10).

---

## Summary table — what Warriors must produce

| Artifact | Path | LOC est | Purpose |
|---|---|---:|---|
| `DispatchCompleted.model` field | `src/bonfire/models/events.py:132-136` | +1 | Carry the model on completion. |
| `DispatchRecord.model` field | `src/bonfire/cost/models.py:14-22` | +1 | Persist the model on the ledger row. |
| `ModelCost` Pydantic class | `src/bonfire/cost/models.py` | +6 | Aggregator output type. |
| Runner emit | `src/bonfire/dispatch/runner.py:184-193` | +1 | `model=options.model` on Completed event. |
| Consumer passthrough | `src/bonfire/cost/consumer.py:30-37` | +1 | `model=event.model` on record. |
| Analyzer aggregator | `src/bonfire/cost/analyzer.py` | +25 | `model_costs() -> list[ModelCost]`. |
| Executor resolver wiring | `src/bonfire/engine/executor.py:266` | +2 | Resolver call + import. |
| Pipeline resolver wiring | `src/bonfire/engine/pipeline.py:498` | +2 | Resolver call + import. |
| Wizard resolver wiring | `src/bonfire/handlers/wizard.py:303-322` | +3 | Resolver call + role kwarg. |
| Settings plumbing (3 sites) | executor/pipeline/wizard `__init__` | +9 | `settings: BonfireSettings | None = None`. |
| Knight A RED tests | 8 test files | ~24 tests | Spine coverage of D1-D8. |
| Knight B RED tests | 3 test files | ~8 tests | Resilience + vocabulary parity. |

**Net: ~32 net-new tests, ~50 LOC source, 0 new files, 0 deletions of public surface.**

---

**END BON-351 Sage memo.**
