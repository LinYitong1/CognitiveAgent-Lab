# QA 验收报告 — M0 项目脚手架

> 验收人：QA Agent ｜ 日期：2026-10-20 ｜ 依据：ACCEPTANCE_CRITERIA v1.2（M0 节 + 通用门禁节）、ROADMAP v1.2 M0 节、Backend 交接文档 `backend-m0-scaffold.md`
> 被验收交付：Backend M0（脚手架 + /health + 测试骨架 + check_layers + check.sh）
> 结论速览：**有条件通过**——6 项 PASS、1 项 PASS(等效)、3 项 ENV-BLOCKED（沙箱环境限制，非代码缺陷）、**0 项 FAIL、无退回项**

---

## 0. 环境限制声明（验收环境证据，先读）

本 QA 会话的宿主 Security Center 拦截所有 unlink/rename 操作，Python tempfile 探测失败（`No usable temporary directory found`），导致以下原文命令在本会话不可用，**均为环境限制，非代码缺陷**：

| 原文命令 | 实测失败证据 | 归因 |
|----------|--------------|------|
| 裸 `pytest` | exit=1，堆栈：`_pytest/capture.py:493 FDCapture.__init__ → TemporaryFile → FileNotFoundError`（FDCapture 启动即崩，未执行任何测试） | tempfile 被拦 |
| `pytest --cov` | exit=1，堆栈：`coverage/sqldata.py:913 erase → file_be_gone → os.remove(path)`（清理旧 .coverage 文件被拦） | os.remove 被拦 |
| `compileall -q src/` | exit=1，9 个文件全部 `*** Error compiling`；Security Center 拦截日志直接可见 `src/__pycache__/__init__.cpython-313.pyc.4381397456`（pyc 临时文件 rename 被拦） | pyc 原子写 rename 被拦 |

等效运行方式（已验证可行）：pytest 加 `--capture=no -p no:cacheprovider`；compileall 用内存 `compile()` 逐文件替代。各分项实测记录见下表。

---

## 1. 逐项验收结果

