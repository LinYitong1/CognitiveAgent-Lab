# M2-A — Reference Project Analysis (source-level)

- **Method**: all four repositories were shallow-cloned read-only to a scratch directory on 2026-10-21 and analysed at **source-code level** (no code copied into this project; nothing executed from them). This extends the earlier README-level survey (`docs/research/game-prototype-survey.md`, 2026-10-20) with implementation facts.
- **Licences re-confirmed**: OpenGame Apache-2.0 · game-studio-ai Apache-2.0 · WebGameTemplateForAgents MIT · gamedev-agent MIT. Zero code adoption planned; only design ideas, with attribution.

---

## 1. gamedev-agent (rsasaki0109) — closest prior art for our M2 route

**Pipeline (source: `src/agent/`)**: `planner.ts` (LLM + Zod-validated GameSpec) → `codegen.ts` (deterministic template output) → `verifier.ts` (5 stages) → `repair-loop.ts` (bounded, error-hash dedup) → optional deploy.

**Source-level findings**:

- **GameSpec is deliberately tiny and bounded** (`schemas.ts`): ~30 fields, a **single archetype literal** (`archetype: z.literal("top-down-collect")`), bounded strings (`max(60)`, `max(240)`, `max(400)`), bounded numerics (`speed: min(120).max(360)`), and **fixed world dimensions as literals** (`viewport 960×540`, `world 16×9×60`, `z.literal(…)`). The schema itself is the creativity fence.
- **Codegen is a thin deterministic wrapper** (`codegen.ts`): the only generated artifacts are (a) `game-spec.ts` = the validated JSON embedded as a `const`, (b) `GameScene.ts` = a 10-line subclass of the hand-written `BaseTopDownScene`, (c) a fixed asset manifest. **All game logic lives in the hand-written template core** — the LLM never authors logic-bearing code.
- **Verifier is layered and evidence-producing** (`verifier.ts:100–175`): format → typecheck → unit → build → browser (Playwright, only if build passed). Each stage's stdout/stderr is archived as an artifact; browser checks include console errors, page errors, failed requests, layout stats, game-state probes and **functional probes (`movement / win / restart / lose`)**; the report carries a numeric score and a **`errorSetSha`** (SHA of the sorted error set) so the repair loop can detect "same failure as last round".
- **Repair loop**: deterministic fixes first, LLM repair restricted to whitelisted paths, ≤ 3 rounds, best-version rollback.

**Adopt**: bounded-by-design spec fields (we already share this philosophy in GameSpec v1 — keep it in v2); evidence-archived verification stages; error-set hashing for stall detection (analogous to our `error_code:path` stalled protocol); the "one archetype first" MVP discipline.
**Adapt**: their single hardcoded archetype becomes our **registry of runtime layouts** (v1 already has `canvas-center|rows`; v2 adds an exploration layout) — same narrowness, but pluggable rather than schema-literal.
**Avoid**: none major; note it targets one casual game archetype with no experimental-control concept — our differentiator is exactly the mapping layer they do not need.

## 2. WebGameTemplateForAgents (ludenio) — runtime discipline and review-guard semantics

**Source-level findings** (`ARCHITECTURE.md`, `DESIGN_RULES.md`, `src/store/store.js`, `tests/`):

- **"Mutable UDF + deterministic lockstep"**: one mutable state object; every discrete change is a `store.dispatch(type, payload)` recorded in `store.history`; handlers mutate state; **continuous per-tick simulation is explicitly NOT logged**. Replay = re-run history. This is a clean answer to our "measurement vs. presentation events" split: discrete logged events ↔ measurement-adjacent actions; unlogged continuous ticks ↔ animation.
- **file:// compatibility rules** (identical to our B2 contract): no ES modules, no bundlers, no CDN/npm, IIFE + `window` exports, deterministic script load order.
- **Design review as a guard protocol** (`DESIGN_RULES.md:14–40`): a **completeness gate** ("insufficient data to verify — request UI screenshots, UX flows, state diagrams before approving") and a **violation protocol** (stop; name the violated principle; explain the player consequence; **propose 3 compliant alternatives**; wait for a decision).
- In-repo test page (`tests/index.html`, `file://`-openable, 28 store tests) — the same zero-dependency self-check pattern our renderer already uses (`selfCheck()`).

**Adopt**: the two-class event model (logged discrete vs. unlogged continuous) as the backbone of our event-log v2; the guard protocol wording as the model for our **researcher approval checkpoints** (a checkpoint that cannot be verified from supplied artifacts must block with a named reason and concrete remediation options, never wave through).
**Avoid**: its mutable-global-state style is fine for a template but our renderer keeps the pure-function assembly + embedded-data model; no change needed there.

## 3. game-studio-ai (miharbi) — orchestration semantics (and why 28 agents is not for us)

**Source-level findings** (`agents/tier1–3`, `config/validators.yaml`, `plans/templates/*.yaml`, `tests/`):

