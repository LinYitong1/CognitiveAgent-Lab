# 06 — Research Data Layer: Future Contract Requirements (Design Only)

New in the 2026-10-24 design revision. This document lists the data-contract requirements a
**future data-collection layer** must satisfy for formal scientific use. It is a
requirements specification, not an implementation plan: **nothing here is implemented**,
nothing here modifies ExperimentSpec, and no field below may leak into the spec or bundle.

Position (unchanged from 03 T2-4 / 05 Q8): **a bundle is one within-subject condition set by
design.** Participants, sessions, and data receipt live in a separate collection layer that
*references* bundles by fingerprint — it must never alter generation, trials, or answers.

Status taxonomy: **[VERIFIED]** established fact about current code · **[DESIGN]** contract
requirement proposed here · **[NEEDS-TEST]** to be proven when implemented.

---

## 1. What exists today (baseline facts)

- Event log per session, in-page JSON array, **manual download only**; no network
  persistence [VERIFIED: both engines' end screens].
- Every event carries `t_epoch_ms = Date.now()` — a client wall-clock timestamp
  [VERIFIED: `logEvent` / `logGame` / `logMeasurement`]. *(Correction to audit doc 01 §6 and
  05 Q8c, which said "no absolute timestamps, rt_ms only": absolute client timestamps DO
  exist per event. What is missing is **trusted** time — see §4.)*
- `rt_ms` is `performance.now()`-relative, anchored at stimulus/window onset [VERIFIED].
- Measurement events carry `trial_index`, `block`, `conditions`, `response_name`, `value`,
  `correct`, `rt_ms`; explore adds `channel` separation [VERIFIED].
- Offline reconciliation machinery exists: `verify_game_events`-style expectations and the
  engines' runtime self-checks (one response event per trial per response; cursor order)
  [VERIFIED].
- Browser `setTimeout` timing is approximate and documented everywhere as not
  research-grade [VERIFIED].

## 2. Participant contract [DESIGN]

| Field | Requirement |
|---|---|
| `participant_id` | opaque string, server-issued; never derived from PII |
| `group` | between-subject group label (assignment method must be recorded: e.g. seed-based counterbalance) |
| `metadata` | free-form JSON (demographics etc.), opt-in, size-bounded |
| `created_at` | server time |

Musts: group assignment is **server-side and auditable** (client-side assignment is
tamperable); participant records are separable from session data for deletion/consent
requests. Between-subject designs are impossible today precisely because this contract
does not exist [VERIFIED gap, 03 T2-4].

## 3. Session contract [DESIGN]

| Field | Requirement |
|---|---|
| `session_id` | server-issued, unique per run of a bundle |
| `participant_id` | link to §2 |
| `bundle_sha256`, `trials_fingerprint`, `config_fingerprint` | the exact executed bundle — the reproducibility anchor (the session claims "this participant ran THIS bundle") |
| `game_sha256` | identity of the rendered HTML (GameSpec is embedded in the HTML; pin the artifact) |
| `started_at`, `ended_at` | server-receipt times bracketing the session |
| `environment` | user agent, viewport, input modality (research-grade caveat fields) |
| `status` | `in_progress` / `completed` / `aborted` — enables partial-data policy |

Musts: a session is invalid unless its fingerprints match a bundle the server can verify
(`verify_bundle` exists offline today [VERIFIED]); session resumption after tab close needs
an explicit resume contract (trial cursor at abort point) — the current engines have no
save/resume; a resumed session must log a `resume` marker, never silently splice.

## 4. Response-event envelope and timestamps [DESIGN]

The event schema itself is mostly sufficient for within-subject analysis (accuracy/RT
ANOVAs; 03 T4-2 [VERIFIED]); the envelope additions:

| Item | Requirement |
|---|---|
| `session_id`, `seq` | envelope keys + a **monotonic per-session sequence number** (ordering without trusting client clocks) |
| `schema_version` | versioned event schema from day one (events are the least-frozen surface; today's events have no version field) |
| `t_epoch_ms` (existing) | keep, but reclassified: **client clock, untrusted** — clock skew/timezone/tampering uncontrolled [VERIFIED limitation] |
| server `received_at` | the trusted timestamp, assigned at receipt; analysis uses client `t_epoch_ms` only for *within-session relative* ordering, cross-checked against `seq` |
| phase-onset events | deferred M3-A P2 item (03 T3-3): `phase_start{name, trial_index, t_epoch_ms}` enables timeline reconstruction; do NOT retrofit RT anchoring (already correct) |
| withhold marker | per 04 P2.3: `withheld: true` gated on the response declaring `withhold_option` |

Timing-precision stance (unchanged): browser timestamps are gameplay-grade [VERIFIED
documented]; a native runtime would be a new deployment mode — out of this layer's scope,
must not be silently claimed otherwise (honest-docs rule).

## 5. Persistence / transport contract [DESIGN]

1. **Server-side receipt endpoint**: append-only JSONL per session; the HTML runtime gains
   one optional `POST` flush — the single runtime change this layer requires (and it must
   be absent-by-default so standalone HTML keeps working offline; byte-drift rule applies
   to the non-collecting path).
2. **Force-flush on `pagehide`/`visibilitychange`** — today a closed tab silently discards
   data [VERIFIED].
3. **Idempotent retry**: client retries with `(session_id, seq)`; server deduplicates —
   flaky networks must not duplicate or drop events.
4. **Reconciliation on receipt**: extend the existing self-check/verify logic server-side —
   every trial exactly one response event per response, cursor order, conditions match the
   bundle; mismatched sessions flagged, not silently accepted.
5. **Data-minimization defaults**: no keystroke timing beyond recorded RT, no free-text
   beyond declared text responses (text responses need an explicit PII review before this
   layer ships — noted as a policy gate, not an engineering one).

## 6. Explicit non-goals

- No participant/session/group fields in ExperimentSpec or the bundle (wrong layer;
  polluting the spec breaks the reproducibility contract — a bundle must regenerate
  byte-identically regardless of who runs it).
- No adaptive channel: session data must never feed back into generation (generate-then-
  execute architecture, frozen).
- No claims of research-grade timing (browser limitation stands until a native runtime
  decision).

## 7. Open questions requiring a decision before implementation

- Server technology & hosting posture (the project is currently a fully offline single-file
  pipeline — a receipt endpoint changes the deployment story; this is a product decision,
  not a schema one).
- Consent/IRB workflow integration (electronic consent screen before `session_start`?).
- Between-subject group assignment policy (fixed counterbalance list vs seeded).
- Whether phase-onset events land before or with this layer (independent, sequencing
  choice).

All items in this document are **[DESIGN]** unless marked otherwise; nothing here is
implemented and nothing should be claimed in user-facing docs until the corresponding
acceptance tests exist.
