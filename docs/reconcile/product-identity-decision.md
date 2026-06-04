# Product-identity decision: opinion-package vs cadre pivot

Status: decision brief for review. No option is selected here — this document
presents the evidence so the call can be made deliberately.

Lineage: this brief builds on the v1 reconcile trunk that already carries the
shipped contract plus the Elegance-Law error taxonomy (merged in #190). It is
the topic-by-topic companion to the staged-replay plan in #191.

## 1. The question

The shipped product on PyPI (`bonfire-ai` 1.0.1) presents Bonfire as an
**opinion-package**: a CLI with `install-skill`, a bundled `SKILL.md`, an
importable ISM integrations package, file-safety primitives, and a small
security cluster (a deny-by-default project-settings trust gate, path-traversal
validators on envelope and session ids, and traceback redaction in the dispatch
backend). The release trunk already carries exactly this surface. Separately, a
documented direction from mid-May pivots Bonfire toward a **cadre** product: a
CLI with `install-agents`/`build-agents`/`list-agents`/`uninstall-agents`, a
cadre package, role metadata, and seven bundled role prompts. That cadre work
lives on `main`. The question is: when we build the next release off the trunk,
does Bonfire present as the opinion-package (keep what shipped), as the cadre
product (replay `main`), or as both surfaces coexisting — and can we even have
both without breaking the people already running 1.0.1?

## 2. Comparison: A vs B-naive vs B-union

"A" is the trunk as it stands today (the shipped opinion-package). "B-naive" is
replaying `main` wholesale onto the trunk. "B-union" adds the cadre commands on
top of the trunk while keeping the opinion-package surface. All three keep the
nine shared commands (`init`, `scan`, `status`, `resume`, `handoff`, `persona`,
`cost`) and the entry point (`bonfire = bonfire.cli:app`) unchanged.

| Axis | A (trunk / shipped) | B-naive (replay main) | B-union (trunk + cadre) |
|---|---|---|---|
| CLI: `install-skill` | present | **removed** | present (kept) |
| CLI: `install-agents` / `build-agents` / `list-agents` / `uninstall-agents` | absent | added (4) | added (4) |
| Files changed vs trunk | baseline | 25 files, +1104 / −2062 | 13 files, +1134 / −0 |
| Net LOC | baseline | removes ~1446 (opinion surface), adds ~1040 (cadre) | adds ~1040 (cadre), removes 0 |
| Importable modules | `integrations`, `_safe_read`, `_safe_write`, `cli.commands.install_skill`, `skill` (SKILL.md payload) | all of those **removed**; `cadre` + `agent.role_metadata` added | all opinion modules kept; `cadre` + `agent.role_metadata` added |
| Security surface | trust gate + envelope-id validator + session-id validator + traceback redaction — all present | **all four removed** | all four kept |
| Packaging / wheel | bundles `skill/*.md` + `integrations/builtins/*.ism.md` | drops skill + ism bundles, adds prompts glob | keeps skill + ism bundles, **adds** prompts glob |
| Version / changelog | 1.0.1, Production/Stable; `[1.0.1]`/`[1.0.0]` entries intact; publish-action pinned | regresses to 0.1.0a2, Alpha; loses `[1.0.1]`/`[1.0.0]`; publish-action re-pinned to a different SHA | stays 1.0.1, Production/Stable; changelog + pin intact |
| Reversibility | maximal (no-op on shipped contract) | poor (every removed surface is a separate breaking restore) | good (additive minor release; cadre can be deprecated later without touching A) |
| Buildable on trunk now? | yes (it is the trunk) | yes, but dominated | **yes — measured: builds, imports, lint-clean, tests green** |

### What each option means for an existing 1.0.1 user

- **A** changes nothing. `pip install bonfire-ai==1.0.1` behaves exactly as it
  does today. The cost is that the documented cadre direction does not reach
  users until it is merged separately.
- **B-naive** is a multi-axis breaking change. `bonfire install-skill` becomes
  "No such command". `import bonfire.integrations` (and its 11 public names),
  `import bonfire._safe_read`, `import bonfire._safe_write`, and
  `from bonfire.cli.commands import install_skill` all raise `ModuleNotFoundError`.
  The bundled skill and ISM payloads disappear from the wheel. The version goes
  **backwards** (1.0.1 → 0.1.0a2), which breaks pip's upgrade ordering. And the
  whole security cluster is silently deleted — see the smoking gun below.
- **B-union** breaks nothing. Everything a 1.0.1 user relies on still resolves,
  the security gates stay armed, the version stays at or above 1.0.1, and the
  user gains four new commands plus the importable `cadre` and `role_metadata`
  modules and seven bundled role prompts.

### The security smoking gun (the most material B-naive loss)

On the trunk, the dispatch backend resolves project settings through a
deny-by-default gate: for a foreign or un-opted-in repo it returns an empty
setting-source list, so a cloned third-party repo's `CLAUDE.md` and
`.claude/settings.json` are **not** auto-injected into the dispatched agent's
system prompt unless the operator explicitly opts in. On `main` the backend
hardcodes the project setting-source unconditionally for any working directory —
re-opening prompt/settings injection from attacker-controlled repo content.
B-naive would ship that regression for free, on top of dropping the
envelope-id and session-id path-traversal validators and the traceback
redaction (which otherwise keeps raw local-frame data out of the persisted
JSONL). This is why B-naive is described as **dominated**: it pays a ~1446-LOC
security-and-integration surface (plus a version regression) to buy a ~1040-LOC
cadre surface that B-union delivers for zero deletions.

## 3. The spike (real numbers)

A spike branch (`spike/product-identity-union`, pushed at `612a938`, no PR per
the never-merge rule) grafted the cadre surface onto the trunk and measured it.

- **Does it build?** Yes. `pip install -e .[dev]` exits 0; the import probe
  `import bonfire.cadre, bonfire.cli.commands.install_agents,
  bonfire.cli.commands.build_agents, bonfire.agent.role_metadata` prints
  `import OK` and exits 0.
- **Is it clean?** Yes. `ruff check` on the grafted files → "All checks
  passed!" (exit 0); `ruff format --check` → "5 files already formatted"
  (exit 0); ruff version is the trunk's pin (0.15.13).
- **Do the tests pass?** Yes. The trunk's existing CLI/skill suite runs
  unbroken under the graft: 266 passed (5132 deselected) for
  `cli or cadre or install or agents`; 368 passed (1 xpassed) for the
  app/help/command tests; 12 passed for the `install_skill`/`skill` tests
  (the A surface is un-regressed).
- **Does it actually work?** Functional smokes (run on the spike branch,
  where the cadre verbs exist): the spike's `build-agents` wrote all seven
  role files (proving prompt loading through `importlib.resources` plus the
  packaging glob); `install-agents --dry-run` enumerated the seven
  `bonfire-*` agents (proving role metadata + the cadre contract).
- **Diff shape:** 13 files changed, +1134 / −0 — purely additive, the exact
  inverse of B-naive's −2062.

### Command list after the union graft

`bonfire --help` lists **both** surfaces:

```
install-skill   (KEPT — opinion-package surface intact)
install-agents
uninstall-agents
list-agents
build-agents
init
scan
status
resume
handoff
persona
cost
```

### One honest caveat on test coverage

The 266 green tests are the trunk's existing suite passing unchanged under the
graft — they prove the graft does not break A. The cadre modules arrived on
`main` **without their own unit tests**, so cadre behaviour here is proven by
the import probe and the two functional smokes, not by ported tests. A real
pivot landing should also port `main`'s cadre tests (if any) or write them.

## 4. Where this lands in the reconcile

The full reconcile plan catalogues the product-identity / CLI-app two-way-merge
as one of its later topics, after the retrieval-and-engine chain. That ordering
is a **sequencing convenience**, not a hard dependency: it is easiest to reason
about the final `app.py` merge once every other topic's `app.py` edits have
landed. The cadre code itself does **not** depend on any of those topics.

The import-graph evidence is the proof. The grafted cadre modules import only:
`bonfire.__version__` (already on the trunk); their own three grafted modules
(`role_metadata`, `cadre`, `build_agents`); and, transitively, nothing beyond
the standard library (`typing.TypedDict`, `importlib.resources`,
`collections.abc`, `json`, `datetime`, `pathlib`). There are no references to
the engine, the protocol-superset types, retrieval, or any later-topic symbol.
Two structural facts make the graft conflict-free: the trunk had no
`role_metadata.py` (pure add, no overwrite), and the trunk's `agent/__init__.py`
re-exports only roles and tiers (so the add doesn't collide).

**Shortest path to a landable pivot:** cherry the union spike's additive delta
straight onto the trunk as its own standalone topic. It is +1134 / −0,
conflict-free, lint-clean, and test-green, and the only `app.py` change it makes
is appending four lazy command shims after the existing `install-skill` shim.
The one ordering caution: whoever lands this must keep the trunk's lazy-loading
group pattern (which the spike does) rather than `main`'s eager command
registration — eager registration is what couples `main`'s `app.py` to
import-time availability of the heavy command modules, and is the seam the
reconcile wants resolved last. So the cadre topic can land any time; the only
thing to serialize is the final `app.py` reconciliation if other in-flight
topics also edit `app.py`.

## 5. Open questions (only the product owner can answer)

The build constraint — *can we keep the opinion-package surface and add cadre?* —
is answered: **yes** (B-union, measured). What remains is a product-identity
call, not a build call:

1. **One surface or two?** B-union ships a CLI carrying both `install-skill`
   (writes to `~/.claude/skills/bonfire/`) and `install-agents` (writes to
   `~/.claude/agents/bonfire/`). Is "Bonfire installs a skill **and** a cadre of
   agents" the intended product story, or should the product present a single
   install verb?

2. **If two surfaces, what is the relationship between them?** Are skill and
   cadre peers, or is one the headline and the other a power-user mode? This
   shapes help text, docs, and onboarding regardless of the code.

3. **Does the documented mid-May cadre pivot still stand?** If the intent was to
   *replace* the opinion-package with the cadre (the spirit of B-naive, minus
   its accidental security/packaging losses), that is a deliberate breaking
   change for 1.0.1 users and should ship as a clean major bump with the
   security cluster preserved — explicitly, not by replaying `main`.

4. **Version line.** B-union is a 1.1.0-class additive minor release. Is shipping
   cadre as a minor (additive, no breakage) the desired cadence, or is a major
   intended to signal a product repositioning?

5. **Should `main`'s reintroduced global `--persona` root flag be carried?** The
   trunk deliberately pruned it; `main` re-adds it. B-union should **not** carry
   it unless the pivot wants that override surface back.
