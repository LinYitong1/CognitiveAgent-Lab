# QA 审查报告 — 实验工具扩展设计提案 v2（纯文档审查）

> 审查人：QA Agent（docs/AGENT_ROLES.md §4）｜ 日期：2026-10-20
> 被审对象：`docs/proposals/experiment-tools-design-proposal.md`（v2，688 行，Architect 按用户 6 点意见修订）
> 审查方式：纯文档静态审查（无代码可运行）——v1/v2 全文对比（`git show 63f5dcd` 只读）、逐示例手工复算、M1 接口签名与真实源码逐行核对（M1 验收期间的逐行审计记录 + 本轮行号复核）
> 约束遵守：未修改提案本身；未执行任何 git 写操作。

---

## 总体结论：**有条件批准**

6 点修订全部真实落地（A1/A2/A4/A6 完整落实，A3 数字复算全部正确，A5 基本落实），核心架构（通用 combinator 为核心 + 插件纯可选、双 spec 解耦、确定性契约）与产品边界一致，M1 签名引用逐行核实准确。**但发现 3 项 Major**：均为 v2 新增内容之间的内部矛盾或协议缺口（文档级修订可修，不动架构）——修正后即可批准，无需退回重写。

| 级别 | 数量 | 编号 |
|------|------|------|
| Blocker | 0 | — |
| Major | 3 | MA-1（ITERATION_STALLED 阈值与测试脚本矛盾）、MA-2（序列型插件覆写与"统计由核心保证"矛盾）、MA-3（序列型约束校验通道缺失，范式知识有泄漏进核心验证器之虞） |
| Minor | 7 | MI-1 ~ MI-7 |
| Suggestion | 4 | SG-1 ~ SG-4 |

---

## A. 六点修订落实度（逐项证据）

### A1 通用生成器 vs paradigm plugins —— **落实**

| 检查点 | 证据 | 判定 |
|--------|------|------|
| 核心 combinator 明确为系统必经路径 | §5.2 标题即"系统核心"，"纯函数，零范式知识，直接由 factors/levels/blocks/constraints 驱动"（L402）；§② 红线"核心 schema、验证器、通用组合生成器中零范式/零理论名词"（L51） | ✓ |
| paradigm=None 全功能可用 | v1 中 `paradigm: str` **必填**（v1 §4 schema），v2 改为 `paradigm: str \| None = None`（L243，注释"None = 纯通用路径（核心，无需任何插件）"）；§5.3 冻结规则"系统的可用性不依赖任何插件：核心路径对全部用户始终可用"（L458）；新增 §4.2 纯通用示例（cueing-generic，paradigm: null）端到端证明；§8.5 `test_generic_path_no_plugin_end_to_end` + EX-8 验收项固化该证据 | ✓ |
| 插件纯可选（enhancement 非 dependency） | §5.3 节标题即"enhancement，非 dependency"；`spec.paradigm is None` → "不触碰任何插件代码"（L456）；插件未注册 → `UNKNOWN_PARADIGM`（"此错误只表示声明了但环境没有"，L499） | ✓ |
| 是否存在"必须先有插件才能跑"的暗示 | 未发现。UNKNOWN_PARADIGM 语义、§4.2 示例、EX-8 均反向佐证 | ✓ |
| Stroop/N-back 严格限于示例身份 | L29（范围声明）、L54（"样例代码，不是系统组成部分"）、§4.3/4.4 标题"可选插件示例"、L460（"不是系统部件"）、§⑩.2 治理开放问题（"以免被误认为官方范式支持"） | ✓ |

### A2 ExperimentSpec / GameSpec 分离 —— **落实**

| 检查点 | 证据 | 判定 |
|--------|------|------|
| 职责边界表清晰无重叠 | §4.0 十行关注点逐一归属（L184-195）：因素/序列/正确性/计时/响应归实验层；键位/反馈/场景/流程/游戏化归表现层——无一行双属 | ✓ |
| 字段归属体现解耦 | ExperimentSpec（L201-250）实际字段全部落在边界表"✅ 实验层"侧，无 feedback/scene/input 等表现字段混入；GameSpec（L337-379）全部落在"✅ 表现层"侧，无条件分配/试次生成/正确性判定字段——双向核对无漏网 | ✓ |
| GameSpec 引用而非复制 | `ExperimentRef`（L337-342）仅携带 name/version/seed + 双 fingerprint，不复制试次或实验内容；§7.2 "游戏端加载时校验 ref 与 Bundle 一致才启动" | ✓ |
| 跨 schema 校验 | `input.bindings` 只能引用 ExperimentSpec 已声明的 `responses` 名（L381） | ✓ |

