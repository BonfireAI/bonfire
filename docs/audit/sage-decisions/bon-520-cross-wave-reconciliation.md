# BON-520 Cross-Wave Reconciliation — Sage Decision Log

**Date:** 2026-04-21
**v0.1 tip:** `e00a062` (after BON-342 handlers/ + BON-345 persona/ merged independently)
**Sage branch:** `antawari/bon-520-sage`
**Scope:** Operational reconciliation of two sibling-batch Sage syntheses that broke 23 tests on the combined tip.

This log is NOT a re-litigation of BON-342 D1–D6 or BON-345 D1–D6. Both prior
syntheses were individually correct against their scope. The breakage is at
the pipeline level (see Operation Splatter BON-519 for the merge-preflight
follow-up). This log arbitrates reconciliation only: what shape the RED
side must take so the Warrior's TOML edits will flip the combined suite
GREEN in one bounded diff.

## Context — the three clusters (23 failures total)

| Cluster | Count | Owner | Symptom |
|---|---|---|---|
| RC1 | 16 | Warrior (TOMLs) + Sage (one hardcoded frozenset) | Builtin TOMLs only cover 8/9 roles — missing `analyst` |
| RC2 | 2  | Sage (rename sweep) | `test_config.py` still asserts old default `"passelewe"` |
| RC3 | 5  | Sage (test helpers)  | `test_persona_toml_schema.py` helpers bake in 8-role blocks |

Everything below flows from the same root: `AgentRole` now carries 9 members
(`analyst` added by BON-342 D1), and BON-345's artefacts — TOMLs, test
helpers, and one pre-existing 8-role assertion — were written when the enum
had 8.

---

## §D1 — RC1 fix strategy (Warrior-owned, 3 builtin TOMLs)

**Verdict:** The Warrior extends each built-in's `[display_names]` table
with exactly one new entry.

| Built-in | New line | Rationale |
|---|---|---|
| `src/bonfire/persona/builtins/default/persona.toml` | `analyst = "Analysis Agent"` | Default uses `ROLE_DISPLAY[role].professional` per BON-345 D5. BON-342 D1 locks `ROLE_DISPLAY["analyst"] = DisplayNames("Analysis Agent", "Architect")`. |
| `src/bonfire/persona/builtins/minimal/persona.toml` | `analyst = "Analysis Agent"` | Same rationale — minimal ships professional names, no personality markers (BON-345 D5). |
| `src/bonfire/persona/builtins/passelewe/persona.toml` | `analyst = "Architect"` | Passelewe is gamified (BON-345 D5). Uses `ROLE_DISPLAY["analyst"].gamified` literal. |

**Do NOT re-order existing entries.** Append `analyst = ...` at the end of
each `[display_names]` block. Line-count delta per TOML: +1.

Once landed, the following 15 of the 16 RC1 failures flip GREEN automatically:

- `test_persona_builtin.py::TestDefaultPersonaShips::test_default_covers_all_agent_roles`
- `test_persona_builtin.py::TestDefaultPersonaShips::test_default_passes_schema_validation`
- `test_persona_builtin.py::TestEveryShippedBuiltinPassesSchema::test_every_shipped_builtin_passes_schema`
- `test_persona_builtin.py::TestMinimalPersonaShips::test_minimal_covers_all_agent_roles`
- `test_persona_builtin.py::TestMinimalPersonaShips::test_minimal_passes_schema_validation`
- `test_persona_builtin.py::TestPasseleweIfPresent::test_passelewe_covers_all_agent_roles`
- `test_persona_builtin.py::TestPasseleweIfPresent::test_passelewe_passes_schema`
- `test_persona_defaults.py::TestDefaultPersona::test_default_toml_has_full_display_names`
- `test_persona_defaults.py::TestMinimalPersona::test_minimal_toml_has_full_display_names`
- `test_persona_defaults.py::TestPasseleweAsOptionalExample::test_passelewe_toml_has_full_display_names`
- `test_persona_toml_schema.py::TestDisplayNamesCoverage::test_display_name_value_non_string_rejected` *(after §D4 test fix)*
- `test_persona_toml_schema.py::TestDisplayNamesCoverage::test_persona_missing_single_role_raises_with_role_name[analyst]` *(after §D4 test fix)*
- `test_persona_toml_schema.py::TestDisplayNamesCoverage::test_unknown_role_in_display_names_rejected` *(after §D4 test fix)*
- `test_persona_toml_schema.py::TestDisplayNamesCoverage::test_valid_full_coverage_passes` *(after §D4 test fix)*

