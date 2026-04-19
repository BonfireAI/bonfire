# Scout-3 / BON-338 / Bonfire Integration — Report

## 1. SDK Hook Attachment Seam

**File:** `src/bonfire/dispatch/sdk_backend.py`
**Function:** `ClaudeSDKBackend._do_execute()`, lines 99-110.
**Seam:** `ClaudeAgentOptions(...)` constructor call. Today receives 10 kwargs. Does NOT pass `hooks=`. SDK supports `hooks: dict[HookEvent, list[HookMatcher]]` — slot is open.

Current (sdk_backend.py:99-110):

```python
agent_options = ClaudeAgentOptions(
    model=options.model,
    max_turns=options.max_turns,
    max_budget_usd=options.max_budget_usd,
    cwd=options.cwd or None,
    permission_mode=options.permission_mode,
    allowed_tools=options.tools,
    setting_sources=["project"],
    thinking=thinking_config,
    effort=effort_level,
    stderr=lambda line: logger.warning("[CLI stderr] %s", line),
)
```

Proposed insertion:

```python
agent_options = ClaudeAgentOptions(
    ...,
    allowed_tools=options.tools,
    hooks=_build_security_hooks(options.security, bus=self._bus, session_id=envelope.envelope_id),
    setting_sources=["project"],
    ...,
)
```

Single added kwarg. Backend never raises — existing `execute()` → `_do_execute()` outer try/except (lines 76-85) converts exception to FAILED envelope.

Import-guard at lines 28-39 wraps `ClaudeAgentOptions` in `try/except ImportError` setting to `None`. `HookMatcher`/hook-event types must join same guard.

## 2. Current EventBus Topology

**File:** `src/bonfire/events/bus.py` (130 lines). Functional, transferred W2.3 (BON-333).

### Bus API
- `subscribe(event_type, handler)` — typed (bus.py:65-76)
- `subscribe_all(handler)` — global (bus.py:78-87)
- `async emit(event)` — typed-first, global-second (C7 guarantee, bus.py:89-129). Increments sequence, stamps via `model_copy(update={"sequence": n})`. Consumer isolation: each handler try/excepted.

### 28 events across 9 categories (`models/events.py`)
Pipeline (4) / Stage (4) / Dispatch (4) / Quality (3) / Git (4) / Cost (3) / Session (2) / XP (3) / Axiom (1). **No `Tool*` events. No `Security*` events.**

### Producers
- `dispatch.runner.execute_with_retry` emits `DispatchStarted/Completed/Failed/Retry` (runner.py:103, 131, 149, 168, 184, 226).
- Pipeline engine (W3.1 just landed) will emit `Pipeline*`/`Stage*`.
- `CostTracker` itself emits `CostBudgetWarning`/`CostBudgetExceeded` (consumers/cost.py:35-65).

### Consumers (`events/consumers/__init__.py:26-53`)
`wire_consumers()` registers 4 defaults:
- `SessionLoggerConsumer` — global, persists every event (logger.py)
- `DisplayConsumer` — typed for `StageCompleted/StageFailed/QualityFailed/CostBudgetWarning` (display.py:84-89)
- `CostTracker` — typed for `DispatchCompleted` (cost.py:35)
- `VaultIngestConsumer` — typed for `StageCompleted/StageFailed/DispatchFailed/SessionEnded` per BON-333 Sage (surface only, real ingestion deferred)

### Adding `SecurityDenialEvent`

Belongs in `models/events.py` under new `Security` category, NOT under `Tool*` (tool events are separate audit concern). Add to:
1. Class defs (new section next to `XPAwarded`)
2. Discriminated `BonfireEventUnion` (lines 301-331)
3. `EVENT_REGISTRY` dict (lines 339-368)

`SessionLoggerConsumer` picks up automatically (subscribe_all). `DisplayConsumer` needs new typed subscription for CLI visibility. No existing consumer breaks.

## 3. Private V1 Existing Hook Wiring

**Zero SDK hook wiring in private V1.** Evidence:

- `bonfire/src/bonfire/dispatch/sdk_backend.py:187-199` — builds `ClaudeAgentOptions` with 11 kwargs. **No `hooks=`.** Almost identical to public v0.1 (plus `system_prompt`, `setting_sources` passthrough).
- Grep `bonfire/src/` for `PreToolUse|HookMatcher|hooks=` in SDK sense — **zero matches**. Only matches in `docs/audit/*` (propose adding) and `persona/hookspec.py` (pluggy, structurally unrelated).
- Private V1 audit finding `F2-scout.json:42` confirms verbatim: *"sdk_backend.py:109-121 constructs ClaudeAgentOptions with … NO hooks= kwarg is ever passed."*
- Private V1 `ls dispatch/` = same 6 files as public v0.1. **No `hook_bridge.py`, no `hooks.py`, no `security_hooks.py`.**

### How private V1 surfaces tool audits today

Doesn't. Envelope-level only. Audit report `M1-sdk-verifier.json:45`: *"hooks … would let the same EventBus observe PreToolUse, PostToolUse, PreCompact INSIDE the single dispatch."*

**Implication:** BON-338 is greenfield. No transfer; no reference. Audit findings document intended shape but code was never written — v0.1-first feature per trust-triangle release gate.

## 4. Proposed Architectural Shape

### Release-policy context (load-bearing)

`docs/release-policy.md:41-43` names four trust-triangle components blocking v0.1.0:
1. W1.5.1 interfaces
2. W1.5.3 default allow-list floor
3. W4.1 user-configurable allow-lists — **BON-337**
4. W4.2 default security hook set — **BON-338**

BON-338 is one leg of a four-legged trust guarantee. Users install `bonfire-ai==0.1.0` expecting default deny set.

### Module layout — `src/bonfire/security/` (new subpackage)

Rationale: hooks + allow-lists are same security subsystem. Colocating beats scattering.

```
src/bonfire/security/
    __init__.py          # SecurityHookConfig, build_security_hooks, default_deny_patterns
    hooks.py             # PreToolUse factory + deny-check logic
    patterns.py          # DEFAULT_DENY_PATTERNS + role-specific overlays
    config.py            # SecurityHookConfig Pydantic model
    events.py (optional) # SecurityDenialEvent — OR add to models/events.py
```

Precedent: `bonfire/events/`, `bonfire/cost/`, `bonfire/workflows/` are sibling first-class subpackages.

**Alternative (rejected):** inline in `sdk_backend.py`. Rejected because (a) `pydantic_ai_backend.py` will want same semantics; (b) hooks testable without SDK when isolated; (c) BON-337 needs same home.

### Deny-list source — three-layer composition

1. **`DEFAULT_DENY_PATTERNS`** — hardcoded constants in `security/patterns.py`. Non-configurable. W1.5.3 "floor" guarantee — defaults cannot be softened. Types: tool names + regex-against-tool-input.
2. **Role-overlay deny** — `DEFAULT_DENY_PATTERNS_BY_ROLE: dict[str, list[Pattern]]`. Public v0.1 has 7 roles. E.g. `"knight"` adds src/ write denial.
3. **User deny extension** — loaded from `bonfire.toml` (BON-337 territory). Hook composes `defaults + role_overlay + user_extension`. Deny always wins.

**Role-specific denials arrive via `envelope.agent_name` or `envelope.metadata["role"]`** (fields exist — envelope.py:75, sdk_backend.py:96 in V1). No new envelope field required.

### Event emission — **emit on deny only**

- **Deny:** emit `SecurityDenialEvent(session_id, sequence, tool_name, reason, pattern_matched, agent_name)`. Blocking signal, low volume, high value.
- **Allow:** NO event. Every tool call floods bus. Tool-level success telemetry = separate ticket (`Tool*` event family proposed in V1 F2-5, NOT BON-338 scope).
- **Hook error:** hook catches own exceptions, logs warning, defaults to ALLOW (fail-open on infrastructure bug). Sage should lock explicitly.