| ID | 实际命令 | 退出码 | 输出摘要 | 结论 |
|----|----------|--------|----------|------|
| M0-1 | 前置 `lsof -i :8000 -sTCP:LISTEN`（无占用，rc=1）→ 判据命令块原文执行（`.venv/bin/uvicorn src.api.app:app --port 8000` + 30 次就绪探测 + 标志位收尾 + kill $APP_PID） | 0 | `ok=1`；body 精确 `{"status":"ok"}`；kill 后 lsof 复查无监听（rc=1），进程清理确认；日志含 `Application shutdown complete` | **PASS** |
| M0-2 | ① 等效：`.venv/bin/python -m pytest --capture=no -p no:cacheprovider` ② 对照：裸 `.venv/bin/python -m pytest` | ① 0 ② 1 | ① `collected 1 item`、`tests/unit/test_health.py .`、`1 passed in 0.30s`（0 failed 且 collected=1，满足判据）② 崩于 tempfile（见 §0，测试逻辑未执行，与代码无关） | **PASS(等效)** |
| M0-3 | 判据命令块原文执行（`env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null .venv/bin/uvicorn src.api.app:app --port 8000` + 探测 + 清理） | 0 | `ok=1`；body 精确 `{"status":"ok"}`；双通道清理（unset + /dev/null 绕开 .env）下 `Application startup complete`；kill 后 lsof 复查无监听 | **PASS** |
| M0-4 | `.venv/bin/python -m pyright --version` | 0 | `pyright 1.1.414` | **PASS** |
| G-1 | `bash scripts/check.sh`（原文） | 1（聚合） | 分项报告：`[PASS] G-3`、`[PASS] G-4`、`[PASS] G-5a`；`[FAIL] G-1`（tempfile 崩溃，见 §0）、`[FAIL] G-2`（os.remove 被拦）、`[FAIL] G-5b`（pyc rename 被拦）——三个 FAIL 分项输出均可直接归因到 unlink/rename 拦截，无一条测试断言失败。**分项全部 PASS 无法在会话内确认**（G-2/G-5b 为 ENV-BLOCKED），聚合退出码必然非 0 | **ENV-BLOCKED**（待本地全绿确认；脚本结构核验见 §2） |
| G-2 | ① 原文：`.venv/bin/python -m pytest --cov=src --cov-report=term-missing`（经 check.sh）② 等效尝试：加 `--capture=no -p no:cacheprovider` | ① 1 ② 1 | ① tempfile 崩溃（见 §0）② 测试本身可通过，但 coverage 数据落盘阶段 `os.remove` 旧 `.coverage.*` 文件被拦（堆栈见 §0）——等效运行也无法完成 coverage 数据文件写入。M0 判据为"命令可运行不报错"（覆盖率阈值自 M1 生效），此项在本会话无法实测确认 | **ENV-BLOCKED** |
| G-3 | 判据命令块原文执行（grep + `rc=$?` + `[ "$rc" -eq 1 ]`） | 0（整块） | grep 无任何匹配输出，rc=1 → 整块退出 0，符合"rc=1 通过"语义 | **PASS** |
| G-4 | `.venv/bin/python -m scripts.check_layers`（原文裸命令，无需等效） | 0 | `[PASS] 分层依赖检查通过：无反向 import（api → services → agent → tools/storage，models/config 仅被引用）`，无违规输出 | **PASS** |
| G-5a | `.venv/bin/python -m pyright src/`（原文裸命令，无需等效） | 0 | `0 errors, 0 warnings, 0 informations` | **PASS** |
| G-5b | ① 原文：`.venv/bin/python -m compileall -q src/` ② 等效：内存 `compile()` 逐文件编译全部 9 个 src py 文件 | ① 1 ② 0 | ① 9 文件全部 `Error compiling`——Security Center 拦截日志直接显示 pyc 临时文件（`.pyc.4381397456`）删除被拦，非语法错误 ② `OK ×9`（`src/__init__.py`、`agent/`、`api/__init__.py`、`api/app.py`、`config.py`、`models/`、`services/`、`storage/`、`tools/`），`total=9, failed=0`——语法全部合法；但 pyc 落盘语义无法在会话内完成，原文命令 exit 0 待本地确认 | **ENV-BLOCKED** |

> 汇总：**PASS × 6**（M0-1、M0-3、M0-4、G-3、G-4、G-5a）｜ **PASS(等效) × 1**（M0-2）｜ **ENV-BLOCKED × 3**（G-1、G-2、G-5b）｜ **FAIL × 0**

---

## 2. check.sh 源码人工核验（E2E-4 前置要求）

对 `scripts/check.sh` 逐行审阅：

| E2E-4 要求 | 核验结果 | 证据（行号） |
|------------|----------|--------------|
| 覆盖 G-1+G-2+G-3+G-4+G-5a+G-5b 六项全部分项 | 满足 | L26-33（G-1/G-2）、L36-45（G-3）、L48-50（G-4）、L53-55（G-5a）、L58-60（G-5b） |
| 逐项独立执行 | 满足 | 六个分项各自独立命令段，互不短路 |
| 显式 `if` 判定退出码，不依赖 `set -e` 链 | 满足 | `set -u`（L5，非 set -e）；L28/33/50/55/60 `if [ $? -eq 0 ]`；G-3 三分支显式判定 rc=1/0/其他（L39-45），正确处理"rc=1 是通过态" |
| 无 `\|\|` 兜底 | 满足 | 全文无 `||` 形式的命令级兜底；report() 在 if 分支内调用，失败置 `overall=1` |
| 分项报告可归因（`[PASS]/[FAIL] 分项名`） | 满足 | 本会话实测三个 FAIL 分项均可从输出直接归因到 tempfile/rename 拦截（见 §1 表 G-1 行），实证"失败可归因" |
| 聚合退出码 = 任一分项失败即非 0 | 满足 | `overall` 初值 0，fail 分支置 1，`exit "$overall"`（L68）；本会话实测聚合 exit=1 与分项 FAIL 一致 |