### A3 示例约束冲突修正 + 手工复算 —— **数字全部正确；发现 1 项归因矛盾（MA-2）**

**C1/C2/C3 规则定义**（L494-497）：C1 互斥（balance+ratios → `CONSTRAINT_CONFLICT` 错误）、C2 覆盖警告（balance+weight≠1.0 → `WEIGHT_IGNORED`）、C3 有效权重（balance=false 时 ratios > Level.weight，ratios 和容差 1e-6 否则 `RATIO_SUM`）——定义清晰、优先级明确。v1 的冲突示例（v1 §4.1 Stroop 同时 balance=true + ratios 0.34/0.33/0.33）已在 v2 §4.3 中移除。✓

**逐示例手工复算**（QA 独立复算，非采信自查表）：

| 示例 | 复算 | 判定 |
|------|------|------|
| §4.2 通用 | 2 因素×2 水平=4 组合 ✓；balance=true 无 ratios 无显式 weight → C1 无冲突、C2 无警告 ✓；practice 8=4×2 ✓、main 80=4×20 ✓、总计 88 ✓、每组合 22（2+20）✓；水平频数 valid=22×2=44 ✓（同理 44/44/44） | **全部自洽** |
| §4.3 Stroop | congruency(2)×ink_color(3)=6 组合 ✓；balance=true 无冲突 ✓；practice 12=6×2 ✓、test 96=6×16 ✓、总 108 ✓；test 内 congruent=3 组合×16=48 ✓、ink red=2 组合×16=32 ✓（48/48、32/32/32） | **全部自洽** |
| §4.4 N-back | 单因素 weight 0.3/0.7，balance=false 无 ratios → C3 有效权重=weight ✓ C1 无冲突 ✓；120×0.3=36、120×0.7=84，36+84=120 精确整数（零余数）✓；"前 n=2 个必然 nonmatch"占 nonmatch 名额、总频数不变 ✓；trial_count 120 ≥ n+1=3 ✓ | **数字自洽**（但归因表述错误，见 MA-2） |
| §7.1 vs §4.2 | spec 节字段值一致（seed 11/balance/8+80/timing 400/null/800，省略字段均为 Pydantic 默认值、语义等价）✓；summary 88/44/44/44/44 ✓；allocation main 每组合 20 ✓ | 一致（allocation 缺 practice 块与指纹占位值不一致，见 MI-1/MI-2） |
| §3.1/§3.2 输出示例 | stats trial_count 88、frequency 44/44/44/44、plugin_used null——与 §4.2 对齐 ✓（v1 此处是 stroop 的 96/48/48/32/32/32，v2 已同步改写） | 一致 |
| §8.2 断言 vs §4 | 88/各水平 44、96 内 48/48/32/32/32、36/84——三个示例的断言数字与 spec 数字逐一吻合 ✓ | 一致 |

**MA-2（Major）**：§4.4 自洽性称"120 试次 × 0.3 = 36 …（**largest remainder 零余数**，无舍入）"（L332），§8.2 同样把 N-back 频数精确性归因于 largest remainder——但 N-back 是**序列型插件**：§5.3 `generate_sequence` 返回 list 时"**覆写整个试次构造**"（L450），核心 combinator 的 largest remainder 分配路径根本未执行；match 位点由插件自行安排，36/84 的精确性是插件遵守 weight 意图的结果，非核心算法保证。这与 §5.3 冻结声明"插件不能修改因素分配、约束执行、频数统计——统计性质永远由核心计算（插件无法破坏平衡性）"（L459）直接矛盾：覆写整个试次构造的序列型插件当然"能"偏离任何频数（核心至多事后统计、无法事前强制）。**建议修法**：§5.3/§4.4 区分两类插件语义——derive 型"因素分配与频数由核心强制"；sequence 型"频数由插件按 weight 实现、核心**事后校验**（生成后频数与有效权重推出的期望数偏差超容差 → 验证错误）"，§4.4/§8.2 的归因表述同步改为"插件按 0.3/0.7 安排位点，核心事后断言 36/84"。

