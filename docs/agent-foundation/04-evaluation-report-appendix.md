# Offline agent evaluation report

- Scenarios: **8** (ScriptedLLM through the real AgentLoop + real tools)
- Execution completion rate: **0.875**
- Termination reasons: `{"model_final_answer": 7, "max_steps_exceeded": 1}`
- Tool error events by category: `{}`
- Error recovery rate (hard tool errors): **None**
- Validation repair rate (structured feedback loop): **1.0**
- Mean / median model calls: **4.5 / 5.0**

- Verified artifact success rate (L3): **0.625**
- Partial-artifact runs: `['s5_partial_artifacts', 's7_untrusted_tool_result']`

- Nominal-manipulation flagged by the L4 label-masking HEURISTIC: `['s6_nominal_manipulation']` (heuristic: text-line designs only; timing-only factors false-positive, coincidental content differences false-negative)
- Designed false-success probe `s6_nominal_manipulation` must appear above
- Researcher review required: 4 items (construct validity, calibration, cue leakage, counterbalancing)

- False success rate: **0.125** (completed+verified+rendered but L4 auto-check failed)
- Token usage / cost: null (scripts report no usage; never fabricated)
- Real LLM: **pending** — No paid API calls are made by this harness. ScriptedLLM rates measure workflow mechanics, NOT agent capability. Real-model evaluation requires explicit user authorization.

## Per-scenario detail

| id | status | termination | model calls | tool calls | errors | recovered | L3 bundle | L3 html | L4 all-pass |
|---|---|---|---|---|---|---|---|---|---|
| s1_simple_experiment | completed | model_final_answer | 7 | 6 | - | False | True | True | True |
| s2_multicond_explore | completed | model_final_answer | 6 | 5 | - | False | True | True | True |
| s3_multiphase_trials | completed | model_final_answer | 5 | 4 | - | False | True | True | True |
| s4_error_param_repair | completed | model_final_answer | 6 | 5 | - | False | True | True | True |
| s5_partial_artifacts | completed | model_final_answer | 2 | 1 | - | False | True | None | True |
| s6_nominal_manipulation | completed | model_final_answer | 5 | 4 | - | False | True | True | False |
| s7_untrusted_tool_result | completed | model_final_answer | 2 | 2 | - | False | None | None | None |
| s8_budget_exhausted | failed | max_steps_exceeded | 3 | 3 | - | False | None | None | None |