**核验结论：check.sh 结构合规，满足 E2E-4 全部要求。** 遗留小问题见 §4 建议 1（硬编码 node 路径，非阻断）。

---

## 3. 静态核查结果

### 3.1 源码审查（文件:行 定位）

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 无硬编码密钥 | 通过 | `src/config.py:26-32` 全部字段默认空串/安全值；`src/api/app.py`、`tests/unit/test_health.py` 无任何密钥形态字符串；G-3 grep rc=1 佐证 |
| 无 M1 越界（agent loop / 工具） | 通过 | `src/agent/`、`src/tools/` 仅有 0 字节 `__init__.py`；全 src 无 loop/tool_call/白名单校验等实现代码 |
| 无 M2 越界（数据库表 / SSE） | 通过 | `src/storage/` 仅 0 字节 `__init__.py`；无 sqlite/create table/EventSource/text-event-stream 匹配 |
| `/health` 实现合规 | 通过 | `src/api/app.py:15-18` 精确返回 `{"status":"ok"}`，M0 无其他端点；L12 `get_settings()` 于 import 时加载（M0-3 实现依据） |
| 测试真实性 | 通过 | `tests/unit/test_health.py:12-15` TestClient 真实调用 /health，断言 200 + body 精确匹配（非空壳/0 collected） |
| check_layers 规则与契约一致 | 通过 | `scripts/check_layers.py:25-34`：api=0→services=1→agent=2→tools/storage=3（同值允许 tools↔storage 互引）、models/config 共享层不得引用业务层；ast 解析绝对+相对 import（L79-94）；与 ARCHITECTURE §3 / G-4 判据一致 |
| 配置实现与 §7 一致 | 通过 | `src/config.py:14` `CALC_AGENT_ENV_FILE` 路径覆盖（默认 .env，/dev/null 绕开）；Settings 七字段与 .env.example 一一对应；`allowed_hosts` property 解析逗号分隔白名单 |

### 3.2 配置与工程文件核对

| 检查项 | 结果 | 说明 |
|--------|------|------|
| `.env.example` vs ARCHITECTURE §7 | 一致 | 8 字段全对齐：CALC_AGENT_ENV_FILE / OPENAI_API_KEY / ANTHROPIC_API_KEY / LLM_BASE_URL / LLM_MODEL / CALC_AGENT_MAX_STEPS / HTTP_ALLOWED_HOSTS / DATA_SANDBOX_DIR，无缺失无多余 |
| `.gitignore` 覆盖 | 通过 | `.env`（L2）、`.venv/`（L5）、`logs/`（L8）、`*.db`（L13）均在；另含 `data/*`+`!data/.gitkeep`、`__pycache__/`、`.coverage(.*)`、`.DS_Store` |
| `pyproject.toml` 依赖白名单 | 通过 | runtime 6 项 + dev 4 项 = ARCHITECTURE §2.1 全部 10 项，无白名单外依赖；`[tool.pyright] venvPath/venv` 显式指向 .venv（Backend 交接文档问题 4 的修复确认生效，G-5a 0 errors 佐证） |

---

## 4. 总体结论

### M0：**有条件通过**（无代码缺陷，无退回项）

- **PASS 6 项 + PASS(等效) 1 项**：M0 全部四项运行时验收（M0-1~M0-4）在会话内真实通过（M0-2 经等效方式，测试逻辑与原文完全等价且原文失败输出已归因为环境问题）；G-3/G-4/G-5a 门禁裸命令原样通过。
- **ENV-BLOCKED 3 项**（G-1、G-2、G-5b）：全部归因宿主沙箱 unlink/rename 拦截，失败证据与拦截日志逐条对应（§0/§1），**未发现任何测试断言失败或代码层面错误**；其中 G-5b 语法合法性已经内存编译等效证明（9/9 OK）、G-1 中 pytest 分项经等效命令证明（1 passed）。
- **FAIL 0 项**：无退回 Backend 的修复要求。