The 16th RC1 failure — `test_persona_rename_sweep.py::test_canonical_roles_match_agent_role_enum` — is addressed by the Sage edit to that test file (see §D2-adjacent note below).

---

## §D2 — `test_roles.py` adaptation (Sage edit)

**Failure:** `test_all_eight_roles_exist` asserts `len(AgentRole) == 8` but
AgentRole now has 9 members.

**Candidate shapes:**
1. **Dynamic lower-bound** — `assert len(AgentRole) >= 8` plus an explicit
   `test_analyst_exists`. Forever-stable but weakens the tripwire: a
   regression removing a role wouldn't fire this test (it would only fire
   the missing-member test).
2. **Exact rename + explicit member test** — rename the test to
   `test_all_nine_roles_exist` with `len(AgentRole) == 9` AND add a
   `test_analyst` per-member test mirroring the existing 8.

**Verdict:** Shape (2). Exact count is the correct tripwire shape — the
test's purpose is "if AgentRole's cardinality changes, fail loudly so the
operator files a ticket to update the map." Shape (1) hides the signal.
When role #10 lands, the next Sage renames to `test_all_ten_roles_exist`;
that's a one-line edit and the tripwire stays sharp.

**Mechanical edits to `tests/unit/test_roles.py`:**
- Rename `test_all_eight_roles_exist` → `test_all_nine_roles_exist`.
- Update the assertion from `assert len(AgentRole) == 8` → `assert len(AgentRole) == 9`.
- Append `test_analyst` after `test_synthesizer`, mirroring the existing
  per-member shape: `assert AgentRole.ANALYST == "analyst"`.

The existing `test_values_are_lowercase_strings`,
`test_serialization_roundtrip`, `test_grep_friendly`, and every test in
`TestNamingVocabulary` iterates over `AgentRole` directly — they pick up
the new member for free.

### §D2-adjacent — `test_persona_rename_sweep.py` tripwire

`test_canonical_roles_match_agent_role_enum` asserts enum values match a
module-level hardcoded `_CANONICAL_ROLES` frozenset of 8 names. This is a
stale tripwire: its docstring literally says "If AgentRole evolves, this
fires first so we know the TOML assertions below are checking the right
vocabulary." It fired. The correct response is to update the canonical set.

The same `_CANONICAL_ROLES` frozenset is also consumed by five parametrized
TOML-shape tests (lines ~310–349). Those tests currently PASS (builtins
cover all 8 hardcoded roles). If we add `analyst` to the frozenset but
Warrior does not yet update TOMLs, those tests would move from GREEN to RED
and get added to Warrior's fix list. Since Warrior is about to add
`analyst` to all three TOMLs per §D1, the net effect after Warrior's commit
is GREEN for all six.

**Verdict:** Update `_CANONICAL_ROLES` to include `"analyst"`. Keep it a
hardcoded frozenset (not dynamic-from-enum) — the whole point of this
sweep file is to be a separate source of truth that cross-checks the enum.
Making it dynamic would defeat the purpose of the cross-check.

**Side effect (intentional, Warrior-fixable):** the same
`_CANONICAL_ROLES` frozenset is consumed by two parametrized suites —
`TestBuiltinPersonaTomlShape::test_each_builtin_display_names_covers_all_roles`
and `...values_are_strings` — each parametrized across the three shipped
built-ins. After this edit they will RED on all three personas × 2 suites
= 6 additional RED tests, because the built-in TOMLs still carry 8
entries. The Warrior's §D1 TOML edits flip all six back to GREEN. This
is the forever-guard doing its job: canonical set and TOMLs must march
together, or at least one tripwire fires.

