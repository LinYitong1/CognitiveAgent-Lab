# Phase A Backend 交付交接文档 — Generic Experiment Engine

> 作者：Backend Agent ｜ 日期：2026-10-20 ｜ 基线：commit ae8dd68（M1 全验收通过）
> 实现唯一依据：`docs/handoff/architect-phaseA-contract.md`（冻结版，PA-1~PA-14）
> 状态：Backend 自验全部通过，待 QA 按 §⑦ PA-1~PA-13 验收；PA-14（真实 LLM Demo）由 Lead 在 QA 后于用户环境执行。

---

## 1. 模块结构（新增文件）

```
src/experiment/                  实验引擎层（分层序 4：tools 之下，只依赖 models/config/stdlib）
├── __init__.py                  包说明（分层声明；组合注册在 src/agent/experiment_registry.py）
├── schemas.py                   ExperimentSpec 全层级 Pydantic 模型（§2 字段表 + V1~V9 + Trial/GeneratedExperiment）
├── canonical.py                 canonical_json 五参数 + sha256_hex（完整 64 hex，无 [:8] 截断）
├── validation.py                验证层：ValidationIssue、错误码枚举（§4.4 全量）、C1/C2/C3、
│                                UNSAT 各形态、errors≤20+truncated、stalled 指纹协议
├── generation.py                确定性引擎：derive_block_seed（SHA-256 前 8 字节）、九步算法、
│                                ENGINE_SPEC_VERSION="1.0"、largest remainder、effective_weights
├── export.py                    build_bundle(spec, *, generated_at=None)：Bundle 组装 +
│                                bundle_sha256（剥离两键规则）、allocation per-block 口径
└── verify.py                    verify_bundle + CLI（python -m src.experiment.verify <path>，exit 0/1）

src/tools/
├── _sandbox_io.py               沙箱五步规则可复用实现（与 file_write.py:39-79 同语义；
│                                同步义务注释在本文件头——file_write.py 本体零修改）
└── experiment_tools.py          三工具：validate_experiment / generate_trials / export_experiment
                                 （Input 模型 + _ExperimentBlocked + BLOCKED: 前缀 + build_* 工厂；
                                 256KB config 护栏 ×3、1MB bundle 护栏、两级错误契约）

src/agent/experiment_registry.py build_experiment_registry(settings)：M1 三工具 + 实验三工具组合注册
                                 （src/agent/__init__.py 零改动）

examples/run_experiment_agent.py Demo 入口（§9：三工具注册、goal 冻结文本、task_id 首行、
                                 bundle+双指纹+verify 提示行、exit 0/1/2）

tests/unit/experiment/           PA-1~PA-7、PA-11、PA-12 单元测试（63 个）
tests/integration/test_experiment_agent.py  PA-8/9/10 FakeLLM 集成测试（3 个）
tests/golden/                    PA-13：generic-2x2-seed7.json（9652 字节 canonical 单行）+ test_golden.py
docs/handoff/backend-phaseA.md   本文
```

### 批准扩展（仅两处 M1 文件变更，各一行/两行）

```diff
# src/config.py（§8.2）
+    # SEARCH_EXHAUSTED 框架能力参数（契约 §4.2；Phase A 无消费路径，Phase B 序列约束消费）
+    experiment_max_search_attempts: int = 100

# scripts/check_layers.py（§8.3）
     "tools": 3,
     "storage": 3,
+    "experiment": 4,  # Phase A 新增：tools 之下的实验引擎层（契约 §8.3 批准扩展）
```

## 2. 测试选择器 ↔ PA 条目对照（QA 验收命令照此执行）