### A4 可重复性契约 —— **落实**（附 1 项 Suggestion）

| 检查点 | 证据 | 判定 |
|--------|------|------|
| 导出包内嵌完整原始 spec（含 seed） | §5.4 契约四要素表（L464-471）+ §7.1 `spec` 节完整内嵌（v1 是"元信息投影，完整 config 不重复内嵌"——v2 明确反转，L572"不再以元信息投影省略"） | ✓ |
| engine_spec_version | 定义明确为"算法规范的语义版本，**非代码哈希**"——跨实现可复现的锚点（L469）；出现在 validate/generate 输出与导出包 | ✓ |
| plugin 版本 | `plugin_used` "stroop@1.0" 格式（L470）；纯通用路径 null | ✓ |
| fingerprint | 双 fingerprint（config + trials），sha256(canonical JSON)[:8] | ✓ |
| 独立验证两路径可操作 | 路径 1 重生成：同 spec+seed+兼容版本 → 比对 trials_fingerprint（输入=导出包 spec 节，闭环成立）；路径 2 仅验证：对导出包 trials 数组做 canonical JSON sha256 == 包内指纹（无需生成器实现，完整性校验）——两条均可操作 | ✓ |
| canonical JSON 规范 | 冻结：`sort_keys=True, ensure_ascii=False, separators=(",", ":")` + float 最短往返 + 禁 NaN/Inf + 随 engine_spec_version 版本化（L473） | ✓ |
| 第三方复现歧义点 | 见 SG-1：跨**语言**实现复现还隐含要求复刻 `random.Random` 的 MT19937 初始化/字符串种子 sha512 派生/shuffle 消费序，以及 float 最短往返在不同语言实现间的边界差异——§⑩.5 已自觉提出 conformance 向量集但列为开放问题 | 部分（Suggestion） |

### A5 无理论硬编码 —— **基本落实**（发现 1 项 Major：MA-3）

**全文扫描结果**：

| 扫描对象 | 结果 |
|----------|------|
| 核心 schema（§4.1） | 全部为通用结构（因素/水平/权重/比例/约束/块/计时/响应），无范式名词；paradigm/paradigm_params 为自由字段（"核心引擎不解释其内容"，L252）✓ |
| 验证规则与错误码（§6.1） | 10 个错误码 + 2 个警告码均为通用机制；无"颜色命名"类范式专属校验 ✓ |
| 生成器算法（§5.2） | 9 条全为通用机制（笛卡尔积/largest remainder/filter/shuffle/拒绝采样）✓ |
| 理论假设 | Bayesian/evidence sampling 等仅出现在"不内嵌"声明（L53），零实现痕迹 ✓ |
| 范式词出现位置（grep 全文） | 全部位于：红线声明、示例（示例身份明确）、插件协议注释、指纹格式示意、测试断言（引用示例）、治理开放问题、变更记录——无一处进入核心逻辑 | ✓ |
| **例外发现** | §6.1 `CONSTRAINT_INFEASIBLE` 括号注释"（**序列型含 trial_count < n+1**）"（L499）+ §4.4"验证器以此校验 trial_count ≥ n+1"（L332）+ §8.3 对应拒绝测试（L616）——见 MA-3 |

**MA-3（Major）**："trial_count ≥ n+1"校验中 `n` 是 N-back 的 `paradigm_params.n`——若由**核心** validation.py 执行该校验，核心必须理解 `n` 的序列语义，即 N-back 范式知识泄漏进核心验证器，违反 §② 红线；而 §5.3 `ParadigmPlugin` 协议只有 `derived_fields / derive / generate_sequence` 三个方法，**没有 validate 钩子**——插件没有参与验证的通道（§3.2 还明确"实现上直接复用同一验证函数"，进一步排除了插件侧验证）。文档内部逻辑倾向核心验证器做全部校验 → 与红线冲突。**建议修法**：`ParadigmPlugin` 协议增加 `validate(spec) -> list[ValidationIssue] \| None` 钩子，核心验证器在通用校验后调用被声明插件的该钩子并合并结果——范式知识留在插件层，红线闭合，§4.4/§8.3 的校验有了可实现通道。

### A6 M1 零改动 —— **落实**