**Mechanical edit to `tests/unit/test_persona_rename_sweep.py`:** append
`"analyst",` to the `_CANONICAL_ROLES` frozenset literal at line ~51.

---

## §D3 — `test_config.py` rename-sweep (Sage edit, 2 lines)

**Failures:**
- `TestPipelineConfig::test_default_construction` line 81: `assert p.persona == "passelewe"`.
- `TestBonfireSettingsTomlLoading::test_toml_partial_merge_preserves_defaults` line 246: `assert s.bonfire.persona == "passelewe"`.

**Root cause:** BON-345 D4 updated `src/bonfire/models/config.py:46` from
`persona: str = "passelewe"` → `persona: str = "default"`. The BON-345
sweep-added tests (`test_persona_rename_sweep.py::TestConfigPersonaDefault`)
enforce this at the source-file level, but these two pre-existing
`test_config.py` tests were not in BON-345's scope and still assert the
old literal.

**Verdict:** Mechanical rename. `"passelewe"` → `"default"` on both lines.

---

## §D4 — RC3 disposition (Sage edit, test helpers only)

**Investigation carried out:**
1. Read `src/bonfire/persona/loader.py` in full. The `_validate_raw`
   method at lines 212–283 implements:
   - Warn-on-unknown-top-level-table (lines 219–228) — matches `TestExtrasPolicy` contract.
   - Strict `version: str` type check via the `_REQUIRED_PERSONA_FIELDS` loop (lines 234–246) — matches `TestVersionField` contract.
2. The loader's behavior is correct against the BON-345 D1/D2 Warrior
   contract. No src change is required.
3. Traced each RC3 failure by reading the test body and comparing to the
   loader's execution order:

| Test | Builds TOML with... | Loader order | Why it fails |
|---|---|---|---|
| `test_unknown_toplevel_table_accepted` | Valid `[persona]` + `_FULL_DISPLAY_NAMES_BLOCK` (8 roles only) + `[metadata]` extra | (a) warn on `[metadata]` — fine, then (b) check `[display_names]` coverage | Misses `analyst` → raises "missing role: analyst" |
| `test_unknown_toplevel_table_logs_warning` | Same as above | Same | Same |
| `test_multiple_unknown_toplevel_tables_accepted` | Same + `[notes]` | Same | Same |
| `test_version_must_be_string` | `_persona_toml(version="2.1.0")` → 8-role block | Type check passes, then coverage check | Misses `analyst` → raises |
| `test_version_any_string_accepted` | `_persona_toml(version="calver-2026.04")` → 8-role block | Same | Same |

**All five failures trace to the same helper defect:** the module-level
constant `_FULL_DISPLAY_NAMES_BLOCK` (lines 52–62) and the per-role
mapping dict inside `_persona_toml_missing_role` (lines 106–115) hardcode
8 roles. After BON-342 D1 widened `AgentRole` to 9, these helpers no
longer produce valid TOML for the "positive path" tests.

**Verdict:** PURE TEST-CONTRACT BUG. The loader is correct. Fix the
helpers; no src changes.

**Mechanical edits to `tests/unit/test_persona_toml_schema.py`:**

1. Append `analyst = "Analysis Agent"` to `_FULL_DISPLAY_NAMES_BLOCK` at
   line ~61 (inside the triple-quoted string, before the closing `"""`).
   Using the professional name mirrors the default/minimal builtin shape,
   preserves the "neutral test persona" intent of the fixture helper, and
   keeps the adversarial block compatible with any future parametrized
   extension.

2. Append `AgentRole.ANALYST: "Analysis Agent",` to the `mapping` dict
   inside `_persona_toml_missing_role` at lines ~106–115. Same rationale.

3. **No test bodies or assertions change.** The parametrized
   `test_persona_missing_single_role_raises_with_role_name[analyst]`
   case (currently in the RC1 list) picks up the new mapping entry and
   flips GREEN because the helper now produces a TOML with 9-role
   coverage minus `analyst`, and the loader raises "missing role: analyst".

