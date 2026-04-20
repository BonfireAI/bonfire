# Sage Decision Log — W5.7: `cost/` + `session/` transfer

**Scope:** Canonical RED suites for `bonfire.cost` (renamed from private
`bonfire.costs`) and `bonfire.session`.

**Inputs:**
- Knight-A (innovative, 4 files, 88 tests, commit `91a152a`)
- Knight-B (conservative, 4 files, 45 tests, commit `df36ec3`)
- Private v1 reference at `/home/ishtar/Projects/bonfire/src/bonfire/costs/` + `.../session/`

**Output:** 4 canonical test files in `tests/unit/` + this log + Warrior handoff.

---

## Critical invariant locked

The package rename `costs` (plural) -> `cost` (singular) applies everywhere.

- Every import: `from bonfire.cost.models import ...`, `from bonfire.cost.analyzer ...`,
  `from bonfire.cost.consumer ...`.
- Every `DEFAULT_LEDGER_PATH` default: `Path.home() / ".bonfire" / "cost" / "cost_ledger.jsonl"`.
- Every in-repo package: `src/bonfire/cost/`.
- The `~/.bonfire/cost/` directory mirrors the Python package name — no
  residual `costs/` appears anywhere in the public surface.

This is DISTINCT from `bonfire.events.consumers.cost::CostTracker` (the
in-memory budget watcher already live in v0.1). `CostLedgerConsumer` lands
at `bonfire.cost.consumer` and serves a different role (persistence).

---

## Tension matrix

Each Knight divergence, the resolution, and the rationale.

### 1. `DEFAULT_LEDGER_PATH` convention (singular `cost/`)

- **Knight-A:** `~/.bonfire/cost/cost_ledger.jsonl` (rename applied).
- **Knight-B:** did not pin the path explicitly; fixture uses singular
  `tmp_path / "cost" / "cost_ledger.jsonl"`.
- **Resolution:** LOCK singular. Path default matches package name. Warrior
  MUST set `DEFAULT_LEDGER_PATH = Path.home() / ".bonfire" / "cost" / "cost_ledger.jsonl"`
  in `src/bonfire/cost/models.py`.
- **Rationale:** the rename is a package-surface decision; letting the
  default path keep the private `costs/` plural would leak the private
  naming into the public install footprint.

### 2. `stages_completed` int-vs-float strictness

- **Knight-A:** permissive (accepts Pydantic coercion OR strict rejection).
- **Knight-B:** mirrors private v1 (no edge test).
- **Verification:** `pydantic.BaseModel` v2 default with `x: int` REJECTS
  `2.7` with `int_from_float` error and COERCES `2.0` to `2`. Verified
  live in the worktree venv.
- **Resolution:** LOCK strict. Test asserts `ValidationError` on
  `stages_completed=2.7`. Catches any future Warrior that might set
  `strict=False` or add `Annotated[int, BeforeValidator(...)]`.
- **Rationale:** silent truncation of 2.7 -> 2 would smuggle bad data past
  the schema. Private v1's Pydantic-default behavior is already strict
  enough to raise — we pin that behavior.

### 3. Fixture dir name in `test_cost_consumer.py`

- **Both Knights:** singular `tmp_path / "cost" / "cost_ledger.jsonl"`.
- **Resolution:** aligned, no change.

### 4. `test_each_record_on_its_own_line` trailing `\n`

- **Knight-A:** asserts `raw.endswith("\n")`.
- **Knight-B:** no equivalent.
- **Verification:** private `costs/consumer.py` line 52 writes
  `record.model_dump_json() + "\n"` — trailing newline is part of the
  contract.
- **Resolution:** KEEP Knight-A's stricter assertion. The trailing `\n`
  guarantees `TestAnalyzerEdge::test_truncated_final_line_is_skipped`
  doesn't get a false green from a trailing-newline shortcut.

### 5. `test_session_id_with_unusual_chars`

- **Knight-A:** includes quotes, unicode, tabs.
- **Knight-B:** no equivalent.
- **Resolution:** KEEP broader coverage. The JSON encoder escapes quotes
  and newlines inside strings natively, so the JSONL line stays parseable.
  Documented as a hardening assertion against operator-supplied session
  ids.

### 6. Baseline count drift (`1904 collected, 1883 passed`)

- **Observation:** cosmetic — "baseline 1883" is the passing count; 21
  tests are `xfail`/`xpass` markers.
- **Resolution:** no change needed. Full-suite invariant preserved.

### 7. Coverage expansions from Knight-A

Adversarial edges Knight-A added beyond the private mirror:

- `test_blank_lines_are_skipped`
- `test_truncated_final_line_is_skipped`
- `test_unknown_record_type_is_skipped`
- `test_record_missing_required_fields_is_skipped`
- `test_duplicate_pipeline_record_last_write_wins`
- `test_interleaved_sessions_parse_correctly`
- `test_large_ledger_parses_without_error` (10K rows)
- `test_zero_stages_pipeline_is_preserved`
- `test_crlf_line_endings_are_tolerated`
- `test_concurrent_emits_serialized_by_bus` (asyncio.gather × 50)
- `test_ledger_appends_to_preexisting_file`
- `test_duration_is_none_before_start`
- `test_status_is_pending_before_end`
- `test_persistence_append_after_dir_deleted_recreates`
- `test_persistence_list_ignores_non_jsonl_files`

**Resolution:** KEEP all. Grouped under `TestAnalyzerEdge`,
`TestConsumerEdge`, `TestModelsEdge`, `TestSessionStateEdge`,
`TestSessionPersistenceEdge` for discoverability. Rationale in the docstring
above each class.

### 8. Drops from Knight-A

Cases removed because they added noise without pinning the contract:

- `test_burst_of_events_no_line_corruption` (200 emits) — covered
  functionally by `test_concurrent_emits_serialized_by_bus` (50 emits
  via asyncio.gather). Keeping both would just slow CI.
- `test_two_consumers_on_same_ledger_both_append` — implementation-defined
  behavior; not a promise we want to make in v0.1 (could change with
  async file locks).
- `test_roundtrip_preserves_event_timestamp` — subsumed by the baseline
  `test_dispatch_record_has_timestamp_from_event`.

### 9. `asyncio_mode = "auto"`

- **Observed:** `pyproject.toml` sets `asyncio_mode = "auto"`.
- **Decision:** drop Knight-B's explicit `@pytest.mark.asyncio` marks.
  Auto mode discovers `async def` tests automatically.

---

## Dedupe math

- Raw total: 88 (A) + 45 (B) = **133 tests**.
- Canonical total: **86 tests**.
- Reduction: 47 tests deduped (35% shrink) while preserving ALL of
  Knight-A's adversarial lens.

Per file:

| file                    | Knight-A | Knight-B | Canonical | Notes |
|-------------------------|---------:|---------:|----------:|-------|
| `test_cost_models.py`   | 19       | 9        | 19        | 9 baseline (`TestDispatchRecord`=3, `TestPipelineRecord`=2, `TestSessionCost`=3, `TestAgentCost`=1) + 10 `TestModelsEdge` |
| `test_cost_analyzer.py` | 22       | 11       | 23        | 12 baseline `TestCostAnalyzer` (adds A's `all_records` sort + B's multi-session detail assertion) + 11 `TestAnalyzerEdge` |
| `test_cost_consumer.py` | 15       | 5        | 12        | 5 baseline `TestCostLedgerConsumer` + 7 `TestConsumerEdge` |
| `test_session.py`       | 32       | 20       | 32        | 20 baseline (`TestSessionImports`=2, `TestSessionStateInit`=2, `TestSessionStateLifecycle`=4, `TestSessionStateToDict`=1, `TestSessionPersistenceAppend`=3, `TestSessionPersistenceRead`=3, `TestSessionPersistenceList`=2, `TestSessionPersistenceExists`=1, `TestSessionRoundTrip`=2) + 6 `TestSessionStateEdge` + 6 `TestSessionPersistenceEdge` |
| **Total**               | **88**   | **45**   | **86**    |       |

Canonical count (86) sits in the 80-100 target with every adversarial edge
preserved.

---

## Warrior handoff

### Source files to create

```
src/bonfire/cost/__init__.py       (exports AgentCost, CostAnalyzer,
                                    CostLedgerConsumer, DispatchRecord,
                                    PipelineRecord, SessionCost)
src/bonfire/cost/models.py         (DEFAULT_LEDGER_PATH + 4 BaseModels)
src/bonfire/cost/analyzer.py       (CostAnalyzer)
src/bonfire/cost/consumer.py       (CostLedgerConsumer)

src/bonfire/session/__init__.py    (exports SessionState, SessionPersistence)
src/bonfire/session/state.py       (SessionState)
src/bonfire/session/persistence.py (SessionPersistence)
```

All files mirror the private v1 source with `costs` -> `cost` rename applied
on imports and the `DEFAULT_LEDGER_PATH` default.

### DEFAULT_LEDGER_PATH (locked)

```python
from pathlib import Path

DEFAULT_LEDGER_PATH: Path = Path.home() / ".bonfire" / "cost" / "cost_ledger.jsonl"
```

### API surface

**`bonfire.cost.models`** — 4 Pydantic BaseModels:

- `DispatchRecord(type: Literal["dispatch"]="dispatch", timestamp: float, session_id: str, agent_name: str, cost_usd: float, duration_seconds: float)`
- `PipelineRecord(type: Literal["pipeline"]="pipeline", timestamp: float, session_id: str, total_cost_usd: float, duration_seconds: float, stages_completed: int)`
- `SessionCost(session_id: str, total_cost_usd: float, duration_seconds: float, dispatches: list[DispatchRecord], stages_completed: int, timestamp: float)` — plus `@property date -> str` returning `datetime.fromtimestamp(self.timestamp, tz=UTC).strftime("%Y-%m-%d")`.
- `AgentCost(agent_name: str, total_cost_usd: float, dispatch_count: int, avg_cost_usd: float)`

