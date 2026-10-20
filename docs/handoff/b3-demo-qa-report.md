# B3 QA 报告 — 端到端 Demo 验收与 GitHub 开源准备

> 作者：QA（Architect/Backend/QA 三角色单 Agent 执行）｜ 日期：2026-10-20 ｜ 状态：**完成，等待用户确认是否发布**
> 依据：用户 B3 批准指令（11 项目标 + 6 项限制）；基线 commit `42178c9`（B2，208/208 测试绿）

## 1. 交付物清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `examples/run_game_agent.py` | 新增 | E2E Demo：内置 ScriptedLLM（LLMClientProtocol 鸭子类型），单一 AgentLoop 完成 validate_experiment → generate_trials → export_experiment → validate_game → render_game → HTML；双层验证（脚本级 + 产物级），任何失败非零退出 |
| `tests/integration/test_e2e_game_agent.py` | 新增 | BD-1~BD-5 五项集成测试（详见 §3） |
| `README.md` | 重写 | 定位/快速开始/安装/架构/测试/试玩清单/已知限制/许可证占位 |
| `docs/checklists/browser-playtest-checklist.md` | 新增 | 浏览器人工试玩检查清单（9 节 30 项） |
| `pyproject.toml` | 修订 | 补 build-system + setuptools 包发现，`pip install -e .` 可用（已验证仓库外可 import） |
| `scripts/check.sh` | 修订 | 移除硬编码个人 node 路径，改为 PATH 缺失提示 |
| `docs/ENVIRONMENT_AUDIT.md` 等 4 个历史文档 | 脱敏 | `/Users/<user>` 绝对路径 → `~` |
| `.workbuddy/skills/`（4 文件） | 取消跟踪 | 会话内部数据不入公开仓库（磁盘文件保留） |

M1 / Phase A / B0-B2 冻结代码零改动（git diff 验证：src/ 与既有 tests/ 无修改）。

## 2. 全量门禁结果

| 检查 | 结果 |
|------|------|
| pytest 全量 | **213/213 通过**（基线 208 + 新增 5） |
| pyright src/ | **0 errors, 0 warnings** |
| 分层依赖检查 | PASS（无反向 import） |
| compileall | 通过 |
| scripts/check.sh 六项门禁 | **全部 PASS**（G-1~G-5b） |
| 密钥扫描（扩展至全仓库跟踪文件） | 无硬编码密钥（docs 中命中均为扫描正则的描述文本） |

## 3. E2E 验收证据（BD-1~BD-5）

- **BD-1 单循环全流程**：FakeLLM 五工具链在单一 AgentLoop（复用 build_game_registry
  8 工具，无新框架）内跑通；双层验证零问题。
- **BD-2 Demo 脚本真实可运行**：子进程 `CALC_AGENT_ENV_FILE=/dev/null`（零密钥零 .env）
  运行退出码 0，输出 `[E2E OK]`，bundle + HTML 真实落盘。
- **BD-3 可复现性**：两次独立运行 → `bundle_sha256` / `trials_fingerprint` /
  `config_fingerprint` 三指纹一致，HTML **逐字节一致**（generated_at 不参与指纹）。
- **BD-4 防静默忽略（产物篡改）**：HTML 缺失 / bundle 试次篡改 / HTML 字节篡改
  三种情形均被 `verify_artifacts` 报告问题；恢复后零问题（证明失败确由篡改引起）。
- **BD-5 防静默忽略（流程作弊）**："抄近路 LLM" 跳过 render_game 谎称完成 →
  Agent 层形式 completed，但验证层揭穿（工具序列不完整 + HTML 缺失）。

Demo 实跑输出（仓库根目录）：

```
$ .venv/bin/python examples/run_game_agent.py
llm rounds : 6 (5 tool calls + 1 final)
bundle     : data/experiments/demo-agent-game.json (sha256=9741eb7abd534527..., trials=24)
game html  : data/games/demo-agent-game.html (35277 bytes)
[E2E OK] all checks passed
```

## 4. 仓库卫生检查（开源前）

| 检查项 | 结果 | 处置 |
|--------|------|------|
| 密钥/API key | 无（.env 已 gitignore；.env.example 值全空） | 无需处置 |
| 个人绝对路径 | 曾有 8 处（docs×7 + check.sh×1 + .workbuddy×1） | 已全部脱敏/移除 |
| 临时日志/产物 | logs/、data/*、.coverage、.DS_Store 均已 gitignore | 无需处置 |
| 大型/二进制/模型文件 | 无（最大跟踪文件 200KB 文本 diff） | 无需处置 |
| 会话内部数据 | .workbuddy/skills/ 曾被跟踪 | 已 `git rm --cached`（磁盘保留） |

## 5. 许可证建议（未添加，等待用户确认）

**推荐 Apache-2.0**（备选 MIT）：

- 现有运行时依赖 FastAPI/Starlette/Pydantic/httpx/openai SDK 均为 MIT/BSD/Apache
  宽松许可，无传染性约束，两者皆可行；
- Apache-2.0 额外含明确专利授权与商标条款，对含确定性引擎 + 渲染器的工具型项目
  更稳妥；MIT 更简短、生态更普遍；
- 确认后添加 `LICENSE` 文件并同步 README 许可证节。

## 6. GitHub 发布前检查清单（供用户裁决）

- [ ] 确认许可证（Apache-2.0 / MIT / 其他）→ 添加 LICENSE 文件
- [ ] 确认 `docs/handoff/` 内部开发过程文档是否随仓库公开（当前含完整决策记录，
      无敏感信息；若希望精简可移至内部或删除，代码与 README 不依赖它们）
- [ ] 创建公开仓库并推送（本阶段未执行任何 push / 建仓操作）
- [ ] 建议补 CI workflow（直接复用 `scripts/check.sh`，六项门禁已机器可判定）
- [ ] 发布后按 `docs/checklists/browser-playtest-checklist.md` 人工开一次 file://
      截图留档（B2 验收的遗留人工项）

## 7. 已知限制（README 已同步公开声明）

1. 真实 LLM 端到端未通过（PA-14 已知问题：qwen2.5:7b + Ollama 0.40.6 工具调用
   静默丢弃；验收门槛为 FakeLLM + pytest，接口保持可替换）
2. 正式实验计时未经验证（浏览器近似计时，不用于数据收集）
3. 游戏交互类型有限（仅键盘 choice/text/rating；反馈三枚举；多响应不重绘刺激）
4. 事件日志不强制持久化（仅结束屏手动下载）
5. 浏览器自动化测试推迟（人工清单替代，D2 决策）

## 8. 边界遵守声明

未运行 Ollama / 真实 LLM / 付费 API；未修改 M1 与 Phase A 核心逻辑；未引入前端
框架或多 Agent 运行时；未推送 GitHub、未创建公开仓库、未添加许可证。