- **28 agents in 3 tiers** (3 directors / 8 leads / 19 specialists) are **markdown role prompts**, not separate models. Orchestration is a **YAML plan DAG**: steps with `depends_on` and `gate: auto | conditional | human_review`.
- **User-configurable output validators** (`validators.yaml`): each validator = a `source_spec` JSON (with `_schema` blocks whitelisting enum values) + `on_fail: warn|block`. All top-level spec keys are required; enum violations block. This is schema-driven validation exactly like our `validate_experiment`/`validate_game`, but user-extensible.
- **Two-state artifact flow**: `output/pending/` → human approval → `output/approved/`. A concrete, filesystem-level approval mechanism.
- **Tests are fully offline** (fixtures, no LLM calls) — same discipline as our FakeLLM gate.
- It **produces design documents and engine-ready specs, not playable games**; targets Godot/Unity/UE via config.

**Adopt**: the `pending → approved` two-state artifact convention for researcher checkpoints (maps naturally onto our sandbox + a `review/` prefix); `on_fail: warn|block` semantics for future mapping-layer warnings (e.g., "narrative references unknown room" warns, "trial mutation attempt" blocks).
**Adapt**: multi-agent tiers are a **non-goal** for us (project boundary: single AgentLoop; PA-14 shows even one 7B LLM is our budget). What we take is the **gate vocabulary**: M2 stages get `auto` gates (deterministic verification) and `human_review` gates (researcher approval), executed as stages of one loop.
**Avoid**: 28-role orchestration, cross-model routing, engine-target sprawl.

## 4. OpenGame (silentlamp fork of leigest519/OpenGame) — the route we already rejected, re-examined for salvageable parts

**Source-level findings** (`agent-test/`, `packages/core/src/skills/`):

- It is a **fork of a Gemini-CLI-class agent runtime** (1,137 tracked files; packages/core/cli/sdk) — a full CLI product, far beyond a lab tool.
- **Template Skill** (`agent-test/template-skill/`): a Phaser 3 + Vite + TS **meta-template** with hand-written scene classes (`TitleScreen`, `Preloader`, `UIScene`, `PauseUIScene`, `GameOverUIScene`, `VictoryUIScene`, a `StateMachine.ts`). The agent edits code inside this scaffold.
- **Asset protocol** (`docs/asset_protocol.md`): a multimodal generation tool with **strict union-type parameter shapes** (background/tileset/animation/image/audio), fixed output sizes, explicit batching rules ("split >N assets into two calls to avoid timeout"), and harsh failure notes ("using `x` instead of `*` causes API errors"). The protocol doc is essentially a **hardened interface spec distilled from observed failures**.
- **Debug protocol** (`docs/debug_protocol.md`): pre-build checklists for recurring Phaser failure classes — animation-key chain integrity (`asset-pack.json → animations.json → animKeys`), config-key alignment, tilemap layer case-sensitivity, TS import rules. **Verified failure knowledge encoded as checklist protocols** that the agent must run before building.
- Bench: headless browser + VLM review across build health / visual usability / intent alignment.

**Adopt (ideas only)**: the **protocol-as-checklist** pattern for our future Game Tester stage — every recurring runtime failure class discovered during M2 playtesting becomes a self-check-page assertion (we already do this with `selfCheck()`; the lesson is to grow it systematically), and later a Playwright probe list. Strictly-shaped asset interfaces are a good model **if** we ever add generated media (explicitly out of MVP scope).
**Avoid (confirmed)**: LLM free-generates-the-whole-game (unverifiable experimental control), 27B-class model dependency, VLM-in-the-loop acceptance, CLI-product scope.

## 5. Cross-project synthesis → what M2 adopts, adappts, avoids

| Theme | Decision | Source |
|---|---|---|
| LLM writes specs, deterministic code builds the artifact | **Adopt** (already our route; re-validated) | gamedev-agent |
| Bounded, literal-heavy schemas as the creativity fence | **Adopt** in GameSpec v2 | gamedev-agent |
| Evidence-archived, layered verification; error-set hashing | **Adopt** for the new reconciliation verifier | gamedev-agent |
| Logged-discrete vs. unlogged-continuous event split | **Adopt** as event-log v2 backbone | WebGameTemplate |
| Guard-style approval (completeness gate, named violations, 3 alternatives) | **Adopt** as researcher-checkpoint semantics | WebGameTemplate |
| `pending → approved` artifact states; `warn|block` validation outcomes | **Adapt** (filesystem convention on our sandbox) | game-studio-ai |
| Plan-DAG gates (`auto` / `human_review`) | **Adapt** as **stage gates inside the single AgentLoop**, not multi-agent orchestration | game-studio-ai |
| Multi-agent role hierarchies; cross-model routing | **Avoid** (boundary + PA-14 budget) | game-studio-ai |
| LLM free-form game codegen; VLM review; product-scale CLI | **Avoid** (prior survey decision, re-confirmed at source level) | OpenGame |
| Failure-knowledge-as-protocol checklists | **Adopt** as growing self-check assertions | OpenGame |
| Generated multimodal assets | **Avoid for MVP**; revisit post-M2 | OpenGame |

**No multi-agent architecture is required.** Every adopted mechanism is executable as tools + stage conventions inside the existing single `AgentLoop`.