| PA | 命令 | 命中测试 |
|----|------|----------|
| PA-1 | `pytest tests/unit/experiment -k "spec_"` | test_schemas.py 的 test_spec_accepts_*（3）+ test_spec_rejects_*（14）；附带命中 test_generate_invalid_spec_no_generation（名字含 "spec_no"，无害） |
| PA-2 | `-k "determin or cross_ or isolation or regenerate"` | test_determinism.py 全部 4 个（模块名含 "determin"，test_generation_same_seed_byte_identical 经模块名命中） |
| PA-3 | `-k "c1 or c2 or c3 or ratio or remainder or mismatch or mutex or filter_empty or correct_from or paradigm or unsupported"` | test_validation.py 的约束/频数 15 个 |
| PA-4 | `-k canonical` | test_canonical.py 4 个 |
| PA-5 | `-k "sha256 or fingerprint or verify"` | test_fingerprints.py 6 个（期望向量独立计算写死） |
| PA-6 | `-k "unsat or search_exhausted"` | test_unsat_error_code_mapping + test_search_exhausted_framework_capability（声明性弱断言，局限见源码注释） |
| PA-7 | `-k "tool_"` | test_tool_specs.py 全部 6 个（注意：test_config_size_blocked / test_generate_no_file_written / test_errors_truncated_at_20 三个冻结名不含 "tool_"，经**模块名** test_tool_specs 命中——pytest -k 匹配模块名；若 QA 环境禁用该行为，改跑整文件 `pytest tests/unit/experiment/test_tool_specs.py`） |
| PA-8/9/10 | `pytest tests/integration -k "design_iteration or stalled or max_steps"` | test_experiment_agent.py 3 个（另命中 M1 的 test_loop_step_limit，一并绿） |
| PA-11 | `-k "export_blocks or export_sandbox"` | test_export_sandbox.py 5 个 |
| PA-12 | `python -m scripts.check_layers && pytest tests/unit/experiment -k "layers or static_guard"` | test_layers_static.py 6 个（AST 级 import 守卫 + random/datetime/uuid 扫描 + pyproject 依赖白名单不变断言） |
| PA-13 | `pytest tests/golden` | test_golden_export_unchanged（逐字节，含 bundle_sha256；UPDATE_GOLDEN=1 重写后 skip 提示人工 review） |
| PA-14 | `python examples/run_experiment_agent.py`（Lead 执行，qwen2.5:7b @ Ollama） | stdout：task_id → status: completed → result → bundle/trials_fingerprint/bundle_sha256/verify 四行；随后 `python -m src.experiment.verify <bundle>` exit 0 |

## 3. 运行方式

```bash
# 单元 + 黄金
.venv/bin/python -m pytest tests/unit/experiment tests/golden --capture=no -p no:cacheprovider
# 集成（FakeLLM，无 key 可跑）
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null \
  .venv/bin/python -m pytest tests/integration --capture=no -p no:cacheprovider
# 全量回归（M1 55 + Phase A 67 = 122）
.venv/bin/python -m pytest --capture=no -p no:cacheprovider
# 类型与分层门禁
.venv/bin/python -m pyright src/            # 0 errors
.venv/bin/python -m scripts.check_layers    # exit 0
# 独立验证任意 Bundle（不需要生成器）
.venv/bin/python -m src.experiment.verify data/experiments/<name>.json
# Demo（需 .env：OPENAI_API_KEY 任意非空 + LLM_BASE_URL=http://localhost:11434/v1 + LLM_MODEL=qwen2.5:7b）
.venv/bin/python examples/run_experiment_agent.py
# 黄金文件更新流程
UPDATE_GOLDEN=1 .venv/bin/python -m pytest tests/golden   # → 人工 review diff → PR 说明 + engine_spec_version 递增
```

## 4. Backend 自验记录（真实退出码）

| # | 命令 | 结果 |
|---|------|------|
| 1 | `pytest tests/unit/experiment --capture=no -p no:cacheprovider` | **63 passed，exit 0** |
| 2 | `pytest tests/integration -k "design_iteration or stalled or max_steps" ...` | **4 passed，exit 0** |
| 3 | `pytest tests/golden ...` | **1 passed（逐字节一致），exit 0** |
| 4 | `pytest --capture=no -p no:cacheprovider`（全量） | **122 passed，exit 0**（M1 55 + Phase A 67） |
| 5 | `pyright src/` | **0 errors, 0 warnings，exit 0** |
| 6 | `python -m scripts.check_layers` | **[PASS]，exit 0** |
| 7 | `git status --short` | 仅新增文件 + config.py + check_layers.py（另见 §6 环境备注） |
| 8 | `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null pytest tests/integration` | **7 passed，exit 0**（FakeLLM 无 key 证明） |
| 附 | 契约 §8.2 M1 回归两命令 | **55 passed，exit 0**；tests/e2e 无用例（与 M1 基线一致） |
| 附 | Demo 缺 key | `exit 2` + stderr 提示（M1-2 模式） |

## 5. 已知限制（如实声明）

