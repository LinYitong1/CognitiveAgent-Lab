# Browser Playtest Checklist (B3 deliverable)

> Applies to: the single-file HTML games produced by `examples/run_game_agent.py` or  
> `examples/run_game_render.py`.  
> How to use: open the HTML file directly in a browser (`file://`, no server, no network  
> requests) and check each item. If any item fails → the HTML must not be used for demos;  
> go back to the pytest logic core to investigate.

## 0. Preparation

- [ ] Run `.venv/bin/python examples/run_game_agent.py` and confirm the output shows `[E2E OK]`
- [ ] Open the output path `data/games/demo-agent-game.html` (Chrome / Edge / Safari all work)

## 1. Startup integrity self-check (defense D-3)

- [ ] The page enters the Ready screen normally (not a red "Integrity check failed" error page)

## 2. Ready screen

- [ ] The title shows `Side Judgement`
- [ ] The instructions display (including `[f] for left` / `[j] for right`)
- [ ] `Press any key to start` is shown; any key starts the game

## 3. Keyboard responses

- [ ] Each trial: a fixation cross `+` first (about 400 ms), then the stimulus `side: left` or `side: right`
- [ ] Pressing `f` records left, pressing `j` records right; other keys are ignored (the trial does not advance)
- [ ] Unbound keys (e.g. `a`, arrow keys) are ignored

## 4. Feedback

- [ ] Correct key → green `correct`; wrong key → red `incorrect` (disappears after ~300 ms)
- [ ] After the feedback disappears the next trial begins (an empty ISI screen of ~600 ms)

## 5. Progress and block transitions

- [ ] The header counter increments by one per trial (`0/24` → `24/24`) and the progress bar advances in sync
- [ ] After the practice block (4 trials) a Block Break screen appears: `Block 'practice' complete`;  
  press any key to continue into the main block

## 6. End summary

- [ ] After all 24 trials the `Done` screen appears
- [ ] Stats lines: `Trials: 24`, `Correct: X/24 (Y%)` broadly consistent with your recollection of the keys pressed
- [ ] The self-check line reads `Self-check OK: 24 trials, 24 response events` (if it reads  
  `Self-check FAILED` → not passed)
- [ ] The timing disclaimer is displayed (approximate timing; not for formal data collection)

## 7. Event log download

- [ ] A read-only event-log text box (JSON) appears on the end screen
- [ ] Clicking the `Download event log (JSON)` button downloads `demo-agent-game-events.json`
- [ ] Open the downloaded JSON and verify the structure:
  - [ ] 1 `game_start` entry (total_trials=24)
  - [ ] 2 `block_start` entries (practice, main)
  - [ ] 24 `trial_start` entries (with trial_index / block / conditions)
  - [ ] 24 `response` entries (with response_name / value / correct / rt_ms)
  - [ ] 1 `game_end` entry (with correct / applicable stats)

## 8. (Optional) Anti-tamper recheck

- [ ] Copy the HTML file, change any single character in a text editor, save, and reopen →  
  it shows `Integrity check failed` and the game refuses to start (defense D-3 works)

## 9. Known limitations (be aware while playtesting)

- Timing (fixation/ISI/RT) uses browser `setTimeout`/`performance.now` approximations,  
  does not meet millisecond-grade experimental precision, and must not be used for formal  
  data collection
- The event log lives only in page memory — **refreshing or closing the page loses it**; it can  
  only be downloaded manually on the end screen
- In multi-response experiments the outcome-text feedback does not redraw the stimulus (an MVP  
  limitation)
