# 04 — Offline Validation Results (E1-A + E1-B preflight)

Method: `python -m scripts.e1_scorer --selfcheck` (fixed samples, zero LLM
calls) plus `tests/unit/test_e1_scorer.py` (22 regression-locked tests that do
NOT depend on local historical artifacts) plus the zero-cost runner dry run
(`python -m scripts.e1_runner --dryrun`, locked by
`tests/integration/test_e1_runner_dryrun.py`). E1-A run date: 2026-10-24,
baseline `fdf671d`; E1-B preflight run date: 2026-10-25, scorer version
**e1-scorer-v2**.

## The validation matrix (all as expected)

Generic samples (E1-A, unchanged):

| Sample | Type | Expected | Observed | ✓ |
|---|---|---|---|---|
| flanker reference (in-code) | known-good | D4 PASS, D5 PASS | D4 PASS, D5 PASS | ✓ |
| WM reference (in-code) | known-good | D4 PASS, D5 PASS | D4 PASS, D5 PASS | ✓ |
| task-switch reference (in-code) | known-good | D4 PASS, D5 PASS | D4 PASS, D5 PASS | ✓ |
| T2R nominal pattern (in-code) | **known-bad** | **D4 FAIL**, D5 PASS | D4 FAIL, D5 PASS | ✓ |
| historical T5 bundle (real run) | known-good | D3 PASS, D5 PASS | D3 PASS, D5 PASS | ✓ |
| **historical T2R bundle (real run)** | **known-bad** | D3 PASS **and D4 FAIL** | D3 PASS, D4 FAIL | ✓ |
| historical T5 run record | known-good | D1 PASS | D1 PASS | ✓ |
| historical T2R run record | known-bad | D1 FAIL | D1 FAIL (budget-stop) | ✓ |
| WM bundle with inverted answer keys | known-bad | D5 FAIL | D5 FAIL (direction contradiction) | ✓ |
| reference flanker HTML (D6 driver) | known-good | D6 PASS | D6 PASS (8 trials, 8 responses, self-check OK) | ✓ |

Task-level references and adversarial samples (E1-B preflight; every sample is
schema-valid — each violates its BRIEF, not the schema):

| Sample | Type | Expected | Observed | ✓ |
|---|---|---|---|---|
| T5 reference (in-code) | known-good | D4 PASS, D5 PASS | D4 PASS, D5 PASS | ✓ |
| T2R good reference (real load, phases) | known-good | D4 PASS, D5 PASS | D4 PASS, D5 PASS | ✓ |
| flanker with FOUR arrows | adversarial | D4 FAIL | D4 FAIL ("4 arrow characters") | ✓ |
| flanker keyed by congruency, not center | adversarial | D5 FAIL | D5 FAIL ("middle arrow does NOT determine") | ✓ |
| flanker congruency not in the flanks | adversarial | D4 FAIL, D5 FAIL | D4 FAIL (never varies) + D5 FAIL (target no longer affects content) | ✓ |
| WM with 3-word "low" load | adversarial | D4 FAIL | D4 FAIL ("3 memorized words") | ✓ |
| WM probe phase shows the study set | adversarial | D4 FAIL | D4 FAIL ("probe phase shows 5 content words") | ✓ |
| task-switch, both mappings flipped | adversarial | D5 FAIL | D5 FAIL ("literal direction violated") — consistent+inverted+balanced, caught ONLY by the brief-level direction check | ✓ |
| T5 colors 9/1 unbalanced | adversarial | D4 FAIL | D4 FAIL ("not balanced") | ✓ |
| T5 identical content both colors | adversarial | D4 FAIL, D5 FAIL | D4 FAIL + D5 FAIL (ambiguous content) | ✓ |
| T2R explore game with 2 rooms (rendered HTML) | adversarial | D4 FAIL | D4 FAIL ("only 2 explorable rooms"; load/membership checks still PASS on the same bundle) | ✓ |
| T2R good reference, 3 rooms (rendered HTML) | known-good | D4 PASS + INCONCLUSIVE marker | D4 PASS ("3 explorable rooms") + explicit MANUAL-ACCEPTANCE note for runtime order invariance | ✓ |

`_all_as_expected = True` (exit 0). No scoring standard was lowered to make a
reference pass: two adversarial samples fail BOTH D4 and D5, and the flipped
task-switch sample passes every generic check (consistent, inverted, balanced)
and is caught only by the brief's literal direction requirement.

The two headline properties required by the E1-A mandate:

1. **The scorer identifies the T2R nominal-manipulation failure** — on BOTH
   the in-code pattern and the REAL 2026-10-22 artifact, while correctly
   reporting that the same artifact passes `verify_bundle` (D3 PASS). Schema
   validity is not scientific validity, and the scorer demonstrably encodes
   that distinction.
2. **The scorer is validated on known-good AND known-bad fixed samples** —
   including a direction-inverted-key sample (D5) and an ambiguous-content
   sample (regression test) — so a PASS is meaningful, not a default.

## Defects found and fixed during scorer development (recorded for audit)

The offline validation did its job: it caught three real scorer bugs and one
fixture bug before any paid run:

1. **Template-decoration pollution (D5)**: probe-membership tokens initially
   included fixed template words ("Probe:"), which are never in the encoding
   set, collapsing the invariant. Fixed by removing tokens common to every
   trial of a phase kind before comparing.
2. **`dict.items()` vs `values()` (D5 task-switch check)**: the per-task
   consistency check iterated items (yielding (key, value) tuples of length
   2), making "inconsistent" the constant verdict. Fixed to `values()`.
3. **Inverted keys are also a consistent function**: the learned
   probe-membership→key mapping cannot detect a globally inverted key on its
   own. Fixed by anchoring the mapping direction to the spec's declared
   `correct_rule` true/false_option when present (now the inverted-key sample
   fails with "direction CONTRADICTS the declared correct_rule").
4. **A fixture bug the scorer itself caught** (encouraging): the first T2R
   nominal fixture accidentally declared two one-line templates where a
   single two-line template was intended, so each trial showed only one
   random line — and the scorer correctly failed D5 with "identical stimulus
   content maps to different answer keys". The scorer detecting a real bug in
   its own validation fixture is direct evidence the checks are live.

## Contamination controls verified

- The selfcheck writes all temporary bundles under a scratch directory; it
  never writes into another task's sandbox or the historical artifact paths.
- The pytest suite uses only in-code fixtures; it cannot depend on (or mutate)
  the gitignored historical artifacts — proven by running the suite with the
  historical directories untouched.
- The artifact scorer reads bundles from paths given to it and performs no
  writes; the D6 driver plays a COPY-free read of the HTML with a temporary
  harness (tempdir, removed after).

## Runner dry run (zero-cost, end-to-end)

`python -m scripts.e1_runner --dryrun` drives the REAL AgentLoop, the REAL
9-tool registry and the REAL scorer with a MockLLM — six scenarios, all as
expected (regression-locked in `tests/integration/test_e1_runner_dryrun.py`):

| Scenario | Expected | Observed |
|---|---|---|
| success | completed; artifacts produced; D1/D3/D6 PASS (incl. the node driver playing the rendered HTML) | exactly that; brief verbatim in `brief.txt`; report/scored JSON retained |
| validation failure | model claims success without artifacts → D1 FAIL, failure_class=no-artifacts | exactly that (scored JSON records "no artifacts produced") |
| budget stop, call cap | pre-call hard stop at 3 calls; stop_reason=budget-stop | exactly that (llm_calls=3, the 4th call never issued) |
| budget stop, cost cap | post-call accounting stops the next call; stop_reason=budget-stop-cost | exactly that (one $0.9-reported call vs a $0.50 cap; llm_calls=1) |
| usage missing | unreported usage NOT counted as $0; conservative guard; reported cost 0.0 marked lower bound | exactly that (stops after 2 unreported calls; cost_is_lower_bound=true) |
| API error | clean failure, failed call counted as billed, llm_error class | exactly that (llm_calls=1; artifacts/report retained) |

The dry run also verifies: each task in a fresh sandbox (reuse refused);
the agent sees ONLY the brief (recorded verbatim); nothing from the scorer is
injected into the conversation; scoring runs strictly AFTER the run.

## Known limits (carried into E1-B unchanged)

- D4's label-masking is a text-line heuristic (false positives on
  timing-only manipulations, false negatives on coincidental content
  differences). The five E1 briefs avoid both modes.
- D5's invariant families cover the documented composition recipes; an agent
  design outside those families yields INCONCLUSIVE → researcher review
  (honest, by design).
- D6's generic driver covers the classic layout only; explore-layout games
  (brief 5) are INCONCLUSIVE → manual play review by the researcher.
- D1 for a run that renders a broken-but-rendered game still needs D3/D4/D5/D6
  to catch downstream problems — that is why dimensions are separated.
