# 浏览器人工试玩检查清单（B3 交付）

> 适用对象：`examples/run_game_agent.py` 或 `examples/run_game_render.py` 生成的单文件 HTML 游戏。
> 使用方法：用浏览器直接打开 HTML 文件（`file://` 直开，无需服务器、无网络请求），
> 逐项勾选。任一项失败 → 该 HTML 不可用于演示，回到 pytest 逻辑核排查。

## 0. 准备

- [ ] 运行 `.venv/bin/python examples/run_game_agent.py`，确认输出 `[E2E OK]`
- [ ] 打开输出路径 `data/games/demo-agent-game.html`（Chrome / Edge / Safari 均可）

## 1. 启动完整性自检（防线 D-3）

- [ ] 页面正常进入 Ready 屏（不是 "Integrity check failed" 红字错误页）

## 2. Ready 屏

- [ ] 标题显示 `Side Judgement`
- [ ] 指导语显示（含 `[f] for left` / `[j] for right`）
- [ ] 显示 `Press any key to start`，按任意键开始

## 3. 键盘响应

- [ ] 每试次：先出现注视点 `+`（约 400ms），随后出现刺激 `side: left` 或 `side: right`
- [ ] 按 `f` 记为 left、按 `j` 记为 right，按其他键无效（不推进试次）
- [ ] 未绑定的按键（如 `a`、方向键）被忽略

## 4. 反馈

- [ ] 按对 → 绿色 `correct`；按错 → 红色 `incorrect`（约 300ms 后消失）
- [ ] 反馈消失后进入下一试次（ISI 空屏约 600ms）

## 5. 进度与区块切换

- [ ] 顶部计数每试次 +1（`0/24` → `24/24`），进度条同步推进
- [ ] practice 区组（4 试次）结束后出现 Block Break 屏：`Block 'practice' complete`，
      按任意键继续 main 区组

## 6. 结束总结

- [ ] 24 试次全部完成后出现 `Done` 屏
- [ ] 统计行：`Trials: 24`、`Correct: X/24 (Y%)` 与实际按键记忆大体一致
- [ ] 自检行显示 `Self-check OK: 24 trials, 24 response events`（若显示
      `Self-check FAILED` → 不通过）
- [ ] 显示计时免责声明（近似计时，不用于正式数据收集）

## 7. 事件日志下载

- [ ] 结束屏出现只读事件日志文本框（JSON）
- [ ] 点击 `Download event log (JSON)` 按钮，下载 `demo-agent-game-events.json`
- [ ] 打开下载的 JSON，核对结构：
  - [ ] 1 条 `game_start`（total_trials=24）
  - [ ] 2 条 `block_start`（practice、main）
  - [ ] 24 条 `trial_start`（含 trial_index / block / conditions）
  - [ ] 24 条 `response`（含 response_name / value / correct / rt_ms）
  - [ ] 1 条 `game_end`（含 correct / applicable 统计）

## 8.（可选）防篡改复核

- [ ] 复制一份 HTML，用文本编辑器改动任意一个字符后保存，再打开 →
      显示 `Integrity check failed`，游戏拒绝启动（防线 D-3 生效）

## 9. 已知限制（试玩时请知悉）

- 计时（fixation/ISI/RT）为浏览器 `setTimeout`/`performance.now` 近似值，
  不满足毫秒级实验精度，不可用于正式数据收集
- 事件日志仅保存在页面内存，**刷新/关闭页面即丢失**，只能在结束屏手动下载
- 多响应实验中 outcome-text 反馈不会重绘刺激（MVP 限制）
