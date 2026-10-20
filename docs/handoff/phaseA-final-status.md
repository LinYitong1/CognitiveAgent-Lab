# Phase A 最终状态与遗留问题清单

- **文档性质**：Phase A 验收状态汇报（含 2026-10-20 20:30 后的独立复验记录）。**本轮未修改 M1 / Phase A 任何已验收代码，未启动 Phase B。**
- **提交人**：Lead Orchestrator（依据 QA 报告、Demo 报告与本轮独立复验）
- **基线**：Phase A commit `45c42c1`（M1 基线 `ae8dd68` 零修改，仅 2 处 Architect 批准的配置扩展）
- **配套决策记录**：用户 D1~D5 决策（2026-10-20）见 §5

---

## 1. PA-1 至 PA-14 实际通过状态

| ID | 内容 | 状态 | 依据 |
|----|------|------|------|
| PA-1 | schema 校验（V1~V9 冻结验证器） | **PASS** | 18 tests；QA 报告 §1 |
| PA-2 | 确定性生成（同 seed 逐字节一致 / 跨 PYTHONHASHSEED / block 隔离 / 重生成一致） | **PASS** | 4 tests + QA 独立四份输出 sha256 全同 |
| PA-3 | 约束校验（C1/C2/C3、UNSAT 码全枚举） | **PASS** | 23 tests + QA 9 场景探针实测 |
| PA-4 | canonical JSON（五参数 / NaN 拒收 / 中文往返） | **PASS** | 4 tests |
| PA-5 | SHA-256 指纹（完整 64 hex / 期望向量独立重算） | **PASS** | 6 tests + 系统 shasum 外部交叉验证 |
| PA-6 | UNSAT vs SEARCH_EXHAUSTED 语义分离 | **PASS** | 2 tests（SEARCH_EXHAUSTED 为契约声明的弱断言，真实触发随 Phase B max_repeat 进入，无夸大） |
| PA-7 | 工具注册与错误契约（20 条截断 / 域错误 vs 工具错误） | **PASS** | 6 tests |
| PA-8 | **FakeLLM 全链路 Demo（迭代设计→生成→导出→指纹验证）** | **PASS** | 集成测试断言：completed + Bundle 落盘 + trials_fingerprint 一致 + verify CLI 子进程 exit 0 + 迭代证据（CONSTRAINT_CONFLICT→修正）+ 频数精确整数 |
| PA-9 | ITERATION_STALLED 防死循环协议 | **PASS** | previous_errors 累积 [] → [f1] → [f1,f1]，三轮判定 false/false/true，终止且未导出 |
| PA-10 | max_steps 守卫 | **PASS** | failed + "max steps" + calls==max_steps + 事件尾序 [error, final] |
| PA-11 | export 沙箱五步规则 | **PASS** | 5 tests（traversal/symlink/prefix/oversize/success） |
| PA-12 | 分层与静态守卫（无 random 模块级调用 / 无范式硬编码） | **PASS** | check_layers PASS + 6 tests + grep 零命中（stroop/n-back/flanker 等） |
| PA-13 | 黄金文件逐字节稳定 | **PASS** | verify CLI exit 0 + 外部 shasum 三指纹交叉一致 + QA 自写标准库脚本 48/48 试次独立复现 |
| PA-14 | 真实 LLM Demo（qwen2.5:7b 全链路导出） | **❌ 未达成（0/5）** | Demo 报告：5 次运行如实记录，无 Bundle 导出；根因=模型能力边界，非引擎缺陷（见 §3） |

**汇总**：PA-1~PA-13 全部通过；PA-14 未通过。全量回归 **122/122**（本轮 20:30 复验再次通过，20.39s）。

## 2. 三项核心问题的核实结论

### 2.1 FakeLLM 全链路 Demo —— 已完成
PA-8 集成测试（`tests/integration/test_experiment_agent.py`）证明完整闭环真实可运行：**验证失败（CONSTRAINT_CONFLICT）→ 模型修正 → 验证通过 → generate_trials → export_experiment 落盘 → verify CLI 独立子进程校验指纹 exit 0**。无 API key 可跑（`env -u OPENAI_API_KEY` 下 7 passed），是系统正确性的背书基线。

### 2.2 真实、可重复验证的 ExperimentBundle —— 已产生
三层证据：
1. **仓库内黄金文件** `tests/golden/generic-2x2-seed7.json`（48 试次，双指纹 + bundle_sha256 全量三指纹）；
2. **本轮独立复验（2026-10-20 20:35）**：从黄金文件中的 spec 现场调用 `build_bundle` 两次，两份产物逐字节一致，且与已提交黄金文件**完全相等**；bundle_sha256 = `96f33202571fc486026c0a317b45fd670c607575275af5de1e1cad6c27b3ad24`、trials_fingerprint = `7cb993c4…d6c0b`，与 QA 报告记录值一致；
3. **QA 历史独立验证**：系统 `shasum -a 256` 外部重算三指纹一致 + 自写标准库脚本（不 import 被验代码）48/48 试次全序列独立复现 + PYTHONHASHSEED=1/2 子进程收敛同一逐字节结果。

`python -m src.experiment.verify <path>` 任何人可独立复验（本轮再次 exit 0）。

### 2.3 未解决的阻断性问题 —— 1 项（PA-14）
唯一阻断项即 PA-14 本身。**引擎、工具、AgentLoop、指纹体系均无缺陷**（Run 2/5 中错误 spec 的结构化拒绝全部按契约工作）；失败全部发生在"qwen2.5:7b 构造正确 ExperimentSpec"这一环节。次要遗留（不阻断验收）见 §4。