| 检查点 | 证据 | 判定 |
|--------|------|------|
| §⑨ 明确零修改 | "M1 既有文件零修改，仅新增文件（v2 重申，全文无任何要求改动 M1 的表述）"（L650）；"不改"清单覆盖全部 M1 文件（L658） | ✓ |
| 有无暗示改 M1 接口 | §3.4 "不动 src/agent/__init__.py"；§6.2 零改动论证；两个注意点（check_layers 一行扩展、_sandbox_io.py 新文件）均诚实声明为"门禁配置变更/新文件"，**不触碰 M1 代码**——且 QA 核实 `scripts/check_layers.py` 确为显式 `LAYER_ORDER` 白名单实现（M0 交付，QA 在 M1 验收时已逐行审计），"需要一行规则扩展"分支为实情，提案的预判准确 | ✓ |
| ToolSpec 字段引用 vs 真实代码 | 提案头部 L8 与 `src/models/tool_spec.py` 逐字段一致：name/description/`input_model: type[BaseModel]`/`idempotency: Literal[...]`/`risk_level: Literal[...]`/`executor: Callable[[BaseModel], Awaitable[ToolResult]]` + `effective_idempotency(args)` ✓ | ✓ |
| registry 行为引用 | "register(spec) -> None（校验失败抛 ToolRegistryError）" ✓；"execute 未知工具/参数校验失败/executor 异常一律返回 ToolResult(ok=False) 不外抛" ✓；引用行号 `registry.py:24-33` 经本轮 sed 复核**精确吻合**（L24 register 起至 L33 async executor 校验止） | ✓ |
| AgentLoop 终态语义引用 | `run_task(goal)`/ERROR: 前缀回传/max_steps 硬上限/final 必发 ✓；引用行号 `loop.py:129-144`（execute → ToolResult → tool message，ok=True 时 content=result 原文）经本轮 sed 复核**精确吻合** | ✓ |
| 分层方向 | `agent → tools → experiment → models/config`（L60）；experiment_registry.py import 同包 build_registry——check_layers 同层互引合法 ✓ | ✓ |

---

## B. 文档内部一致性

| 检查点 | 结果 | 判定 |
|--------|------|------|
| **术语统一**：ExperimentConfig 残留 | grep 全文仅 4 处：L20（"v1 名为 ExperimentConfig，v2 统一命名"）、L238（schema 注释，同上）、L679/L684（变更记录）——**全部为刻意的历史说明**，标题/正文/示例/代码块中无一处以 ExperimentConfig 作现行名 | ✓ |
| 错误码闭环：C1/C2/C3 → 枚举 | C1→`CONSTRAINT_CONFLICT`（枚举在列，L499）✓；C2→`WEIGHT_IGNORED`（警告码在列）✓；C3→`RATIO_SUM`（枚举在列）✓；`ITERATION_STALLED` 在枚举且 §8.5 有测试 ✓ | ✓ |
| `MUTEX_VIOLATION` 测试闭环 | 枚举在列（L499），但 §8.2/8.3 **无 mutually_exclusive 违规/不可满足的对应测试用例**（§8.2 只测 max_repeat） | **MI-3** |
| §8 断言数字 vs §4 示例 | 三个示例的频数断言逐一吻合（88/44×4；96 内 48/48/32/32/32；36/84）✓；v1 §8.2 的 nback 容差断言（±0.05）已升级为精确整数断言 ✓ | ✓ |
| §6.3 阈值 vs §8.5 测试 | **矛盾（MA-1，见下）** | ✗ |
| 变更记录 v1→v2 vs 实际修订 | 逐条与 v1 diff 核对：7 条全部对应真实修订（paradigm 必填→可选、新增 §4.2/红线/边界表/GameSpec/Bundle、C1-C3、四要素契约、错误码补齐、stats 示例 96→88 等）——无虚报 | ✓ |