4. The `test_display_name_value_non_string_rejected` test at line ~404
   constructs its own inline `[display_names]` block via
   `_persona_toml(include_display_names=False) + "..."`. That block
   also only has 8 roles. Append `analyst = "Analysis Agent"\n` to the
   constructed string so the only violation the loader sees is
   `researcher = 42`.

5. The `test_unknown_role_in_display_names_rejected` test at line ~386
   uses `_persona_toml().replace(...)` — once §D4 edit 1 extends
   `_FULL_DISPLAY_NAMES_BLOCK` to 9 roles, the replace still works and
   the only violation is `bogus_role = "Clown"`.

### After §D4, RC3 resolution matrix

| Test | After Sage edit | Warrior action needed? |
|---|---|---|
| `test_unknown_toplevel_table_accepted` | GREEN | No |
| `test_unknown_toplevel_table_logs_warning` | GREEN | No |
| `test_multiple_unknown_toplevel_tables_accepted` | GREEN | No |
| `test_version_must_be_string` | GREEN | No |
| `test_version_any_string_accepted` | GREEN | No |

RC3 is fully owned by the Sage edit. The Warrior touches no source for RC3.

---

## §D5 — NEW dynamic forever-guard test

**Name:** `tests/unit/test_persona_builtins_dynamic_role_coverage.py`
**Purpose:** Prove that EVERY shipped built-in persona TOML covers EVERY
AgentRole member at test time, with the enum as the runtime source of
truth. This is the forever-guard that prevents a future "AgentRole widened
in one wave, TOMLs lagged in another" desync from reaching a merge.

**Shape:**

- Reads `AgentRole` at collection time (not module-import time — both are
  fine for enum since it's static, but reads-enum-at-test-time matches the
  pattern advertised in the dispatch brief).
- Iterates every persona directory under
  `src/bonfire/persona/builtins/` that has a `persona.toml`.
- For each `(persona_dir, agent_role)` pair, asserts `role.value` is a
  key in `[display_names]` with a non-empty string value.
- Uses a parametrize over (persona, role) so the failure message names
  exactly which persona is missing which role.

**Why a new file and not a new test in an existing file:**

- `test_persona_builtin.py` already exercises this via
  `test_every_shipped_builtin_passes_schema`, but only through the
  loader's `validate()` method. If the loader's validator ever drifts
  (e.g. becomes lenient on role coverage), the builtin's gap hides.
- This new test bypasses the loader entirely, reading the TOML directly.
  Two independent paths to the same invariant = tripwire doubled up.

**Mechanical content:** see Write output; single-file module with one
parametrized test and one helper discovering shipped built-ins.

**Expected state:**
- On Sage commit (src untouched, TOMLs untouched): FAILS for all three
  built-ins × `analyst` (3 parametrize cases fail).
- After Warrior commits the 3 TOML updates per §D1: GREEN for all
  cases.

---

## §D6 — Out of scope

1. **Src files.** Not touched. Loader is correct against the merged
   contract; AgentRole enum is correct; Config default is correct.
2. **The 3 builtin TOMLs.** Read-only for this ticket — they are the
   Warrior's scope per the dispatch brief (§Part C "Do NOT touch the 3
   builtin TOMLs").
3. **BON-342 xfails (§D7 stacked markers) and BON-345 xfails.** All
   preserved untouched. This wave does not re-open them.
4. **The pipeline-level merge-preflight check.** Tracked separately as
   BON-519 (Operation Splatter). This reconciliation does not prevent the
   class of failure; it cleans up after it.
5. **Additional dynamic guards beyond §D5.** A mirror test that reads
   TOML `[display_names]` keys and cross-references `ROLE_DISPLAY` (i.e.
   "every role used by any builtin has an entry in the naming vocabulary")
   is a good idea but belongs to a separate ticket — out of scope for
   this reconciliation, which is already carrying six files of diff.

---

## Warrior Contract

**Scope:** Source-side changes to flip the remaining RED tests GREEN.

### Files Warrior must edit