## 3. PA-14 三项修复选项分析

五次运行失败模式：环境 A（冷启动超时）×2 —— **已解决**（预热实践，Run 4/5 无超时）；模型 B（spec 结构猜错：`inputs`/`experimentSpec` 错误包装，错误消息已列全缺失字段但 7B 未采纳修正）×2；模型 C（空响应终止）×2。

| 选项 | 解决什么问题 | 代价/影响 | 与约束的关系 |
|------|-------------|-----------|--------------|
| **A. 工具自描述补全**（修订契约 §5.2：validate_experiment description 增加 ExperimentSpec 顶层结构摘要 + 最小示例） | **失败模式 B 的根因**：宽松 `config: object` 输入使模型在 tools schema 中完全看不到 spec 内部结构，只能盲猜。补全后模型不再猜结构 | 属 Phase A 契约修订（非 M1 接口）；需 Architect 改契约 + QA 复核 + 重跑 PA-14；**判据不放宽** | 与 D1（保留 7b、不放宽标准）完全兼容 |
| B. 更强模型（qwen3:8b / 14b / 未来更强） | **失败模式 B 的模型侧能力**：强模型可凭两级错误契约自行迭代修复嵌套 schema | 重新拉模型（14b 约 +9GB）+ 重跑冒烟 | **已被 D1 排除**（暂不升级） |
| C. 接受现状 | 不解决技术问题，仅登记缺口：PA-14 记"7b 能力受限未达成"，系统正确性由 PA-8 背书，待更强模型补验 | Phase A 验收留缺口 | 与 D1"如实报告成功与失败"字面兼容，但未利用已知根因 |

**推荐的最小修复方案：选项 A**（必要时叠加 C 作为兜底记录）。理由：
1. 直接命中已定位根因（工具 schema 自描述不足是设计代价，补全属工程正当完善，不是替模型代劳——模型仍需真实完成 validate→generate→export→指纹验证全链路，所有 PA-14 判据原样保留）；
2. 与 D1 决策（保留 7b、FakeLLM 门槛、不放宽标准）零冲突；
3. 改动面最小：一处工具 description 文本 + 契约 §5.2 修订 + QA 复核 + PA-14 重跑（预热实践已就绪，环境 A 已排除）；
4. 若 A 实施后 7B 仍不可靠，按 D1 口径如实记录（回落到 C），FakeLLM（PA-8）作为验收门槛的地位不变。

**待用户批准后执行；本轮未实施任何修复。**

## 4. 遗留问题清单（全部不阻断）

| # | 类别 | 问题 | 处置建议 |
|---|------|------|----------|
| L-1 | 验收缺口 | PA-14 未达成（唯一阻断项） | 选项 A 修复后重跑；或按 C 登记（用户决策） |
| L-2 | Minor | verify CLI 失败 detail 同时输出 stdout+stderr（冗余） | Phase B 顺手收敛 |
| L-3 | Minor | 契约 §3.4 "零 set 构造"措辞与实现不完全一致（生成路径零 set 属实；验证层 set 仅成员判断不迭代，确定性不受影响） | Architect 下版契约精确化措辞 |
| L-4 | Minor | stalled 追加的 ITERATION_STALLED 理论上可使 errors 达 21 条（>20 截断上限） | Architect 备案裁定 |
| L-5 | 契约矛盾 | §5.3"两处文件头" vs §8.1"禁改 file_write.py"（Backend 已按文末清单裁定执行，QA 接受） | Architect 下版消除矛盾 |
| L-6 | 风险登记 | Ollama 冷启动（空闲 5 分钟卸载）超 LLMClient 60s×3 窗口 | 预热实践已固化（零改动缓解）；LLMClient 超时不可配属 M1 冻结 |
| L-7 | 风险登记 | 空响应被判 completed 的 M1 语义（模式 C） | M2 恢复/重试语义设计时考虑，不改 M1 |
| L-8 | 风险登记 | previous_errors 防死循环协议依赖模型主动传参，7B 不带、框架无兜底消费 | Phase B 评估框架侧指纹记忆 |

## 5. 用户决策记录（2026-10-20，D1~D5）

- **D1**：保留 qwen2.5:7b 不升级；FakeLLM 集成测试为必须通过的验收门槛；真实 7B 测试如实报告成败，不放宽标准。
- **D2**：MVP 轻量浏览器自检（不将静态 HTML 检查视为真正可玩性验证）；后续增加自动化浏览器交互测试。
- **D3**：第一版网页游戏限定 Demo/Prototype，不宣称科研级计时精度，不用于正式采数。
- **D4**：结构化 GameSpec 生成与验证流程，复用 AgentLoop / Tool Registry，不加多 Agent Runtime。
- **D5**：Phase A 最终验收完成后启动 Phase B，不提前开发。

## 6. 结论与请求裁定事项

**Phase A 状态：PA-1~PA-13 通过（含 FakeLLM 全链路与真实可复现 Bundle）；PA-14 未达成，唯一阻断项。**

请用户裁定：
1. **PA-14 处置**：批准选项 A（工具自描述补全 + 契约 §5.2 修订 + QA 复核 + PA-14 重跑，判据不放宽，实施仍遵守"本轮不动已验收代码、修复作为契约修订单独提交"流程）？还是按选项 C 正式登记缺口、宣告 Phase A 验收完成？
2. 无论选 A 或 C，**是否宣告 Phase A 正式验收关闭**（据 D5，Phase B 在此之后启动）。

—— 报告提交即止，停止等待批准，不自动进入任何下一阶段。