**MA-1（Major）**：§6.3 协议层去重阈值为"当前验证的 errors 与 `previous_errors` 的**交集 ≥ 3 个指纹**"（L526）；而 §8.5 `test_design_iteration_stalled` 的脚本是"**三次提交含同一错误的 spec**（带递增 previous_errors）→ 第三次收到 ITERATION_STALLED"（L631）。手工推演：同一错误 = **单个** error_code:path 指纹。第 1 次提交 previous_errors=[]（交集 0）→ 第 2 次 previous_errors=[f1]、当前 errors=[f1]（交集 1）→ 第 3 次 previous_errors=[f1]（交集 1）——**无论按 distinct 还是 multiset 计数，单指纹重复提交的交集永远 ≤ 2 < 3，测试在数学上不可触发**（§6.3 层 2 软引导"同一验证错误出现 2 次即应大幅修改"也暗示协议阈值语义应为"重复 2 次"而非 3 个不同指纹）。**建议修法**（二选一，保持 §6.3 与 §8.5 同步）：① 阈值改为"任一 error_code:path 指纹在 previous_errors 中已出现 ≥ 2 次 → stalled"（与软引导语义对齐，§8.5 脚本不变）；② 保持"交集 ≥ 3"但 §8.5 脚本改为"提交含 3 个不同验证错误的 spec，连续重复 → 第 2 次即 stalled"。

---

## C. 范围控制

| 检查点 | 证据 | 判定 |
|--------|------|------|
| 是否滑向游戏引擎 | GameSpec 全部为声明式结构：`layout` 自由字符串（解释权留给未来游戏端）、`feedback.on_response` 三值枚举、`flow` 布尔/枚举、`gamification` 布尔开关——无物理/精灵/关卡/机制 DSL；§① 明确排除"GameSpec 的具体游戏机制 DSL"；§⑦.2 "不实现游戏、不设计游戏机制 DSL 的深层细节" | ✓ 克制 |
| 是否开发特定范式 | 插件只给 Protocol 签名与职责文字描述（§5.3），无 stroop/nback 完整实现代码；两示例仅作表达力验证；分发治理（随仓库 vs 独立 examples）作为 §⑩.2 开放问题留给用户 | ✓ |
| M2/前端越界 | §⑩.7 刻意不设计 M2 交互；GameSpec 产出通道列为 §⑩.1 开放问题 | ✓ |

---

## 问题清单

### Major（批准前必须修，均为文档级修订，不动架构）

| # | 问题 | 位置 | 修复建议 |
|---|------|------|----------|
| MA-1 | ITERATION_STALLED 阈值（交集 ≥3 指纹）与 §8.5 stalled 测试脚本（三次提交同一错误=单指纹）数学上不可触发，冻结契约内部矛盾 | §6.3 L526 vs §8.5 L631 | 阈值改"任一指纹重复出现 ≥2 次"（与软引导语义对齐），或测试脚本改"3 个不同错误重复提交"——两处同步 |
| MA-2 | §5.3"插件不能修改频数统计（无法破坏平衡性）"与 `generate_sequence` 序列型覆写整个试次构造直接矛盾；§4.4/§8.2 把 N-back 频数精确性归因于核心 largest remainder 是错误归因（序列型根本不走该路径，36/84 是插件按 weight 安排位点的结果） | §5.3 L459 / §4.4 L332 / §8.2 L608 | §5.3 区分两类插件语义：derive 型频数由核心强制；sequence 型频数由插件实现、核心**生成后校验**（偏差超容差 → 验证错误）；§4.4/§8.2 归因表述同步修正 |
| MA-3 | "序列型 trial_count ≥ n+1"校验无合规实现通道：`ParadigmPlugin` 协议无 validate 钩子，核心验证器执行则范式知识（n 的语义）泄漏进核心，违反 §② 通用性红线 | §6.1 L499 / §4.4 L332 / §5.3 L442-452 | 协议增加 `validate(spec) -> list[ValidationIssue] \| None` 钩子，核心验证器调用被声明插件并合并结果 |

### Minor（建议修）