1. **SEARCH_EXHAUSTED 在 Phase A 不可触发**：约束集全部验证期可判定，无搜索路径。框架能力已按契约落全（错误码枚举、`generate_trials(max_attempts=100)` 签名、`Settings.experiment_max_search_attempts`），对应测试为声明性弱断言（PA-6 局限性由契约如实标注）。真实触发随 Phase B max_repeat 进入。
2. **可重复性边界 = 同一 Python 实现与版本（3.13.x）**：`random.Random` 的 MT19937/shuffle 跨版本稳定性是实现细节非语言规范；float 最短往返跨语言有边界差异。跨实现复现依赖 conformance 向量集（OUT-3 推迟）。Python 升级时黄金文件是回归网。
3. **1MB 导出上限 ≈ 5k 试次**（R-6）：超限显式 `BLOCKED: export too large`，分块导出推迟。
4. **validate/generate 的完整 JSON 报告进事件流时被 `_SUMMARY_LIMIT=512` 截断**（R-1）：不影响 LLM（tool message 用全量 result）；验收口径以 FakeLLM received_messages 与落盘文件为准（PA-8 已按此设计）。
5. **跨因素水平重名是未定义边界**：契约未裁定两因素共用水平名时 mutually_exclusive 的配对语义；当前实现按"水平名集合同现"判定（与契约 §4.3 表述一致），全部冻结测试用例不涉及该形态。
6. **strict balance 不存在**：trial_count 不整除时按 largest remainder 近似 + RATIO_ROUNDED 警告（§4.3 裁定）；严格等频模式留待 §⑩.4 决策。

## 6. 环境备注（QA 需知）

1. **pytest tmp_path 在本沙箱不可靠**：宿主安全代理对 pytest 会话根目录的 `mkdir(exist_ok=True)` 存在间歇性 PermissionError 拦截（M1 测试 docstring 记录的同类现象）。Phase A 全部新测试沿用 M1 固定子目录模式（`data/.test-sandbox/experiment-*`，自建自清，data/ 已 gitignore）。
2. **工作区存在两份非 Backend 造成的文档格式化改动**：`docs/handoff/m1-2-report.md`、`docs/handoff/qa-M1-2.md` 在工作树中显示 modified（纯 markdown 表格对齐/行尾空格，无语义变化；mtime 19:22，早于 Backend 首次写入 19:35，非本次交付所为）。Backend 未触碰、未还原——请 Lead 提交时甄别归属。M1 产品代码/测试文件经 `git diff` 核实零修改。
3. 集成测试会在 `logs/` 落 `agent-task-expa00*.jsonl`（gitignored），在 `data/.test-sandbox/` 留测试残留（gitignored，清不掉无妨）。

## 7. 契约遵循性说明（与任务指令的差异报告）

以下均为"任务指令与契约冲突时以契约为准"的显式记录，非契约偏离：

1. **组合注册位置**：任务指令要求 `build_experiment_registry` 落 `src/experiment/__init__.py`；契约 §5.4/§8.1 冻结为 `src/agent/experiment_registry.py`（且分层规则禁止 experiment 层 import agent/tools）。**按契约实现**。
2. **文件命名**：任务指令列 spec.py/validate.py/bundle.py/errors.py；契约 §2/§8.1 冻结为 schemas.py/validation.py/export.py，错误码枚举并入 validation.py（任务指令自身也允许"或并入各模块"）。**按契约实现**。
3. **"两处文件头同步注释"**：契约 §5.3 要求 file_write.py 与 _sandbox_io.py 两处文件头注明同步义务，但 §8.1 与文末清单同时禁止修改 file_write.py——同步注释仅落 _sandbox_io.py 文件头（与文末清单一字不差：`_sandbox_io.py：…文件头同步义务注释；未修改 file_write.py`）。
4. **V1~V9 实现载体**：契约 §2.1 注释块写 "model_validator（ExperimentSpec 级）"；实际以 field_validator（跨字段经 info.data）+ ResponseVar model_validator 组合实现，语义逐条等价（V1~V9 全覆盖），目的是让每条结构错误携带可用 path（loc）——契约冻结的是校验语义，实现载体属"实现内部细节可自定"范围。此差异已在 schemas.py 文件头注明。

## 8. 给 QA 的提示

1. PA 断言口径全部为**精确整数**频数（黄金 spec：48 试次每组合 12、每水平 24/24；Demo spec：104 试次每组合 26、每水平 52/52）。
2. PA-8 的"generate 输出 trials_fingerprint == Bundle 内值"从 FakeLLM `received_messages[3]` 的**最后一条** tool 消息取（该轮含第二轮 validate 输出与 generate 输出两条 tool 消息）；"迭代证据"从 `received_messages[1]` 取。
3. PA-9 逐轮推演（MA-1）已在测试内断言三轮 stalled 分别为 false/false/true。
4. verify CLI 的失败路径会向 stderr 输出 detail 且 exit 1（篡改 trials 任一字节 → 两项 check 同时失败）。
5. 黄金文件 `tests/golden/generic-2x2-seed7.json` 为 canonical 单行 JSON（无尾随换行、无 BOM），比对务必逐字节（非语义 diff）。
6. 静态守卫（PA-12）用 AST 解析 import——docstring 中出现 "src.agent" 等字样不会误报。