Rationale: `SecurityDenialEvent` is *decision*, not *telemetry*. Matches existing patterns (`QualityFailed`, `DispatchFailed` — failure-mode events).

### Composition with BON-337's allow-list

**Semantic runtime ordering:**
```
SDK evaluation: hooks → deny rules → permission_mode → allow rules → can_use_tool
```

SDK runs **hooks first**, before `allowed_tools`. BON-338 (hook) semantically precedes BON-337 (allow-list). Hook can deny tool allow-list would permit. Safety wins.

**Shared module:** yes — same `bonfire/security/` package. BON-337 adds `patterns.py::DEFAULT_ALLOW_PATTERNS` + `config.py::SecurityHookConfig.allow`. Both read same `SecurityHookConfig`. Neither ticket couples tightly to other's internals — share config object.

## 5. Public API Surface Proposal

### Single Pydantic config through `DispatchOptions`

```python
# src/bonfire/security/config.py
from pydantic import BaseModel, ConfigDict, Field

class SecurityHookConfig(BaseModel):
    """User-facing security policy for a Bonfire dispatch.

    Composes with default deny-list floor — user values EXTEND, not replace.
    Denials always win over allows.
    """
    model_config = ConfigDict(frozen=True)

    extra_deny_patterns: list[str] = Field(default_factory=list)
    extra_allow_patterns: list[str] = Field(default_factory=list)  # BON-337
    emit_denial_events: bool = True
    fail_open_on_hook_error: bool = True  # see §4 "Hook error"
```

### Extending `DispatchOptions`

Per V1 F2-scout finding F2-6, `DispatchOptions` is composition-safe seam:

```python
class DispatchOptions(BaseModel):
    ...existing 8 fields...
    security: SecurityHookConfig = Field(default_factory=SecurityHookConfig)
```

`default_factory=SecurityHookConfig` means every dispatch gets non-None config with defaults — **trust-triangle guarantee automatic** (caller has to work to turn off). Implements release-gate promise: v0.1.0 users cannot accidentally ship without default deny floor.

### Backend pattern

`PydanticAIBackend` ignores `security` field (AgentBackend protocol is structural). Only `ClaudeSDKBackend` consumes in v0.1. Future backends opt in.

### Auto-applied default

Default `SecurityHookConfig()` IS the "W4.2 default security hook set" deliverable. If user writes:

```python
await runner.execute_with_retry(backend, envelope, DispatchOptions())
```

…the default deny set applies. No opt-in required. Opt-out requires explicit custom `SecurityHookConfig`, and even then `DEFAULT_DENY_PATTERNS` cannot be softened below floor (W1.5.3). Sage locks that defaults are hardcoded constants not overridable from `SecurityHookConfig`.

## 6. Composition with BON-337

### Ordering at runtime

Per SDK evaluation order (confirmed `bonfire/docs/spikes/bon-366/scout-machinist.md:72`):

```
hooks (BON-338) → deny rules → permission_mode → allow rules (BON-337) → can_use_tool
```

Hook runs **first**, before `allowed_tools`. Intended safety ordering: hook's deny is authoritative regardless of allow-filter.

### Shared module

Both tickets live in `src/bonfire/security/`. BON-337 contributes `config.py::SecurityHookConfig.extra_allow_patterns` + logic to project onto `options.tools` in `sdk_backend.py` before `ClaudeAgentOptions`. BON-338 contributes hook factory + deny patterns.

**Both read same `SecurityHookConfig`.**

### Coupling concerns

- If BON-337 and BON-338 ship in different PRs, Sage must require they use same `SecurityHookConfig`. Premature lock of shape by whichever lands first blocks other.
- Recommendation: **ship `SecurityHookConfig` Pydantic model first (shared seam), then two deliveries against it.** BON-334-style "seam before body" pattern (memory `feedback_seam_before_body.md`).
- Without coordination, BON-337 could define `AllowListConfig` and BON-338 `HookConfig`, fragmenting caller experience.