### 待用户在本地终端运行的最终确认清单

以下命令在无沙箱限制的本地终端执行，预期全部通过即 M0 无条件通过：

```bash
# ① G-1 全量门禁（关键项：预期六项分项全部 [PASS]，聚合退出码 0）
bash scripts/check.sh

# ② G-2 覆盖率命令可运行（M0 判据：命令运行不报错即可；覆盖率阈值自 M1 生效）
.venv/bin/python -m pytest --cov=src --cov-report=term-missing

# ③ G-5b 语法编译（预期静默通过，exit 0）
.venv/bin/python -m compileall -q src/

# ④（可选复核）裸 pytest，M0-2 原文命令
.venv/bin/python -m pytest
```

> 若 ①~④ 在本地全部通过，M0 验收升级为无条件通过；若出现任何失败，按分项报告归因（预期不会——本会话所有失败点均为宿主拦截动作的直接结果）。

---

## 5. 风险与建议

1. **[建议·非阻断] `scripts/check.sh:13` 硬编码本机 managed node 绝对路径**（`/Users/linyitong/.workbuddy/binaries/node/versions/22.22.2-6/bin`）。在无此路径的机器上该 PATH 前缀失效（不致失败，但 node 兜底失效，pyright 可能因缺 node 不可用）。建议 M1 由 Backend 改为条件检测（存在才 export，或用 `command -v node` 判定后回退）。
2. **[移交 Lead] 项目根残留 tempfile 垃圾文件**：Backend 交接文档已知问题 2 所列 8 字符随机名文件 + `.coverage.*` 中间文件，且**本次 QA 会话实测又新增若干同类残留**（每条命令的 sitecustomize tempfile 探测产生）。Lead 提交前务必清理，且**禁止 `git add -A` / `git add .`**（.gitignore 未覆盖无后缀随机名文件，会被误入库）——按 Backend 建议 `git add` 显式路径清单。
3. **[无风险确认] M1 前置已就位**：`CALC_AGENT_ENV_FILE` 语义（config.py:14）、`allowed_hosts` 白名单解析（config.py:34-37）、pyright venv 配置均已按契约落地，M1 可直接开工。
4. **[口径说明] 本报告所有 PASS(等效)/ENV-BLOCKED 分类**均附原文命令失败输出作环境归因证据，未以等效通过掩盖原文失败；最终判定以用户本地运行 §4 清单结果为准。

---

## 验收记录附录（关键原始输出摘录）

```
# M0-1 / M0-3
ok=1 | body={"status":"ok"} | lsof_after_rc=1（端口清理确认）

# M0-2 等效
collected 1 item / tests/unit/test_health.py . / 1 passed in 0.30s / exit=0

# M0-4
pyright 1.1.414 / exit=0

# G-3（grep rc 语义）
final_rc=0（grep rc=1 无匹配 → 通过）

# G-4
[PASS] 分层依赖检查通过：无反向 import / exit=0

# G-5a
0 errors, 0 warnings, 0 informations / exit=0

# G-5b 等效
OK ×9（src 全部 py 文件内存编译）/ total=9, failed=0 / exit=0

# check.sh 分项
[PASS] G-3 无硬编码密钥 | [PASS] G-4 分层依赖正确 | [PASS] G-5a pyright 零错误
[FAIL] G-1 pytest 全绿 | [FAIL] G-2 覆盖率命令可运行 | [FAIL] G-5b compileall 通过
（三个 FAIL 均归因 §0 环境拦截；聚合 exit=1）
```