1. **`src/bonfire/persona/builtins/default/persona.toml`**
   - Append one line at the end of the `[display_names]` table:
     `analyst = "Analysis Agent"`
   - Do not reorder existing entries.
   - Do not change `[persona]` block or any other content.

2. **`src/bonfire/persona/builtins/minimal/persona.toml`**
   - Append one line at the end of `[display_names]`:
     `analyst = "Analysis Agent"`
   - Same discipline as default.

3. **`src/bonfire/persona/builtins/passelewe/persona.toml`**
   - Append one line at the end of `[display_names]`:
     `analyst = "Architect"`
   - Note: gamified name, not professional. Passelewe is the gamified voice.

### No other source changes

- Warrior does NOT touch `src/bonfire/persona/loader.py` (RC3 is a test
  helper defect, not a src gap — see §D4).
- Warrior does NOT touch `src/bonfire/agent/roles.py` (BON-342 D1
  already landed correctly).
- Warrior does NOT touch `src/bonfire/models/config.py` (BON-345 D4
  already landed correctly).
- Warrior does NOT touch `src/bonfire/naming.py` (BON-342 D1 already
  landed the `ROLE_DISPLAY["analyst"]` entry).

### Scoped ruff

Warrior runs scoped ruff on the 3 TOML files only? TOMLs don't ruff —
skip. Run `ruff check --fix` + `ruff format` on the commit file list:
result is no-op for TOML files. Verify full tree passes `ruff check`
before commit.

### Tests Warrior's 3-TOML edit must flip GREEN

- 10 RC1 tests from `test_persona_builtin.py` / `test_persona_defaults.py` (see §D1 list).
- 3 new cases from `test_persona_builtins_dynamic_role_coverage.py::TestDynamicRoleCoverage::test_builtin_has_display_name_for_role` (one per persona × analyst).
- 6 parametrized cases from `test_persona_rename_sweep.py::TestBuiltinPersonaTomlShape` that Sage's `_CANONICAL_ROLES` update newly RED's (see §D2-adjacent side-effect note).
- 4 RC1 tests in `test_persona_toml_schema.py::TestDisplayNamesCoverage` that flip GREEN via Sage's §D4 test-helper edits *AND* the persona-missing-role[analyst] parametrize case flipping GREEN.

Total: Warrior's single 3-TOML change flips ~20 tests from RED to GREEN.

### Expected pytest counts after Warrior GREEN

- **Full suite** `pytest tests/`: **0 failures**, 0 errors.
- **xfails:** all BON-342 §D7 markers preserved (9 architect decorations,
  1 wizard decoration). All BON-345 xfails preserved.
- **xpasses:** any xpass that was present before this wave remains. No
  new xpasses introduced.

### Verification

```
/home/ishtar/Projects/bonfire-public/.venv/bin/pytest tests/ --no-header -q
```

Must show `N passed` with N matching the pre-reconciliation passing-plus-23 total
(baseline was 23 failing out of ~N+23 total — post-Warrior, all 23 should
move to passed).

### Commit message shape

```
bon-520-warrior: add analyst to 3 builtin persona TOMLs
```

No src edits beyond the 3 TOMLs. Single commit on branch
`antawari/bon-520-warrior` (worktree `/home/ishtar/Projects/bonfire-public/.claude/worktrees/bon-520-warrior`, to be created by dispatcher).

---

## Summary

| Layer | Files touched by Sage | Files touched by Warrior |
|---|---|---|
| Test contract | `test_roles.py`, `test_config.py`, `test_persona_toml_schema.py`, `test_persona_rename_sweep.py` | — |
| Test additions | `test_persona_builtins_dynamic_role_coverage.py` (new) | — |
| Source | — | `default/persona.toml`, `minimal/persona.toml`, `passelewe/persona.toml` |
| Docs | `docs/audit/sage-decisions/bon-520-cross-wave-reconciliation.md` (this file) | — |

End-state: 23 failures resolved. Forever-guard in place. Two independent
test paths (loader + direct TOML read) guarantee the next AgentRole widening
cannot land with lagging TOMLs in a sibling wave without at least one
tripwire firing in pre-merge.