## 7. Cross-Lane Scrub Notes

Private V1 references that would leak:

1. `docs/audit/findings/F2-scout.json` references internal Seal numbers (`Seal #2`, `Seal #4`, `Seal #10`, `Seal #11`) — private Operation Seal labels. **Scrub.**
2. Same references `docs/constraint-index.md` (`C9`, `C11-C15`, `C51`) — public v0.1 has no constraint-index.md. **Don't cite constraint numbers.**
3. `docs/superpowers/plans/2026-04-16-operation-seal-plan.md` — private. **Never reference Operation Seal or Seal-# labels.**
4. Private V1 ticket numbers — `BON-\d+` references scrubbed in canonical transfer per BON-334/336. **Avoid private-lane BON numbers.**
5. Private V1 `src/bonfire/persona/hookspec.py` uses pluggy. Do NOT confuse with SDK hooks — different subsystem. **Avoid naming new module `hooks.py` at top level of `bonfire/`** — conflicts conceptually. `bonfire/security/hooks.py` is namespaced correctly.
6. V1 cost-parsing and XP calculators referenced in F2-5 as consumers benefiting from `Tool*` events. **BON-338 does NOT add `Tool*` events.**

## 8. Open Questions for Sage

1. **Hook error policy — fail-open or fail-closed?** Draft proposes fail-open (allow tool) to avoid bricking on our bugs. Sage should lock against beta-safety risk tolerance. Knob on safety rail is itself a risk.
2. **Do we need `SecurityAllowEvent`?** §4 recommends deny-only. But if CLI session logger wants to prove "every tool ran was allow-list-approved," might need allow audit trail. Alternative: periodic `SecurityAuditSummaryEvent` on `SessionEnded`.
3. **Role-deny overlay — where is `role` sourced?** Envelope has `agent_name: str` (envelope.py:75) and dispatch receives `envelope.metadata.get("role")` (V1 pattern). BON-338 needs definitive answer. Candidates: `envelope.agent_name`, `options.tools`, new `DispatchOptions.role: str`. **Recommend last** — explicit, doesn't overload `agent_name`.
4. **Do denials abort envelope or just tool call?** SDK PreToolUse can return `PermissionResultDeny` failing just tool. LLM typically tries another approach. If role keeps hitting denials, dispatch should short-circuit (after N denials → FAILED envelope with `error_type="security_denial"`). Threshold? Interacts with retry loop in `runner.py`. Needs Sage lock.

## Sources

- `src/bonfire/dispatch/sdk_backend.py:99-110` — seam; no `hooks=` kwarg
- `src/bonfire/dispatch/sdk_backend.py:28-39` — SDK import guard
- `src/bonfire/events/bus.py:60-129` — EventBus API
- `src/bonfire/models/events.py:38-368` — 28 events, no Tool* or Security*
- `src/bonfire/events/consumers/__init__.py:26-53` — default consumers
- `src/bonfire/events/consumers/logger.py:28-30` — SessionLoggerConsumer subscribe_all
- `src/bonfire/events/consumers/display.py:84-89` — DisplayConsumer typed subs
- `src/bonfire/protocols.py:47-67` — DispatchOptions seam
- `docs/release-policy.md:41-43` — W4.1/W4.2 trust-triangle requirement
- `docs/audit/sage-decisions/bon-334-sage-2026-04-18T19-14-42Z.md:174-192` — Sage D11 scope discipline
- `bonfire/src/bonfire/dispatch/sdk_backend.py:187-199` — V1 reference, no hooks
- `bonfire/docs/audit/findings/F2-scout.json:42-48, 104-112, 120-128` — V1 audit F2-5, F2-6
- `bonfire/docs/spikes/bon-366/scout-machinist.md:72` — SDK evaluation order
- `bonfire/src/bonfire/persona/hookspec.py:1` — pluggy hookspec (naming-clash risk)
- `src/bonfire/cli.py:1-36` — public CLI pre-release stub; no composition root yet (Wave 6+)
