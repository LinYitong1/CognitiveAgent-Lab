# 02 — E1 Task Briefs (Natural Language Only)

**Briefs version: `e1-briefs-v1`** (frozen 2026-10-25; the E1-B runner embeds
a verbatim copy as its single source at run time — any change here requires a
new version tag and a runner update).

These five briefs are the COMPLETE task input the agent receives: the brief
text plus the normal tool documentation (the `validate_experiment` /
`validate_game` tool descriptions and their field descriptions — exactly what
every run sees). **Nothing else.** No ExperimentSpec, no GameSpec, no worked
example beyond the tool docs' own, no scoring information, no reference to
the evaluator's fixtures.

Style: a researcher describing an experiment requirement, the way they would
to a human programmer. English (the loop's working language); brief 5's
original was Chinese and is preserved alongside.

Run order (fixed for E1-B): 1 → 2 → 3 → 4 → 5, each in a fresh sandbox
(`data/e1-runs/<run-id>/<task-id>/`).

---

## Brief 1 — e1_t5_retest (historical success retest)

> I need a simple visual discrimination experiment as a browser game. On each
> trial the screen shows a color name (red or blue), and the participant
> presses the matching key. 10 trials, balanced across the two colors. Give me
> a playable single-file HTML game with the standard reproducibility
> guarantees, and make sure the event log records what was shown, what was
> answered, whether it was correct, and the response time.

Purpose in E1: a capability floor retest — this brief succeeded historically
(T5, $0.036); failure now would indicate a regression on the current surface
(Stage 1 changed tool docs, so drift is possible and must be detected).

## Brief 2 — e1_flanker (relational content)

> Design a flanker task. Each trial shows a row of five arrow characters,
> like `<<><<` or `>>>>>`. The participant reports the direction of the MIDDLE
> arrow (left or right). The flanking arrows are either the same direction as
> the middle one (congruent) or the opposite (incongruent); congruent and
> incongruent trials should occur equally often, and the middle direction
> should also be balanced. The correct answer is always the middle arrow's
> direction. 16 trials. I want the game as a single HTML file, and the data
> log must let me analyze accuracy and reaction time separately for congruent
> vs incongruent trials.

Purpose: forces cross-factor relational content (the documented composition
recipe). A nominal design (labels instead of arrows) must fail D4.

## Brief 3 — e1_wm (working memory: load + multi-phase)

> I need a short-term memory experiment. Each trial has two parts: first a
> study screen showing a small set of words to remember, then, after the
> study screen, a probe screen showing one word. The participant judges
> whether the probe word was in the memorized set (yes) or not (no). Memory
> load varies between trials: some trials show 2 words, others show 4; both
> loads equally often. Probes are in the set on half the trials and new on
> the other half, crossed with load. 16 trials total. The study and probe
> screens must be separate presentations (the probe must not be visible while
> the study set is on screen). Answer keys must follow the actual words shown.
> Deliver the playable HTML game with the reproducibility guarantees.

Purpose: load manipulation (real content difference per level) + phased
presentation + content-driven correctness. The exact failure mode of T2R.

## Brief 4 — e1_taskswitch (task cuing and mapping)

> Design a task-switching experiment. There are two judgment tasks on the
> same kind of stimulus. On each trial a cue first tells the participant
> which task to perform, then a word appears. In task A, the participant
> answers whether the word is "same"; in task B, whether it is "different" —
> the correct answer depends on the task: for task A the correct answer is
> "yes" exactly when the word is "same", for task B exactly when the word is
> "different". Both tasks and both answers should occur equally often, 16
> trials. The cue must be shown before the word on every trial. The data log
> must let me identify, for every trial, which task was cued, so I can
> compute switch costs by comparing trials where the task changed from the
> previous trial versus stayed the same. Single playable HTML file please.

Purpose: cue phase + task-contingent answer mapping + analyzable switch
conditions (task factor logged per trial).

## Brief 5 — e1_t2r_regression (the historical nominal-failure case)

> 我要做一个基于可探索场景的工作记忆实验，主题是废弃空间站。实验为
> 被试内设计，两个因素：记忆序列长度（短/长）× 探测类型（相同/不同），
> 共 12 个平衡试次。每个试次先呈现记忆序列，再呈现探测项，被试判断
> 探测项是否在刚才的序列中（相同/不同），用 s/d 键反应。游戏要有至少
> 3 个可探索的房间，试次通过探索场景中的特定对象触发，但探索顺序
> 不能改变试次的内容和顺序。请交付可玩的单文件 HTML 游戏和完整的
> 数据记录。
>
> (English summary for the log: an explorable abandoned-space-station
> working-memory game, length short/long × probe same/different, 12 balanced
> trials, memorize-then-probe with s/d keys, at least 3 explorable rooms,
> exploration must not alter trial content or order.)

Purpose: the regression case. This is the requirement class that failed
scientifically on 2026-10-22 (schema-valid, nominally manipulated, budget-
stopped before render). Stage 1 gave the surface the documented capabilities
(phases, load maps, content-driven keys, the explore renderer with invariant
protection) — E1-B measures whether the model now produces a REAL
working-memory design under the same budget discipline. Note: since the T2R
run, the engine has gained the capabilities that made the old failure
"the best the engine allows" — a nominal result now would be a model-side
failure, not an engine-side excuse.

---

## Administration notes (E1-B runner, not part of the briefs)

- Each brief is sent as the single user task message to a fresh AgentLoop
  (max_steps = 16 model calls; see 05).
- The agent's available surface is the standard 9-tool game registry; nothing
  is added or removed for E1.
- The runner must NOT inject anything into the conversation beyond the brief;
  the run report must show `model_calls` starting from the brief as the first
  user message.
