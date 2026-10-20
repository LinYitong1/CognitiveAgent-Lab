# Phase A QA 验收报告 — Generic Experiment Engine（PA-14 Demo 前）

> 作者：QA Agent ｜ 日期：2026-10-20 ｜ 验收对象：Backend Phase A 交付（基线 commit ae8dd68）
> 验收依据：`docs/handoff/architect-phaseA-contract.md`（冻结契约，§7 PA-1~PA-14）+ `docs/handoff/backend-phaseA.md` + `.workbuddy/memory/MEMORY.md` 产品边界
> 验收方式：独立执行（不复用 Backend 自验记录）；全部命令附实际退出码。沙箱限制：pytest 一律加 `--capture=no -p no:cacheprovider`。
> **总体结论：Phase A（PA-14 Demo 前）通过。** PA-1~PA-13 全部 PASS，无 Blocker / Major 问题；4 项契约差异全部接受；3 项 Minor + 3 项 Suggestion 已列明（均不阻塞）。建议 Lead 放行 PA-14（真实 LLM Demo）。

---

## 1. PA-1~PA-13 逐项验收表

| ID | 命令（实际执行） | 退出码 | 输出摘要 | 结论 |
|----|----------------|--------|----------|------|
| PA-1 | `.venv/bin/python -m pytest tests/unit/experiment -k "spec_"` | 0 | **18 passed**, 45 deselected（test_schemas.py 17：accepts ×3 / rejects ×14，含 seed 越界、组合数>100k、trial_count 越界、mutex 长度、ratios 重复等冻结名全在场；附命中 test_generate_invalid_spec_no_generation ×1，backend-phaseA.md §2 已预告，无害） | **PASS** |
| PA-2 | `-k "determin or cross_ or isolation or regenerate"` | 0 | **4 passed**（test_generation_same_seed_byte_identical / test_generation_cross_pythonhashseed / test_block_isolation / test_regenerate_bundle_identical，四冻结名全在场；PA-2 深度验证见 §3.1/§4） | **PASS** |
| PA-3 | `-k "c1 or c2 or c3 or ratio or remainder or mismatch or mutex or filter_empty or correct_from or paradigm or unsupported"` | 0 | **23 passed**（test_validation.py 13 冻结名全在场 + determinism 2 + schemas 5 + layers 1 + tool 2）；C2 双情形断言逐条核实（balance=true+weight≠1 警告、ratios 因素上 weight≠1 警告，均不影响 valid） | **PASS** |
| PA-4 | `-k canonical` | 0 | **4 passed**（sorted_compact / utf8 中文往返 / rejects_nan / default_omission_same_fingerprint） | **PASS** |
| PA-5 | `-k "sha256 or fingerprint or verify"` | 0 | **6 passed**（known_vectors / full_length / excludes_timestamp / verify_ok / verify_detects_tamper + canonical 1）；期望向量独立验证见 §4.2 | **PASS** |
| PA-6 | `-k "unsat or search_exhausted"` | 0 | **2 passed**（test_unsat_error_code_mapping：`set(fixtures)==set(UNSAT_ERROR_CODES)` 保证 5 个 UNSAT 码全枚举触发；test_search_exhausted_framework_capability：声明性弱断言，局限性声明与契约一致，见 §3.8） | **PASS** |
| PA-7 | `-k "tool_"` | 0 | **6 passed**（registered_flags / domain_vs_tool_error / config_size_blocked / generate_no_file_written / errors_truncated_at_20 / generate_invalid_spec_no_generation；后者 3 个冻结名不含 "tool_"，经**模块名** test_tool_specs 命中——实测生效，backend-phaseA.md §2 预告正确） | **PASS** |
| PA-8/9/10 | `pytest tests/integration -k "design_iteration or stalled or max_steps"` | 0 | **4 passed**（实验 3 个 + M1 test_loop_step_limit 一并绿）；集成测试质量审计见 §5 | **PASS** |
| PA-11 | `-k "export_blocks or export_sandbox"` | 0 | **5 passed**（traversal / symlink / prefix_confusion / oversize / success_in_sandbox——五步规则全部生效证据；oversize 构造 >1MB Bundle → `BLOCKED: export too large`） | **PASS** |
| PA-12 | `.venv/bin/python -m scripts.check_layers && pytest … -k "layers or static_guard"` | 0 | check_layers **[PASS]**（experiment 层登记生效）+ **6 passed**（AST 级 import 守卫、random 模块级函数扫描（`random\.(?!Random\b)` 正则）、generation 纯度（无 datetime/uuid/now(）、tools 层无 src.agent、pyproject 依赖白名单写死断言） | **PASS** |
| PA-13 | `pytest tests/golden` | 0 | **1 passed**（逐字节一致）；**黄金文件可信度独立验证**见 §4.1（verify CLI 重算 + 系统 shasum 交叉 + 48/48 试次独立复现） | **PASS** |
| PA-14 | （Lead 在 QA 放行后于用户环境执行，不在本轮） | — | — | **N/A（本轮范围外）** |

### 1.1 门禁与回归（契约 §8 + G 门禁）

| 项 | 命令 | 退出码 | 结果 | 结论 |
|----|------|--------|------|------|
| 全量回归 | `pytest --capture=no -p no:cacheprovider` | 0 | **122 passed**（M1 55 + Phase A 67：单元 63 + 集成 3 + 黄金 1），与预期一致 | PASS |
| M1 回归 ① | `pytest tests/unit/test_calc.py test_http_request.py test_file_write.py test_registry.py test_health.py tests/integration/test_loop.py` | 0 | **55 passed** | PASS |
| M1 回归 ② | `pytest tests/e2e` | 0 | collected 0（无用例，与 M1 基线一致） | PASS |
| M1 零修改 | `git diff ae8dd68 --stat -- src/ tests/ examples/ scripts/` | 0 | 仅 `scripts/check_layers.py +1`、`src/config.py +2`（逐行核对 = 契约 §8.2/§8.3 批准扩展，一字不多）；其余全部为新增文件（src/experiment/ 7、src/tools/ 2、src/agent/experiment_registry.py、examples/、tests/）；`git status --short` 无 M1 文件 modified。注：backend-phaseA.md §6.2 提到的 m1-2-report.md / qa-M1-2.md 文档改动在本次验收时点已不在工作树 | PASS |
| G-5a | `.venv/bin/python -m pyright src/` | 0 | **0 errors, 0 warnings** | PASS |
| G-3 | 密钥形态 grep | 0（命中复核） | 命中 4 文件均为 M1 既有文档：`task-3a3879b0db2b`（task-id 含 "sk-" 子串误报）与 `OPENAI_API_KEY=ollama`（Ollama 占位符）。**无真实密钥**；Phase A 新增代码/文档零命中 | PASS |
| G-4 | `.venv/bin/python -m scripts.check_layers` | 0 | [PASS] experiment 层（序 4）受门禁保护 | PASS |
| 无 key 集成 | `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null pytest tests/integration` | 0 | **7 passed**（FakeLLM 无 key 可跑证明） | PASS |

---

## 2. 验收方法声明

- 独立执行：所有命令由 QA 重新运行并记录退出码，未复用 Backend 自验记录；
- 交叉验证：指纹类断言一律用系统 `shasum -a 256` 在被验实现外部重算比对（不信任实现自算自比）；
- 独立复现：试次生成逻辑由 QA 自写脚本（仅标准库 hashlib/random/json 按契约 §3 算法）从零复现，与黄金文件比对（不 import 被验代码）；
- 审计独立于测试：PA-2/PA-5/PA-6/PA-13 等关键条目在测试绿之外另做了超越现有测试的深度验证（见 §3/§4）。

---

## 3. 重点人工审计（8 项逐项结论）

### 3.1 确定性引擎源码审计（PA-2 深度验证）—— PASS

- **seed 派生**（`src/experiment/generation.py:30-33`）：`hashlib.sha256(f"{seed}:block:{block_name}".encode("utf-8")).digest()` → `int.from_bytes(digest[:8], "big")`，与契约 §3.1 CR-1 逐字一致；派生键用 `block.name`（V3 保证唯一）。
- **九步算法逐条对照契约 §3.3**：
  - 第 1 步 组合展开：`schemas.py:266-271` `itertools.product` 声明序笛卡尔积 ✓
  - 第 2 步 互斥过滤：`generation.py:69-82` 同现剔除、序保持声明序（不排序——契约明示"序即确定性"）✓
  - 第 3 步 有效权重：`generation.py:36-61`（balance → 1/len(levels)；ratios → 声明值含 0.0；否则 weight 因素内归一化），组合权重 = ∏ 各因素权重（`generation.py:102-109`）✓
  - 第 4 步 factor_filter 过滤：`generation.py:85-99` ✓
  - 第 5 步 largest remainder：`generation.py:119-139`——exact → floor → R → `sorted(key=(-frac, i))` 按 fractional 降序、**并列按组合声明序（索引升序）** +1 共 R 个，与契约"并列时按组合声明序先者得 +1"完全一致 ✓
  - 第 6 步 物化：`generation.py:203-208` 按声明序复制 n_c 次 ✓
  - 第 7 步 排序：`generation.py:209-212` `shuffle_within=True` → `random.Random(derive_block_seed(...))` 实例恰一次 `shuffle`；`False` → 保持展开序 ✓
  - 第 8 步 index：`generation.py:213-223` `index=len(trials)` 全局 0 起连续，blocks 声明序拼接 ✓
  - 第 9 步 频数：`generation.py:172-181` 构造序 = 声明序 ✓
- **确定性静态核实**：引擎（generation.py）内**零 set 构造、零 set 迭代**（QA grep 独立扫描）；无 `random.` 模块级函数（唯一 `import random` 消费在 L211-212 `random.Random(...)` 实例）；无 `datetime`/`uuid`/`now(`/全局状态（docstring 声明与 AST 守卫测试双重在场，test_layers_static.py:56-62）；`datetime.now(timezone.utc)` 仅存在于 export.py:28-30 的 `generated_at` 元字段，不参与任何指纹（契约 §3.2 允许）。
- **超越测试的独立复现**：见 §4.3。

### 3.2 独立重复性实验 —— PASS（实测记录见 §4.3/§4.4）

QA 在 shell 独立执行了两项实验，均通过；且四份输出（两次同进程 + 两个 PYTHONHASHSEED 子进程）sha256 完全一致。

### 3.3 canonical JSON 与 SHA-256 正确性 —— PASS

- `src/experiment/canonical.py:14-16`：`json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)`——与契约 §6.1 五参数规范一字不差；
- `canonical.py:19-26`：`sha256_hex` / `sha256_hex_bytes` 均为完整 `hexdigest()`（64 小写 hex），无 `[:8]` 截断（CR-2）✓；
- 三指纹计算规则（`generation.py:225-226`、`export.py:74-75`、`verify.py:71-78`）与契约 §6.3 表逐条一致；bundle_sha256 剥离 `"bundle_sha256"` 与 `"generated_at"` 两键后计算 ✓；
- **外部工具交叉验证**：用系统 `shasum -a 256` 独立重算黄金 Bundle 的三个指纹（bundle_sha256 / trials_fingerprint / config_fingerprint）均与记录值一致（§4.2）——不信任实现自算自比。

### 3.4 UNSAT vs SEARCH_EXHAUSTED 语义（用户重点 #5）—— PASS

- **错误码枚举逐码比对**：`validation.py:33-46` 11 个错误码与契约 §4.4 表逐码一致（SCHEMA_INVALID / UNKNOWN_PARADIGM / UNSUPPORTED_CONSTRAINT / CONSTRAINT_CONFLICT / RATIO_SUM / BLOCK_FILTER_EMPTY / TRIAL_COUNT_MISMATCH / MUTEX_VIOLATION / CORRECT_FROM_UNKNOWN / SEARCH_EXHAUSTED / ITERATION_STALLED）；警告码 WEIGHT_IGNORED / RATIO_ROUNDED（`validation.py:49-53`）；`UNSAT_ERROR_CODES`（`validation.py:57-63`）= 5 个 UNSAT 码，与契约类别映射一致。
- **构造 spec 实测**（QA 自写探针脚本，9 个场景）：
  - ratios 和=0.9 → `RATIO_SUM`，message 含"和为 0.9，须 ≈1.0"（数学矛盾本身）、suggestion 可行动 ✓
  - factor_filter 圈空 → `BLOCK_FILTER_EMPTY` ✓
  - mutex + filter 叠加掏空 → `TRIAL_COUNT_MISMATCH` ✓
  - 同因素内两水平互斥 → `MUTEX_VIOLATION`（"无意义声明"语义正确）✓
  - ratios 部分置 0（和=1.0）→ valid=true（正确放行：显式排除非 UNSAT）✓
  - **反例验证（契约裁定）**：balance=true、10 试次不整除 4 组合 → `valid=true` + `RATIO_ROUNDED` 警告——**不是错误、更不是 UNSAT**，契约 §4.3 裁定被如实执行 ✓
  - balance+ratios 同开 → `CONSTRAINT_CONFLICT`；max_repeat → `UNSUPPORTED_CONSTRAINT`（message 注明"Phase B 支持，当前请移除"）；paradigm 非 null → `UNKNOWN_PARADIGM`（message 注明"Phase A 未实现插件系统"+已注册插件清单 `[]`）✓
  - 全部错误 message 含实际值、suggestion 非空 ✓
- **SEARCH_EXHAUSTED 在 Phase A 不可触发**：与契约 §4.3 声明一致（约束集全部验证期可判定，无搜索路径），错误码仅在枚举冻结。

### 3.5 无范式硬编码扫描（产品边界红线）—— PASS

- `grep -rniE "stroop|n.?back|flanker|bayesian|belief" src/experiment/ src/tools/experiment_tools.py` → **零命中**（rc=1）；
- schema（schemas.py）无任何指向特定实验范式的字段名/默认值/文档措辞；`paradigm`/`paradigm_params` 为不透明自由字段（非 null 由验证层拒绝，不解释内容）；
- 测试中的 `cueing-generic` 示例仅在 test_schemas.py 注释中声明"仅作为 schema 表达力用例，不意味任何范式支持"——契约 §2.3 明文允许该用法；
- core 代码零范式知识，符合 MEMORY.md"不为特定认知理论硬编码"红线。

### 3.6 export 沙箱同源审计 —— PASS

- `_sandbox_io.py` 五步规则与 `file_write.py:39-79` **逐条语义等价**：
  - 第 1 步 `isabs` + `".." in rel_parts` 拒绝：`_sandbox_io.py:42-43` ≡ `file_write.py:44-45`（逐字同）；
  - 第 2 步 realpath + `is_relative_to` 组件边界（防 data-evil 前缀歧义）：`_sandbox_io.py:47-55` ≡ `file_write.py:47-58`（同构）；
  - 第 3 步 沙箱根到目标逐级 `lstat` 拒符号链接：`_sandbox_io.py:59-67` ≡ `file_write.py:60-69`（同构）；
  - 第 4 步 大小上限：由调用方执行——`_sandbox_io.py:10-14` 文件头明示责任划分；export 工具层 `experiment_tools.py:173-174` 在写盘前执行 1MB 检查 → `BLOCKED: export too large` ✓（与 file_write 内联第 4 步语义等价，责任位置已声明）；
  - 第 5 步 沙箱内自动建父目录覆盖写：`_sandbox_io.py:72-75` ≡ `file_write.py:76-78`（同构）；
- 同步义务注释在 `_sandbox_io.py:3-4` 文件头 ✓；
- `file_write.py` 本体未修改：`git diff ae8dd68 --stat` 核实 src/tools/ 下仅新增文件、零既有文件变更 ✓。

### 3.7 契约 4 处差异处理合理性（backend-phaseA.md §7）—— 逐项 QA 意见

| # | 差异 | Backend 处理 | QA 意见 |
|---|------|--------------|---------|
| 1 | 组合注册位置：任务指令要求 `src/experiment/__init__.py`；契约 §5.4/§8.1 冻结为 `src/agent/experiment_registry.py` | 按契约（分层规则禁止 experiment 层 import agent/tools） | **接受**。任务指令与契约冲突以契约为准，工程流程约定有据；实现（experiment_registry.py:15-21）与契约 §5.4 逐字一致，M1 build_registry 零改动、`src/agent/__init__.py` 未动 |
| 2 | 文件命名：任务指令 spec.py/validate.py/bundle.py vs 契约 schemas.py/validation.py/export.py | 按契约（错误码枚举并入 validation.py，任务指令自身允许） | **接受**。同上；实测模块结构与 backend-phaseA.md §1 一致 |
| 3 | 同步注释位置：契约 §5.3"两处文件头"与 §8.1"禁止修改 file_write.py"内部矛盾 | 按契约文末确认清单：注释仅落 `_sandbox_io.py` 文件头，file_write.py 本体零修改 | **接受**。矛盾条款中以更具体的文末确认清单执行是合理裁定；见问题清单 S-1（建议 Architect 下版消除契约内部矛盾） |
| 4 | V1~V9 实现载体：契约 §2.1 注释写"model_validator（ExperimentSpec 级）"，实际以 field_validator（跨字段经 info.data）+ ResponseVar model_validator 组合 | 语义逐条等价，差异已在 schemas.py 文件头注明 | **接受，建议 Architect 复核备案**。QA 已逐条核对 V1~V9 全部在场且语义正确（schemas.py:42-50 V2 / 76-93 V6+V7 / 105-120 kind 一致性 / 155-171 V1+V9 / 173-181 V8 / 183-208 V3+V5(filter) / 210-218 V4 / 220-246 V5(ratios/mutex)）；契约冻结含义明示"实现内部细节 Backend 可自定"，且 field_validator 使每条结构错误携带可用 loc/path——对 LLM 迭代修正（错误回传协议）实际优于单一 model_validator |

### 3.8 PA-6 弱断言局限性确认 —— PASS

- 契约 §7 PA-6 如实标注："**声明性弱断言**……本条不测触发行为，真实触发测试随 Phase B max_repeat 进入"；契约 §4.3 第 4 条同样如实声明；
- 实现/测试声明一致无夸大：`test_search_exhausted_framework_capability` docstring 原文"本条只断言框架能力在场（错误码枚举、Settings 字段、generate_trials 签名），真实触发测试随 Phase B max_repeat 序列约束进入"；backend-phaseA.md §5.1 已知限制同口径；
- 四项框架能力全部在场且被弱断言覆盖：①错误码 `SEARCH_EXHAUSTED` 冻结于枚举（validation.py:45）；②`generate_trials(spec, max_attempts=100)` 签名冻结（generation.py:184）；③`Settings.experiment_max_search_attempts: int = 100`（config.py:34，"定死"默认值）；④弱断言测试（枚举在场 + Settings 默认值 + 签名参数含 default==100）。
- 结论：契约与实现的声明完全一致，无夸大。

### 3.9 FakeLLM 集成测试质量审计（PA-8/9/10）—— PASS

读 `tests/integration/test_experiment_agent.py` 全文逐断言核实：

- **断言真实（非空断言、非自欺断言）**：
  - PA-8（:113-168）：completed + result 精确比对；`bundle_path.exists()`（Bundle 落盘）；generate 输出 `trials_fingerprint` == Bundle 内值（同纯函数一致性，从 `received_messages[3]` 最后一条 tool 消息取，backend-phaseA.md §8.2 口径）；`verify` CLI 以独立子进程执行 exit 0；迭代证据 `received_messages[1]` 含 `CONSTRAINT_CONFLICT` 与 `"valid":false`；事件断言 validate≥1 / generate≥1 / export==1；频数精确整数（trial_count=104、difficulty 52/52）；
  - PA-9（:172-214）：previous_errors 逐轮累积 `[] → [f1] → [f1,f1]`；三轮 stalled 断言 false/false/true；ITERATION_STALLED 的 error_code 与 suggestion（"停止重复提交，总结未解决冲突并请用户裁决"）精确比对；终止且未导出（export==0、generate==0、`sandbox.rglob("*.json")` 为空）——与契约 §5 stalled 语义、§5.1 MA-1 逐轮推演完全一致；
  - PA-10（:218-245）：failed + "max steps" + `fake.calls == max_steps`（FakeLLM 第 max_steps+1 次调用会 AssertionError，防 loop 越界）+ 事件尾序 `[error, final]` + 无导出；
- 三测试统一经 `build_experiment_registry(settings)` 组装（契约 §9.1 要求 ✓）；沙箱根指固定测试子目录（backend-phaseA.md §6.1 环境备注的沿用，自建自清）。
- 结论：集成测试断言充分、真实，覆盖契约判据全部要点。

---

## 4. 独立实验与交叉验证结果（QA 实测记录）

### 4.1 黄金文件可信度独立验证（PA-13）

1. **verify CLI 重算**：`.venv/bin/python -m src.experiment.verify tests/golden/generic-2x2-seed7.json` → exit 0，"bundle_sha256 与 trials_fingerprint 两项校验均通过"；
2. **系统 shasum 外部交叉验证**（QA 脚本，剥离两键后 canonical 序列化，经 `shasum -a 256` 子进程重算）：
   - bundle_sha256：记录值 `96f33202…3ad24` == 外部重算值 ✓
   - trials_fingerprint：记录值 `7cb993c4…d6c0b` == 外部重算值 ✓
   - config_fingerprint：记录值 `0afd43fd…3125` == 外部重算值 ✓
   - `generated_at == "2026-01-01T00:00:00Z"`（契约冻结注入值）✓
3. **生成逻辑手工核对**（QA 自写独立脚本，仅标准库按契约 §3.1/§3.3 算法复现，不 import 被验实现）：**48/48 试次全序列独立复现一致**（强于"抽 3 个"要求；显式抽查 index 0/8/47 均逐字段一致），含 timing={500, null, 1000}、stimulus/derived 恒空 ✓；
4. **自洽性核对**：48 试次、每组合 12（practice 2+main 10）、每水平 24/24、index 0..47 连续、allocation per-block 口径与契约 §7.1 声明逐项一致 ✓。

### 4.2 PA-5 写死期望向量独立验证

`test_sha256_known_vectors` 的三个期望值用系统 `shasum -a 256` 重算（QA 独立执行）：`sha256("")=e3b0c442…` ✓、`sha256("abc")=ba7816bf…` ✓、canonical 中文对象 `78d14542…` ✓——期望值确实独立于被测代码（非实现自证）。

### 4.3 独立重复性实验（超越现有测试）

- **实验 1（同 spec+seed 两次 build_bundle）**：QA 用 Demo spec（seed=42，practice 8 + main 96）跑两次 `build_bundle(generated_at="2026-01-01T00:00:00Z")`，剥离 generated_at 后 `diff` 为空；两份输出 `shasum` 相同：`18db87b5324bd60836da2cf3ad67779a298a9623184312d6cfbf970f9b6f3bc4`；
- **实验 2（PYTHONHASHSEED 子进程）**：`PYTHONHASHSEED=1` / `PYTHONHASHSEED=2` 两个子进程跑同一生成（真实 `generated_at=now` 路径，剥离后比对）：`diff` 为空，且与实验 1 的输出 sha256 **四份完全相同**——同进程两次、跨 hashseed 子进程、固定/真实时间戳注入，全部收敛到同一逐字节结果。

---

## 5. 问题清单

### Blocker
无。

### Major
无。

### Minor
| # | 问题 | 位置 | 影响与建议 |
|---|------|------|-----------|
| M-1 | verify CLI 失败路径的 detail 同时输出到 stdout（L110 print）与 stderr（L112） | verify.py:110-113 | 输出冗余，不影响判据（exit 1 + stderr 在场）。建议 Phase B 顺手收敛为仅 stderr |
| M-2 | 契约 §3.4 第 3 条"Phase A 引擎中不存在任何 set 构造"的措辞：引擎（generation.py）确为零 set，但 validation.py:244/265、schemas.py:196/229 存在 set 构造——均仅用于 `in` 成员判断/交集真值判定，**无迭代**，确定性不受影响 | validation.py / schemas.py | 实现符合"禁止迭代 set"的实质规范；建议 Architect 下版把该实测声明的范围精确化（"生成路径零 set 构造；验证层 set 仅成员判断不迭代"） |
| M-3 | stalled 追加的 ITERATION_STALLED issue 发生在 `_finalize` 的 20 条截断之后，理论上最终 errors 可达 21 条 | experiment_tools.py:109-114 | 契约未裁定 stalled 追加是否计入 20 上限；触发需"≥20 条错误且同指纹停滞"极端复合条件，实际无影响。建议 Architect 备案裁定 |

### Suggestion
| # | 建议 | 说明 |
|---|------|------|
| S-1 | 消除契约内部矛盾：§5.3"两处文件头同步注释" vs §8.1"禁止修改 file_write.py" | Backend 按文末清单的裁定 QA 已接受（注释仅落 _sandbox_io.py）；建议 Architect 下版契约改写为"同步义务注释落 _sandbox_io.py 文件头" |
| S-2 | PA-14 执行口径提示：Demo 入口比契约 §9.3"追加三行"多输出一行 `verify: python -m src.experiment.verify <path>` 命令提示 | 无害且增强（backend-phaseA.md §2 已声明）；Lead 执行 PA-14 时按实际输出核对，勿判为偏离 |
| S-3 | invalid spec 上仍会计算并报告 RATIO_ROUNDED 等分配类警告（警告与错误独立） | 语义无害（警告不影响 valid 判定，契约亦未禁止）；但 LLM 反馈中可能出现"无效 spec 附带分配警告"，Phase B 可考虑 invalid 时抑制分配类警告以降噪 |

---

## 6. 结论

**Phase A（PA-14 Demo 前）通过。**

- PA-1~PA-13 全部 PASS（自动化测试 122/122 全绿 + 关键条目的深度审计与独立交叉验证全部成立）；
- M1 零修改边界成立（仅两处 Architect 批准的 +1/+2 行配置扩展，逐行核实）；
- 无范式硬编码红线成立（核心代码零命中）；
- UNSAT/SEARCH_EXHAUSTED 语义、双指纹 + bundle_sha256、stalled 协议、沙箱五步规则均与冻结契约一致；
- 契约 4 处差异处理全部接受（差异 4 建议 Architect 复核备案，不阻塞）；
- 3 Minor + 3 Suggestion 无一阻塞，无需退回 Backend。

**建议 Lead 放行 PA-14**（真实 LLM Demo：`python examples/run_experiment_agent.py`，qwen2.5:7b @ Ollama，判据见契约 §7 PA-14 与 §9.3；注意 S-2 的输出行口径）。全部通过并经用户批准后，由 Lead 提请将 PA 条目并入 `docs/ACCEPTANCE_CRITERIA.md`。