**`bonfire.cost.analyzer::CostAnalyzer`** — read-only query layer:

```python
CostAnalyzer(ledger_path: Path = DEFAULT_LEDGER_PATH)

cumulative_cost() -> float                           # sum of PipelineRecord.total_cost_usd
session_cost(session_id: str) -> SessionCost | None  # None if no matching records
agent_costs() -> list[AgentCost]                     # sorted by total_cost_usd DESC
all_sessions() -> list[SessionCost]                  # sorted by timestamp DESC, dedup by session_id (last pipeline wins)
all_records() -> list[DispatchRecord | PipelineRecord]  # sorted by timestamp ASC
```

Internal `_read_records()` MUST:
- return `([], [])` if file missing.
- skip blank lines.
- skip lines that fail `json.loads` (log warning).
- skip records with unknown `type` (log warning).
- skip records that fail `.model_validate(...)` (log warning).
- Never raise on file I/O or parse errors.

**`bonfire.cost.consumer::CostLedgerConsumer`** — persistence consumer:

```python
CostLedgerConsumer(ledger_path: Path = DEFAULT_LEDGER_PATH)

register(bus: EventBus) -> None
    bus.subscribe(DispatchCompleted, self._on_dispatch_completed)
    bus.subscribe(PipelineCompleted, self._on_pipeline_completed)

# Each handler builds the matching record from the event fields and calls
# _append(record). _append MUST:
#   self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
#   with self._ledger_path.open("a", encoding="utf-8") as fh:
#       fh.write(record.model_dump_json() + "\n")
```

Append mode (`"a"`) is critical — tests verify preexisting ledgers are not
clobbered on `register`.

**`bonfire.session::SessionState`** — mutable lifecycle:

```python
SessionState(session_id: str, plan_name: str, workflow_type: str)

# read-only properties
session_id -> str
plan_name -> str
workflow_type -> str
is_active -> bool
total_cost_usd -> float
stages_completed -> int
status -> str                    # "pending" after start(), set by end()
duration_seconds -> float | None # None before start()

# mutators
start() -> None                  # is_active=True, start_time=time.monotonic()
record_stage(name: str, cost: float) -> None   # appends to completed_stages, adds to total
end(status: str = "completed") -> None         # is_active=False, set end_time + status

# serialization
to_dict() -> dict[str, Any]
    # keys: session_id, plan_name, workflow_type, is_active, total_cost_usd,
    #       stages_completed, duration_seconds, status, completed_stages
```

**`bonfire.session::SessionPersistence`** — JSONL append-only store:

```python
SessionPersistence(session_dir: Path)

append_event(session_id: str, event: BonfireEvent) -> None
    # mkdir(parents=True, exist_ok=True), open(<sid>.jsonl, "a"), write model_dump(mode="json") + "\n"
read_events(session_id: str) -> list[dict]   # raises FileNotFoundError if missing
list_sessions() -> list[str]                  # sorted(p.stem for p in dir.glob("*.jsonl"))
session_exists(session_id: str) -> bool
```

Note: `list_sessions` uses `*.jsonl` glob — foreign files (`notes.md`,
`.DS_Store`) are filtered out by the glob pattern, satisfying the
`test_persistence_list_ignores_non_jsonl_files` edge.

### Tests the Warrior must NOT modify

- `tests/unit/test_event_consumers.py` (existing, covers `CostTracker`).
- `src/bonfire/events/consumers/cost.py::CostTracker` (unrelated seam —
  in-memory budget watcher).

### Verification

After Warrior GREEN:

```bash
cd /home/ishtar/Projects/bonfire-public
/home/ishtar/Projects/bonfire-public/.venv/bin/pytest tests/unit/test_cost_models.py tests/unit/test_cost_analyzer.py tests/unit/test_cost_consumer.py tests/unit/test_session.py -v
/home/ishtar/Projects/bonfire-public/.venv/bin/pytest tests/  # expect baseline + 91 new passes
/home/ishtar/Projects/bonfire-public/.venv/bin/ruff check src/bonfire/cost/ src/bonfire/session/ tests/unit/test_cost_*.py tests/unit/test_session.py
/home/ishtar/Projects/bonfire-public/.venv/bin/ruff format --check src/bonfire/cost/ src/bonfire/session/ tests/unit/test_cost_*.py tests/unit/test_session.py
```

### Unresolved items for Wizard pre-merge

None at the contract level. One sanity check to run in CI once Warrior
GREEN lands: confirm `bonfire.cost` does not shadow or collide with any
pre-existing imports of `bonfire.costs` anywhere in the public repo
(`grep -rn "bonfire.costs" src/ tests/` should return zero hits; if any
appear, they're stragglers from the transfer and need to be updated to
`bonfire.cost`).