| # | 问题 | 位置 | 建议 |
|---|------|------|------|
| MI-1 | 同一 §4.2 spec 的 config_fingerprint 占位值不一致：§3.1 示例 `9f3ab2c1` vs §7.1 示例 `1a2b3c4d`（同 spec 应同指纹；§3.2/§7.1 的 trials_fingerprint `5d21e0f7` 倒是统一的）——会误导实施者 | L86 / L552 | 占位值统一，或注明"示意值" |
| MI-2 | "spec 节 = 原始 ExperimentSpec **完整原文**"（L572）与 §7.1 示例省略默认字段（paradigm_params、factor_filter、shuffle_within）不符——省略是 Pydantic 语义等价但非"原文"；且省略与否影响 canonical JSON 的逐字节形态 | L540-549 vs L572 | 措辞改"规范化后的完整 spec（默认值可省略，fingerprint 对解析后对象计算）"或示例补全字段 |
| MI-3 | `MUTEX_VIOLATION` 在错误码枚举中，但 §8 测试策略无 mutually_exclusive 对应用例 | L499 vs §8.2/8.3 | §8.3 补一条 mutex 拒绝/不可满足测试 |
| MI-4 | `TRIAL_COUNT_MISMATCH` 语义模糊（"blocks 总数与约束推出数不符"）——largest remainder 可处理任意 trial_count，无自然触发场景定义；§8.3 有测试条目但无对应可构造输入 | L499 / L616 | 明确触发定义（如"factor_filter 过滤后某 block 的组合权重全为零"），或从枚举删除 |
| MI-5 | `BlockSpec.name` 无唯一性约束——§5.1 子流派生键 `f"{seed}:block:{block.name}"` 在同名 block 下碰撞（两块共享同一随机流） | L227-231 / L392 | 验证器增加 block 名唯一性校验（SCHEMA_INVALID 或新增码） |
| MI-6 | C2 警告只覆盖 balance=true 分支；balance=false 时"ratios 声明的因素上显式 Level.weight 被静默忽略"无对应警告 | L496-497 | WEIGHT_IGNORED 警告条件扩展至 ratios 覆盖 weight 的情形 |
| MI-7 | §7.1 `allocation` 只列 main 块、缺 practice——按 block 为键的 per-block 口径未在格式契约中明示，示例不完整 | L558 / L573 | 明示 allocation 口径（per-block）并补 practice 条目（每组合 2） |

### Suggestion（供 Architect 参考，不构成批准条件）

| # | 建议 |
|---|------|
| SG-1 | 跨语言实现复现的隐含负担未在 §5.4 契约中点明：第三方实现须复刻 `random.Random` 的 MT19937 初始化/字符串种子 sha512 派生/shuffle 消费序，且 float 最短往返表示在不同语言间存在边界差异。建议将 §⑩.5 的 conformance 测试向量集（一组权威 spec→canonical_json→fingerprint 三元组）**从开放问题升格为 engine_spec_version 1.0 的发布必选**——对"独立、开源、跨实现可复现"的产品目标，这是刚需而非增强 |
| SG-2 | `GameSpec.game: dict[str, str]`（name/version 用弱类型 dict）——升格正式契约时建议改嵌套模型（`game_name: str` + `game_version: str` 或子模型），获得 Pydantic 校验 |
| SG-3 | §5.3 `PLUGINS = {}  # 注册表初始为空；stroop/nback 作为随仓库分发的示例插件注册`——"初始为空"与"示例插件注册"并读易歧义（运行时默认注册集到底是什么），建议澄清为"PLUGINS 代码初始为空 dict，示例插件模块在 import 时自注册；最终运行时是否默认装载示例插件由 §⑩.2 治理决策定" |
| SG-4 | §4.4 中 `max_repeat: 3` 被序列型插件解释为"同一**字母**连续呈现上限"——通用约束字段（语义为"同一**水平**连续出现上限"）被插件重载使用，建议在插件协议文档化"插件对通用约束字段的语义映射"边界，避免实现期歧义 |

---

## 审查方法与局限说明

- **对比基线**：v1 经只读 `git show 63f5dcd:docs/proposals/experiment-tools-design-proposal.md` 全文读取，逐节比对修订。
- **手工复算**：§4.2/4.3/4.4 三个示例的组合展开、频数分配、整除性、约束合规，及 §3.1/§3.2/§7.1/§8.2 与 §4 的交叉一致性，全部由 QA 独立复算（非采信 Architect 自查表）。
- **M1 签名核对**：提案引用的 `registry.py:24-33`、`loop.py:129-144` 经本轮 sed 逐行复核精确吻合；ToolSpec/execute/终态语义以 M1 验收期间 QA 逐行审计记录为准。
- **局限**：本提案为纯设计文档，所有"可实施性"结论基于逻辑推演；实施期（若获批）须以正式契约评审 + EX-1~EX-8 验收实证复检本文全部断言（尤其确定性/跨进程稳定性/统计断言）。
