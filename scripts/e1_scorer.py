"""E1 independent scorer (Real LLM Capability Evaluation, Phase E1-A).

Scores a completed agent run's ARTIFACTS (bundle + rendered HTML) and RUN
RECORD (report JSON) against the five E1 task briefs — INDEPENDENTLY of the
agent and of schema verdicts (the audit discipline: schema validity is not
scientific validity; an L4-style label-masking heuristic is a detector, not an
oracle).

Verdicts per dimension: PASS / FAIL / INCONCLUSIVE / NOT_APPLICABLE.

  D1 task completion        — final answer + artifacts delivered (run record)
  D2 tool-call correctness  — valid tools/args, no unknown-tool/invalid-arg errors (run record)
  D3 artifact validity      — verify_bundle + HTML integrity anchors
  D4 real manipulation      — label-masking content check + task-specific
                              structural requirements (phases, load variation,
                              cue variation, factor count)
  D5 answer recomputation   — correct_from exactness + content->key determinism
                              + task-family invariant recomputation from lines
  D6 HTML interaction       — generic node driver: event-log structure on a
                              classic game (explore: researcher review)
  D7 self-repair            — validation errors seen, then passed, then completed
  D8 efficiency             — tokens / calls / wall time / cost estimate

Honesty rules (mirroring scripts/agent_eval.py):
  - known-bad historical artifacts (T2R) must FAIL D4 — the scorer is
    validated on known-good AND known-bad samples (--selfcheck);
  - INCONCLUSIVE means "checkable structure not recognized; researcher review
    required", never a silent pass;
  - D4 is a heuristic (text-line designs): a timing-only manipulation is a
    false positive risk; coincidental content differences are a false negative
    risk (documented in the rubric).

Usage:
  python -m scripts.e1_scorer --selfcheck            # offline validation matrix
  python -m scripts.e1_scorer --task e1_flanker \
      --bundle path/bundle.json [--html path/game.html] [--report run.json]

This module makes NO LLM calls and NO network requests.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]

# Bumped when any check's semantics change (frozen into every scored.json and
# the E1-B run report; the run protocol records this value at freeze time).
SCORER_VERSION = "e1-scorer-v2"

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"
NOT_APPLICABLE = "NOT_APPLICABLE"
Verdict = str


def _mask_all(line: str, level_names: list[str]) -> str:
    """Replace every occurrence of any level name with a fixed placeholder."""
    out = line
    for name in level_names:
        out = out.replace(name, "<<lvl>>")
    return out


# ---------------------------------------------------------------------------
# Task registry: what each brief REQUIRES (the scorer's independent standard)
# ---------------------------------------------------------------------------

TASKS: dict[str, dict[str, Any]] = {
    # Simple choice experiment: no content manipulation demanded by the brief;
    # the displayed condition IS the task. D4 content check: N/A.
    "e1_t5_retest": {
        "min_factors": 1,
        "requires_content_manipulation": False,
        "requires_phases": False,
        "requires_load_variation": False,
        "requires_cue_variation": False,
    },
    # Flanker: congruency x target; BOTH factors must show genuine content
    # differences; balanced.
    "e1_flanker": {
        "min_factors": 2,
        "requires_content_manipulation": True,
        "requires_phases": False,
        "requires_load_variation": False,
        "requires_cue_variation": False,
    },
    # Working memory: real load difference (token-count variation across a
    # factor's levels) + multi-phase encode/probe presentation.
    "e1_wm": {
        "min_factors": 1,
        "requires_content_manipulation": True,
        "requires_phases": True,
        "requires_load_variation": True,
        "requires_cue_variation": False,
    },
    # Task switching: cue content must vary by a task factor; the task->answer
    # mapping must be recomputable from displayed content per task.
    "e1_taskswitch": {
        "min_factors": 2,
        "requires_content_manipulation": True,
        "requires_phases": True,
        "requires_load_variation": False,
        "requires_cue_variation": True,
    },
    # T2R regression: the historical nominal failure — load MUST be real this
    # time; multi-phase presentation required.
    "e1_t2r_regression": {
        "min_factors": 2,
        "requires_content_manipulation": True,
        "requires_phases": True,
        "requires_load_variation": True,
        "requires_cue_variation": False,
    },
}


# ---------------------------------------------------------------------------
# Shared bundle helpers
# ---------------------------------------------------------------------------


def _load_bundle(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _trials(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], bundle.get("trials", []))


def _lines_of(trial: dict[str, Any]) -> list[str]:
    stimulus = trial.get("stimulus")
    if isinstance(stimulus, dict) and isinstance(stimulus.get("lines"), list):
        return [str(x) for x in cast(list[object], stimulus["lines"])]
    return []


def _phases_of(trial: dict[str, Any]) -> list[dict[str, Any]] | None:
    stimulus = trial.get("stimulus")
    if isinstance(stimulus, dict) and isinstance(stimulus.get("phases"), list):
        phases = cast(list[dict[str, Any]], stimulus["phases"])
        return phases if phases else None
    return None


def _factor_names(bundle: dict[str, Any]) -> list[str]:
    return [f["name"] for f in cast(list[dict[str, Any]], bundle["spec"]["factors"])]


def _response_names(bundle: dict[str, Any]) -> list[str]:
    return [r["name"] for r in cast(list[dict[str, Any]], bundle["spec"]["responses"])]


# ---------------------------------------------------------------------------
# D3 artifact validity
# ---------------------------------------------------------------------------


def check_artifact_validity(bundle_path: Path, html_path: Path | None) -> dict[str, Verdict | str]:
    from src.experiment.verify import verify_bundle

    report = verify_bundle(Path(bundle_path))
    d3 = PASS if report.ok else FAIL
    detail = f"verify_bundle={'ok' if report.ok else 'FAIL: ' + str(report.detail)[:200]}"
    if html_path is not None and Path(html_path).is_file():
        html = Path(html_path).read_text(encoding="utf-8")
        anchors = ("BUNDLE_CANONICAL" in html and "TRIALS_CANONICAL" in html
                   and "sha256Hex" in html)
        if not anchors:
            d3 = FAIL
        detail += f"; html_integrity_anchors={'ok' if anchors else 'MISSING'}"
    else:
        detail += "; html=absent"
    return {"verdict": d3, "detail": detail}


# ---------------------------------------------------------------------------
# D4 real manipulation (label-masking heuristic + structural requirements)
# ---------------------------------------------------------------------------


def _label_masking(bundle: dict[str, Any]) -> dict[str, bool]:
    """For each factor: do its levels differ in masked content?

    True = levels differ beyond renaming the level label (genuine content
    difference); False = identical masked content (nominal manipulation — the
    T2R signature). Heuristic: text-line designs only.
    """
    trials = _trials(bundle)
    result: dict[str, bool] = {}
    if not trials or not all(_lines_of(t) for t in trials):
        return {}
    for factor in cast(list[dict[str, Any]], bundle["spec"]["factors"]):
        name = factor["name"]
        level_names = [lvl["name"] for lvl in cast(list[dict[str, Any]], factor["levels"])]
        masked_by_level: dict[str, set[tuple[str, ...]]] = {}
        for t in trials:
            masked = tuple(_mask_all(line, level_names) for line in _lines_of(t))
            masked_by_level.setdefault(str(t["factors"].get(name)), set()).add(masked)
        if len(masked_by_level) < 2:
            continue  # single realized level: variation not analyzable
        level_sets = [next(iter(sets)) for sets in masked_by_level.values() if sets]
        result[name] = not (len(level_sets) >= 2 and len(set(level_sets)) == 1)
    return result


def _load_variation(bundle: dict[str, Any]) -> dict[str, bool]:
    """For each factor: do its levels differ in the TOKEN COUNT of the
    non-window (encoding) phase content? (Real load manipulation detector.)
    """
    trials = _trials(bundle)
    result: dict[str, bool] = {}
    if not trials:
        return {}
    for factor in cast(list[dict[str, Any]], bundle["spec"]["factors"]):
        name = factor["name"]
        counts_by_level: dict[str, set[int]] = {}
        ok = True
        for t in trials:
            phases = _phases_of(t)
            if phases is None:
                ok = False
                break
            encode_lines = [
                str(line)
                for ph in phases
                if not ph.get("response_window")
                for line in cast(list[object], ph.get("lines", []))
            ]
            if not encode_lines:
                ok = False
                break
            n = len(" ".join(encode_lines).split())
            counts_by_level.setdefault(str(t["factors"].get(name)), set()).add(n)
        if not ok or len(counts_by_level) < 2:
            continue
        # genuine load variation: the per-level token-count SETS differ
        sets = [frozenset(v) for v in counts_by_level.values()]
        result[name] = len(set(sets)) > 1
    return result


def _cue_variation(bundle: dict[str, Any]) -> dict[str, bool]:
    """For each factor: does the FIRST phase's content differ across the
    factor's levels? (A task cue must actually signal the task.)"""
    trials = _trials(bundle)
    result: dict[str, bool] = {}
    if not trials:
        return {}
    for factor in cast(list[dict[str, Any]], bundle["spec"]["factors"]):
        name = factor["name"]
        first_by_level: dict[str, set[tuple[str, ...]]] = {}
        ok = True
        for t in trials:
            phases = _phases_of(t)
            if phases is None or not phases:
                ok = False
                break
            first = tuple(str(x) for x in cast(list[object], phases[0].get("lines", [])))
            first_by_level.setdefault(str(t["factors"].get(name)), set()).add(first)
        if not ok or len(first_by_level) < 2:
            continue
        result[name] = len(set(next(iter(s)) for s in first_by_level.values() if s)) > 1
    return result


def check_real_manipulation(bundle: dict[str, Any], task_id: str) -> dict[str, Verdict | str]:
    req = TASKS[task_id]
    problems: list[str] = []
    notes: list[str] = []
    trials = _trials(bundle)
    if not trials:
        return {"verdict": FAIL, "detail": "no trials in bundle"}

    n_factors = len(_factor_names(bundle))
    if n_factors < cast(int, req["min_factors"]):
        problems.append(f"factor count {n_factors} < required {req['min_factors']}")

    masking = _label_masking(bundle)
    if req["requires_content_manipulation"]:
        if not masking:
            # no materialized lines at all, or single realized level
            verdict = INCONCLUSIVE if trials and not all(_lines_of(t) for t in trials) else FAIL
            return {
                "verdict": verdict,
                "detail": "no materialized stimulus lines to compare "
                          "(content manipulation unverifiable) — researcher review",
            }
        genuine = [name for name, differs in masking.items() if differs]
        nominal = [name for name, differs in masking.items() if not differs]
        if not genuine:
            problems.append(
                "ALL factors show IDENTICAL masked content across levels "
                "(nominal manipulation — the T2R signature): " + ", ".join(nominal)
            )
        else:
            notes.append(f"genuine content difference by: {genuine}")
            if nominal:
                notes.append(f"nominal (label-only) factors: {nominal} — "
                             "acceptable only if the brief does not demand manipulation there")
    else:
        notes.append("brief demands no content manipulation; label-masking check not applied")

    if req["requires_phases"]:
        phased = all(_phases_of(t) is not None for t in trials)
        has_window = any(
            any(ph.get("response_window") for ph in cast(list[dict[str, Any]], _phases_of(t) or []))
            for t in trials
        )
        if not phased:
            problems.append("no phased presentation (encoding/probe separation missing)")
        elif not has_window:
            problems.append("phases present but no response window")
        else:
            notes.append("multi-phase presentation present")

    if req["requires_load_variation"]:
        loads = _load_variation(bundle)
        if not loads:
            problems.append("no load variation detected: no factor's levels differ in "
                            "encoding token counts (short/long must differ in REAL content)")
        elif not any(loads.values()):
            problems.append(f"load nominal: token counts identical across levels {loads}")
        else:
            notes.append(f"real load variation by: {[k for k, v in loads.items() if v]}")

    if req["requires_cue_variation"]:
        cues = _cue_variation(bundle)
        if not cues or not any(cues.values()):
            problems.append("no cue variation: the first phase does not differ by any factor "
                            "(a task cue must signal the task)")
        else:
            notes.append(f"cue varies by: {[k for k, v in cues.items() if v]}")

    verdict = FAIL if problems else PASS
    return {
        "verdict": verdict,
        "detail": "; ".join(problems + notes) if (problems or notes) else "ok",
        "problems": problems,  # type: ignore[dict-item]
    }


# ---------------------------------------------------------------------------
# D5 answer recomputation (independent of schema verdicts)
# ---------------------------------------------------------------------------


def _answer_keys(bundle: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """trial_index -> response_name -> expected key (from trial.correct or
    correct_from factors)."""
    keys: dict[int, dict[str, Any]] = {}
    responses = cast(list[dict[str, Any]], bundle["spec"]["responses"])
    for t in _trials(bundle):
        idx = int(t["index"])
        entry: dict[str, Any] = {}
        materialized = t.get("correct")
        for r in responses:
            name = r["name"]
            if isinstance(materialized, dict) and name in materialized:
                entry[name] = materialized[name]
            elif isinstance(r.get("correct_from"), str):
                entry[name] = t["factors"].get(r["correct_from"])
        keys[idx] = entry
    return keys


def check_answer_recomputation(bundle: dict[str, Any], task_id: str) -> dict[str, Verdict | str]:
    trials = _trials(bundle)
    problems: list[str] = []
    notes: list[str] = []
    has_keys = all(any(v is not None for v in _answer_keys(bundle).get(int(t["index"]), {}).values())
                   for t in trials)
    if not has_keys:
        return {"verdict": FAIL, "detail": "some trials carry no answer key at all"}

    # (a) content -> key determinism: identical displayed content must imply
    # identical keys (the answer must be derivable from what is displayed)
    by_content: dict[tuple[str, ...], set[tuple[Any, ...]]] = {}
    for t in trials:
        content = tuple(_lines_of(t))
        if not content:
            continue
        key_tuple = tuple(sorted((k, str(v)) for k, v in _answer_keys(bundle)[int(t["index"])].items()))
        by_content.setdefault(content, set()).add(key_tuple)
    ambiguous = [c for c, ks in by_content.items() if len(ks) > 1]
    if ambiguous:
        problems.append(f"identical stimulus content maps to different answer keys in "
                        f"{len(ambiguous)} content group(s) — answer not derivable from display")
    else:
        notes.append("answer is a deterministic function of displayed content")

    # (b) probe-membership family (WM/T2R): learn the mapping
    # (probe token in encoding tokens) -> key; it must be a consistent function.
    # Template decoration words (tokens common to EVERY trial of that phase
    # kind) are excluded first — they never carry the probe/memoranda signal.
    phases_all = [_phases_of(t) for t in trials]
    if any(p is not None for p in phases_all) and TASKS[task_id]["requires_load_variation"]:
        entries: list[tuple[set[str], set[str], list[str]]] = []
        for t, phases in zip(trials, phases_all):
            if not phases:
                continue
            encode_tokens = set(
                tok
                for ph in phases
                if not ph.get("response_window")
                for line in cast(list[object], ph.get("lines", []))
                for tok in str(line).split()
            )
            probe_tokens = set(
                tok
                for ph in phases
                if ph.get("response_window")
                for line in cast(list[object], ph.get("lines", []))
                for tok in str(line).split()
            )
            key_vals = [str(v) for v in _answer_keys(bundle)[int(t["index"])].values() if v is not None]
            if not encode_tokens or not probe_tokens or not key_vals:
                continue
            entries.append((encode_tokens, probe_tokens, key_vals))
        if len(entries) >= 2:
            enc_common = set.intersection(*(e[0] for e in entries))
            prb_common = set.intersection(*(e[1] for e in entries))
            mapping: dict[bool, set[str]] = {}
            analyzed = 0
            usable = True
            for enc, prb, key_vals in entries:
                items = enc - enc_common
                probes = prb - prb_common
                if not items or not probes:
                    usable = False
                    break
                probe_in = probes <= items
                analyzed += 1
                mapping.setdefault(probe_in, set()).update(key_vals)
            if usable and analyzed:
                if all(len(v) == 1 for v in mapping.values()):
                    notes.append(f"probe-membership invariant recomputed consistently over "
                                 f"{analyzed} trial(s): { {k: sorted(v) for k, v in mapping.items()} }")
                    # direction anchor: a declared correct_rule (op in/eq) fixes
                    # WHICH key value means "probe in memory" — an inverted key
                    # is also a consistent function, so cross-check the direction
                    rule = None
                    for r in cast(list[dict[str, Any]], bundle["spec"]["responses"]):
                        cr = r.get("correct_rule")
                        if isinstance(cr, dict) and cr.get("op") in ("in", "eq"):
                            rule = cr
                            break
                    if rule is not None:
                        observed = {k: sorted(v)[0] for k, v in mapping.items()}
                        expected = {True: str(rule["true_option"]), False: str(rule["false_option"])}
                        if observed != expected:
                            problems.append(
                                "answer key direction CONTRADICTS the declared correct_rule "
                                f"(observed {observed} vs rule {expected} — keys inverted?)"
                            )
                        else:
                            notes.append("key direction matches the declared correct_rule")
                else:
                    problems.append("probe-membership does NOT determine the answer key "
                                    f"(mapping { {k: sorted(v) for k, v in mapping.items()} })")
        # fewer than two usable trials: phased but structure not recognizable -> fall through

    # (c) taskswitch family: per task-factor level, displayed word -> key must
    # be a function, and the mapping must DIFFER between task levels
    if task_id == "e1_taskswitch":
        per_task: dict[str, dict[str, set[str]]] = {}
        task_factor: str | None = None
        for factor in cast(list[dict[str, Any]], bundle["spec"]["factors"]):
            cues = _cue_variation(bundle)
            if cues.get(factor["name"]):
                task_factor = factor["name"]
                break
        if task_factor is not None:
            for t in trials:
                phases = _phases_of(t)
                if not phases:
                    continue
                # probe-phase words (window phase), excluding the cue phase
                words = [
                    tok
                    for ph in phases[1:]
                    for line in cast(list[object], ph.get("lines", []))
                    for tok in str(line).split()
                ]
                key_vals = [str(v) for v in _answer_keys(bundle)[int(t["index"])].values() if v is not None]
                if not words or not key_vals:
                    continue
                level = str(t["factors"].get(task_factor))
                per_task.setdefault(level, {}).setdefault(tuple(words), set()).update(key_vals)
            consistent = all(
                all(len(v) == 1 for v in words.values())
                for words in per_task.values()
            )
            if consistent and len(per_task) >= 2:
                # the mappings must differ between tasks (else no switching demand)
                maps = {level: {w: sorted(v)[0] for w, v in words.items()} for level, words in per_task.items()}
                differs = any(
                    maps[a].get(w) != maps[b].get(w)
                    for a in maps for b in maps if a < b
                    for w in set(maps[a]) & set(maps[b])
                )
                if differs:
                    notes.append(f"task-dependent mapping recomputed per task level "
                                 f"({ {k: len(v) for k, v in per_task.items()} } words/task, mappings differ)")
                else:
                    problems.append("word->answer mapping is IDENTICAL across task levels "
                                    "(no task switching demand in the content)")
            elif per_task:
                problems.append("word->answer mapping inconsistent within a task level")

    verdict = FAIL if problems else PASS
    return {"verdict": verdict, "detail": "; ".join(problems + notes) if (problems or notes) else "ok"}


# ---------------------------------------------------------------------------
# Task-level acceptance invariants (per-brief requirements, Stage E1-B preflight)
#
# These are INDEPENDENT acceptance conditions derived from each brief's
# research requirement. They merge their problems into D4 (structure /
# manipulation / balance) and D5 (answer-key semantics) WITHOUT relaxing any
# generic check: a reference must pass both the generic AND the task checks;
# an adversarial sample (schema-valid but brief-violating) must FAIL at least
# one. Unknown-structure cases are INCONCLUSIVE notes, never silent passes.
# ---------------------------------------------------------------------------

_STRIP_PUNCT = ".,!?;:()[]{}\"'`"
_LEFT_ARROWS = frozenset("<\u2190")
_RIGHT_ARROWS = frozenset(">\u2192")


def _norm_word(tok: str) -> str:
    """Lowercase + strip surrounding punctuation (word-token comparison only;
    arrow-character checks use raw characters)."""
    return tok.strip(_STRIP_PUNCT).lower()


def _key_value(bundle: dict[str, Any], trial: dict[str, Any]) -> str | None:
    for v in _answer_keys(bundle).get(int(trial["index"]), {}).values():
        if v is not None:
            return str(v)
    return None


def _arrow_directions(lines: list[str]) -> list[str]:
    """All arrow characters of the displayed lines, in order, as directions."""
    out: list[str] = []
    for ch in "".join(lines):
        if ch in _LEFT_ARROWS:
            out.append("left")
        elif ch in _RIGHT_ARROWS:
            out.append("right")
    return out


def _phase_word_sets(trial: dict[str, Any]) -> tuple[set[str], set[str]] | None:
    """(encode tokens, probe tokens) of a phased trial, normalized; None when
    the trial is not phased."""
    phases = _phases_of(trial)
    if not phases:
        return None
    enc: set[str] = set()
    prb: set[str] = set()
    for ph in phases:
        target = prb if ph.get("response_window") else enc
        for line in cast(list[object], ph.get("lines", [])):
            for tok in str(line).split():
                w = _norm_word(tok)
                if w:
                    target.add(w)
    return enc, prb


def _load_classes(trials: list[dict[str, Any]]) -> list[int] | None:
    """Per-trial memoranda counts (encoding tokens minus cross-trial constants).
    None when any trial is unphased or has an empty encoding phase."""
    sets: list[set[str]] = []
    for t in trials:
        ps = _phase_word_sets(t)
        if ps is None or not ps[0]:
            return None
        sets.append(ps[0])
    common = set.intersection(*(s for s in sets))
    return [len(s - common) for s in sets]


def _memberships(trials: list[dict[str, Any]]) -> list[bool] | None:
    """Per-trial probe membership (probe tokens minus cross-trial constants
    are a subset of that trial's memoranda). None when not computable."""
    enc_sets: list[set[str]] = []
    prb_sets: list[set[str]] = []
    for t in trials:
        ps = _phase_word_sets(t)
        if ps is None or not ps[0] or not ps[1]:
            return None
        enc_sets.append(ps[0])
        prb_sets.append(ps[1])
    enc_common = set.intersection(*(s for s in enc_sets))
    prb_common = set.intersection(*(s for s in prb_sets))
    out: list[bool] = []
    for enc, prb in zip(enc_sets, prb_sets):
        probe = prb - prb_common
        if not probe:
            return None
        out.append(probe <= (enc - enc_common))
    return out


def _balanced_cells(labels: list[tuple[str, ...]], problems: list[str], what: str) -> bool:
    """Require every combination of the label tuples to occur equally often."""
    if not labels:
        return False
    counts: dict[tuple[str, ...], int] = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    expected_cells = 1
    for i in range(len(labels[0])):
        expected_cells *= len({lab[i] for lab in labels})
    if len(counts) != expected_cells or len(set(counts.values())) != 1:
        problems.append(f"{what} not fully crossed/balanced: {dict(counts)}")
        return False
    return True


def _aligning_factor(
    bundle: dict[str, Any], trial_classes: list[str]
) -> str | None:
    """A declared factor whose levels partition trials one-to-one onto the
    computed content classes (the condition is logged AND matches content)."""
    trials = _trials(bundle)
    for factor in cast(list[dict[str, Any]], bundle["spec"]["factors"]):
        name = str(factor["name"])
        level_class: dict[str, str] = {}
        ok = True
        for t, cls in zip(trials, trial_classes):
            lvl = str(cast(dict[str, str], t["factors"]).get(name))
            if lvl in level_class and level_class[lvl] != cls:
                ok = False
                break
            level_class[lvl] = cls
        if ok and len(level_class) >= 2 and len(set(level_class.values())) == len(level_class):
            return name
    return None


def _plan_from_html(html_path: Path) -> dict[str, Any] | None:
    """Extract the embedded PLAN JSON from a rendered game HTML."""
    m = re.search(r'const PLAN = JSON\.parse\("(.*)"\);', html_path.read_text(encoding="utf-8"))
    if not m:
        return None
    return cast(dict[str, Any], json.loads(json.loads('"' + m.group(1) + '"')))


# -- Flanker: exactly five arrows; center decides; flanks congruent/incongruent


def _flanker_checks(
    bundle: dict[str, Any], d4: list[str], d5: list[str], notes: list[str]
) -> None:
    trials = _trials(bundle)
    parsed: list[tuple[dict[str, Any], str, str]] = []
    for t in trials:
        arrows = _arrow_directions(_lines_of(t))
        if len(arrows) != 5:
            d4.append(f"trial {t['index']} displays {len(arrows)} arrow characters "
                      f"(the brief requires exactly five)")
            continue
        center = arrows[2]
        flanks = (arrows[0], arrows[1], arrows[3], arrows[4])
        if all(f == center for f in flanks):
            parsed.append((t, "congruent", center))
        elif all(f != center for f in flanks):
            parsed.append((t, "incongruent", center))
        else:
            d4.append(f"trial {t['index']} has mixed flank directions (flanks must be "
                      f"uniformly the same as, or opposite to, the middle arrow)")
    if len(parsed) != len(trials):
        return  # structural failure already recorded above
    congr_counts: dict[str, int] = {}
    center_counts: dict[str, int] = {}
    for _, congr, center in parsed:
        congr_counts[congr] = congr_counts.get(congr, 0) + 1
        center_counts[center] = center_counts.get(center, 0) + 1
    if len(congr_counts) < 2:
        d4.append("congruency never varies (both congruent and incongruent trials required)")
    elif congr_counts.get("congruent") != congr_counts.get("incongruent"):
        d4.append(f"congruency not strictly balanced: {congr_counts}")
    if len(center_counts) < 2:
        d4.append("the middle arrow's direction never varies (both left and right required)")
    elif center_counts.get("left") != center_counts.get("right"):
        d4.append(f"middle-direction not strictly balanced: {center_counts}")
    factor = _aligning_factor(bundle, [c for _, c, _ in parsed])
    if factor is None:
        d4.append("no declared factor's levels match the displayed congruency structure "
                  "(congruent vs incongruent is not analyzable from the logged conditions)")
    else:
        notes.append(f"congruency condition '{factor}' matches the displayed flank structure")
    dir_keys: dict[str, set[str]] = {}
    for t, _, center in parsed:
        val = _key_value(bundle, t)
        if val is None:
            continue
        dir_keys.setdefault(center, set()).add(val)
    if len(dir_keys) == 2:
        if any(len(s) != 1 for s in dir_keys.values()):
            d5.append("the middle arrow's direction does NOT determine the correct answer "
                      "(one direction maps to multiple answer keys)")
        elif len(set(next(iter(s)) for s in dir_keys.values())) != 2:
            d5.append("both middle directions map to the same answer key "
                      "(the answer does not follow the middle arrow)")
        else:
            notes.append("correct answer follows the middle arrow's direction")


# -- Working memory: 2/4 memoranda, single probe word, membership, cell balance


def _wm_checks(
    bundle: dict[str, Any], d4: list[str], d5: list[str], notes: list[str]
) -> None:
    trials = _trials(bundle)
    loads = _load_classes(trials)
    if loads is None:
        return  # unphased: the generic D4 phase requirement already fails
    for t, n in zip(trials, loads):
        if n not in (2, 4):
            d4.append(f"trial {t['index']} encodes {n} memorized words "
                      f"(the brief requires exactly 2 or 4)")
    if sorted(set(loads)) == [2, 4]:
        notes.append("encoding sets contain exactly 2 vs 4 memorized words")
        factor = _aligning_factor(bundle, ["low" if n == 2 else "high" for n in loads])
        if factor is None:
            d4.append("no declared factor's levels match the computed memory load "
                      "(per-load analysis is not possible from the logged conditions)")
        else:
            notes.append(f"load condition '{factor}' matches the computed encoding sizes")
    # probe must be exactly one content word (and never shown with the set)
    prb_sets: list[set[str]] = []
    enc_sets: list[set[str]] = []
    for t in trials:
        ps = _phase_word_sets(t)
        assert ps is not None
        enc_sets.append(ps[0])
        prb_sets.append(ps[1])
    prb_common = set.intersection(*(s for s in prb_sets))
    for t, prb in zip(trials, prb_sets):
        n = len(prb - prb_common)
        if n != 1:
            d4.append(f"trial {t['index']}'s probe phase shows {n} content words "
                      f"(exactly one probe word; the study set must not be on screen with it)")
    memberships = _memberships(trials)
    if memberships is None:
        return
    if len(set(memberships)) < 2:
        d4.append("probe membership never varies (both in-set and novel probes required)")
    else:
        mapping: dict[bool, set[str]] = {}
        for t, m in zip(trials, memberships):
            val = _key_value(bundle, t)
            if val is not None:
                mapping.setdefault(m, set()).add(val)
        if len(mapping) == 2 and any(len(s) != 1 for s in mapping.values()):
            d5.append("probe membership does not determine the answer key")
        elif len(mapping) == 2:
            vals = [next(iter(s)) for s in mapping.values()]
            if vals[0] == vals[1]:
                d5.append("both membership classes map to the same answer key "
                          "(the answer does not follow probe membership)")
            else:
                notes.append("answer key follows probe membership with distinct keys")
    if sorted(set(loads)) == [2, 4] and len(set(memberships)) == 2:
        if _balanced_cells(
            [("low" if n == 2 else "high", str(m)) for n, m in zip(loads, memberships)],
            d4, "load x membership cells",
        ):
            notes.append("load x membership crossed and balanced")


# -- Task switching: cue signals a logged task; A/B mappings are exact inversions


def _taskswitch_checks(
    bundle: dict[str, Any], d4: list[str], d5: list[str], notes: list[str],
    inconclusive: list[str],
) -> None:
    trials = _trials(bundle)
    # cue phase = first phase; must be non-window and precede the stimulus
    for t in trials:
        phases = _phases_of(t)
        if phases and phases[0].get("response_window"):
            d4.append(f"trial {t['index']}'s first phase is the response window "
                      f"(the cue must precede the word)")
            break
    cue_classes: list[str] = []
    cue_contents: list[tuple[str, ...]] = []
    for t in trials:
        phases = _phases_of(t)
        if not phases:
            return  # unphased: generic D4 already fails
        cue_contents.append(tuple(str(x) for x in cast(list[object], phases[0].get("lines", []))))
        cue_classes.append(cue_contents[-1])
    task_factor = _aligning_factor(bundle, [repr(c) for c in cue_classes])
    if task_factor is None:
        d4.append("no factor's levels map one-to-one onto distinct cue contents "
                  "(the cue does not signal a logged task condition)")
    else:
        notes.append(f"cue content signals the logged task condition '{task_factor}'")
    # stimulus words (window phases, decoration excluded)
    prb_sets: list[set[str]] = []
    for t in trials:
        ps = _phase_word_sets(t)
        if ps is None:
            return
        prb_sets.append(ps[1])
    prb_common = set.intersection(*(s for s in prb_sets))
    words = [s - prb_common for s in prb_sets]
    word_set = set().union(*words) if words else set()
    if word_set != {"same", "different"}:
        d4.append(f"the realized stimulus words are {sorted(word_set)}; "
                  f"the brief specifies the words 'same' and 'different'")
        return
    # balance: tasks and answers
    if task_factor is not None:
        task_counts: dict[str, int] = {}
        for t in trials:
            lvl = str(cast(dict[str, str], t["factors"]).get(task_factor))
            task_counts[lvl] = task_counts.get(lvl, 0) + 1
        if len(task_counts) == 2 and len(set(task_counts.values())) != 1:
            d4.append(f"tasks not balanced: {task_counts}")
    answer_counts: dict[str, int] = {}
    per_task: dict[str, dict[str, str]] = {}
    for t, w in zip(trials, words):
        val = _key_value(bundle, t)
        if val is None:
            continue
        answer_counts[val] = answer_counts.get(val, 0) + 1
        if task_factor is not None:
            lvl = str(cast(dict[str, str], t["factors"]).get(task_factor))
            if len(w) != 1:
                d4.append(f"trial {t['index']}'s stimulus phase shows {len(w)} content words "
                          f"(exactly one stimulus word required)")
                continue
            word = next(iter(w))
            mapping = per_task.setdefault(lvl, {})
            if word in mapping and mapping[word] != val:
                d5.append(f"within task {lvl!r}, word {word!r} maps to multiple answer keys")
            mapping[word] = val
    if len(answer_counts) == 2 and len(set(answer_counts.values())) != 1:
        d4.append(f"answers not balanced: {answer_counts}")
    if task_factor is None or len(per_task) != 2:
        return
    la, lb = sorted(per_task)
    ma, mb = per_task[la], per_task[lb]
    for lvl, m in per_task.items():
        if set(m) != {"same", "different"}:
            d5.append(f"task {lvl!r} does not realize both stimulus words "
                      f"(mapping incomplete: {m})")
            return
    if not (mb.get("same") == ma.get("different") and mb.get("different") == ma.get("same")):
        d5.append(f"the two tasks' mappings are not the required inversion of each other "
                  f"(A: {ma}, B: {mb}; task B must answer 'yes' exactly where task A answers 'no')")
    else:
        notes.append(f"task-contingent mapping is the required inversion ({la}: {ma}, {lb}: {mb})")
        options = set()
        for r in cast(list[dict[str, Any]], bundle["spec"]["responses"]):
            options.update(str(o) for o in cast(list[object], r.get("options") or []))
        if options == {"yes", "no"}:
            if ma.get("same") != "yes":
                d5.append(f"literal direction violated: in task A the word 'same' must map to "
                          f"'yes' (observed {ma.get('same')!r})")
            else:
                notes.append("literal direction matches the brief (task A: 'same' -> 'yes')")
        else:
            inconclusive.append(f"response options are {sorted(options)}, not literally "
                                f"yes/no — inversion verified, literal direction not (researcher review)")


# -- T2R regression: load + membership + cell balance + >=3 rooms + s/d keys


def _t2r_checks(
    bundle: dict[str, Any], d4: list[str], d5: list[str], notes: list[str],
    inconclusive: list[str], html_path: Path | None,
) -> None:
    trials = _trials(bundle)
    loads = _load_classes(trials)
    memberships = _memberships(trials) if loads is not None else None
    if loads is not None and memberships is not None and len(set(memberships)) == 2:
        distinct = sorted(set(loads))
        if len(distinct) == 2:
            classes = [f"load{distinct.index(n)}" for n in loads]
            factor = _aligning_factor(bundle, classes)
            if factor is None:
                d4.append("no declared factor's levels match the computed sequence length "
                          "(short/long is not analyzable from the logged conditions)")
            else:
                notes.append(f"length condition '{factor}' matches the computed encoding sizes")
            mapping: dict[bool, set[str]] = {}
            for t, m in zip(trials, memberships):
                val = _key_value(bundle, t)
                if val is not None:
                    mapping.setdefault(m, set()).add(val)
            if len(mapping) == 2:
                vals = [sorted(s) for s in mapping.values()]
                if any(len(v) != 1 for v in vals):
                    d5.append("probe membership does not determine the answer key")
                elif vals[0] == vals[1]:
                    d5.append("both membership classes map to the same answer key")
                else:
                    notes.append("answer key follows probe membership with distinct keys")
            _balanced_cells(
                [(f"load{distinct.index(n)}", str(m)) for n, m in zip(loads, memberships)],
                d4, "length x membership cells",
            )
        else:
            d4.append(f"computed encoding sizes {distinct} do not form two distinct "
                      f"length classes (short/long required)")
    if html_path is not None and Path(html_path).is_file():
        plan = _plan_from_html(Path(html_path))
        if plan is None:
            d4.append("the rendered HTML carries no embedded PLAN (not a generated game)")
        elif not isinstance(plan.get("world"), dict):
            d4.append("the brief demands an explorable scene (>= 3 rooms); "
                      "the rendered game is a classic single-screen layout")
        else:
            rooms = cast(dict[str, Any], cast(dict[str, Any], plan["world"]).get("rooms"))
            n_rooms = len(rooms) if isinstance(rooms, dict) else 0
            if n_rooms < 3:
                d4.append(f"only {n_rooms} explorable room(s) (the brief requires at least 3)")
            else:
                notes.append(f"{n_rooms} explorable rooms")
            encounters = cast(list[object], plan.get("encounters") or [])
            if len(encounters) < len(trials):
                d4.append(f"encounter objects ({len(encounters)}) fewer than trials "
                          f"({len(trials)})")
            meta = cast(dict[str, Any], plan.get("meta") or {})
            bindings = cast(dict[str, dict[str, str]], meta.get("bindings") or {})
            keys_used = {k for b in bindings.values() for k in b}
            if keys_used and not {"s", "d"} <= keys_used:
                d4.append(f"response keys {sorted(keys_used)} do not include the brief's "
                          f"s/d keys")
            inconclusive.append(
                "runtime exploration-order invariance is guaranteed by the engine's "
                "monotonic encounter cursor and the declared controlled_invariants, but "
                "NOT re-verified by an automated explore-runtime driver — MANUAL ACCEPTANCE"
            )
    else:
        inconclusive.append("no rendered HTML: room structure (>= 3 rooms), encounter "
                            "coverage, s/d keys, and exploration-order invariance NOT "
                            "VERIFIED — researcher review")


# -- T5 retest: 10 balanced trials; displayed content consistent with the log


def _t5_checks(
    bundle: dict[str, Any], d4: list[str], d5: list[str], notes: list[str],
) -> None:
    trials = _trials(bundle)
    if len(trials) != 10:
        d4.append(f"{len(trials)} trials (the brief requires 10)")
    for factor in cast(list[dict[str, Any]], bundle["spec"]["factors"]):
        name = str(factor["name"])
        counts: dict[str, int] = {}
        for t in trials:
            lvl = str(cast(dict[str, str], t["factors"]).get(name))
            counts[lvl] = counts.get(lvl, 0) + 1
        if len(counts) == 2:
            if len(set(counts.values())) != 1:
                d4.append(f"factor '{name}' not balanced: {counts}")
    # displayed content must differ across the two colors (anti-nominal)
    lines = [_lines_of(t) for t in trials]
    if all(lines):
        by_level: dict[str, set[tuple[str, ...]]] = {}
        for t, ls in zip(trials, lines):
            lvl = str(next(iter(cast(dict[str, str], t["factors"]).values())))
            by_level.setdefault(lvl, set()).add(tuple(ls))
        if len(by_level) == 2:
            a, b = [next(iter(s)) for s in by_level.values()]
            if a == b:
                d4.append("both color levels display identical content "
                          "(the color shown must actually differ)")
            else:
                notes.append("displayed content differs across the two color levels")
    else:
        notes.append(
            "v1-style design (no materialized stimulus lines): the classic runtime "
            "displays the logged factor values verbatim, so conditions in the event log "
            "ARE what was shown"
        )
    notes.append(
        "evidence chain for 'what was shown': the event log records conditions/value/"
        "correct/rt_ms per response but NOT the stimulus text; the displayed content is "
        "reconstructed from the bundle trials, which the HTML embeds and self-verifies "
        "(BUNDLE_CANONICAL/TRIALS_CANONICAL + sha256) — no claim is made that the log "
        "itself records the stimulus"
    )


def check_task_invariants(
    bundle: dict[str, Any], task_id: str, html_path: Path | None = None
) -> dict[str, Any]:
    """Per-brief acceptance invariants. Returns d4/d5 problems (merged into the
    dimension verdicts), notes, and inconclusive items (researcher review)."""
    d4: list[str] = []
    d5: list[str] = []
    notes: list[str] = []
    inconclusive: list[str] = []
    if task_id == "e1_flanker":
        _flanker_checks(bundle, d4, d5, notes)
    elif task_id == "e1_wm":
        _wm_checks(bundle, d4, d5, notes)
    elif task_id == "e1_taskswitch":
        _taskswitch_checks(bundle, d4, d5, notes, inconclusive)
    elif task_id == "e1_t2r_regression":
        _t2r_checks(bundle, d4, d5, notes, inconclusive, html_path)
    elif task_id == "e1_t5_retest":
        _t5_checks(bundle, d4, d5, notes)
    return {
        "d4_problems": d4,
        "d5_problems": d5,
        "notes": [n for n in notes if n],
        "inconclusive": inconclusive,
    }

_HTML_CHECK_HARNESS_JS = """\
"use strict";
var fs = require("fs");
var vm = require("vm");
var html = fs.readFileSync(process.argv[2], "utf8");
var m = html.match(/const PLAN = JSON\\.parse\\("(.*)"\\);/);
if (!m) { console.error("__RESULT__" + JSON.stringify({ verdict: "FAIL", detail: "no PLAN in HTML" })); process.exit(0); }
var planText = JSON.parse('"' + m[1] + '"');
var PLAN = JSON.parse(planText);
var parts = html.split("<script>");
if (parts.length !== 3) { console.error("__RESULT__" + JSON.stringify({ verdict: "FAIL", detail: "unexpected script count" })); process.exit(0); }
var dataJs = parts[1].split("</script>")[0];
var engineJs = parts[2].split("</script>")[0];
if (PLAN.world) {
  console.log("__RESULT__" + JSON.stringify({ verdict: "INCONCLUSIVE", detail: "explore layout: generic driver does not navigate; researcher review required" }));
  process.exit(0);
}
function makeEl(tag) {
  var el = {
    tagName: String(tag || "div").toUpperCase(), children: [], style: {}, _cls: {}, attrs: {},
    handlers: {}, className: "", textContent: "", value: "", readOnly: false, type: "", classList: null,
    appendChild: function (c) { el.children.push(c); return c; },
    removeChild: function (c) { var i = el.children.indexOf(c); if (i >= 0) { el.children.splice(i, 1); } return c; },
    addEventListener: function (name, fn) { (el.handlers[name] = el.handlers[name] || []).push(fn); },
    setAttribute: function (k, v) {
      el.attrs[k] = String(v);
      if (k === "id") { elementsById[v] = el; }
      if (k === "class") { el._cls = {}; String(v).split(/\\s+/).forEach(function (c) { if (c) { el._cls[c] = true; } }); }
    },
    getAttribute: function (k) { return el.attrs[k]; },
    focus: function () {}, click: function () {}
  };
  el.classList = {
    add: function (c) { el._cls[c] = true; },
    remove: function (c) { delete el._cls[c]; },
    contains: function (c) { return !!el._cls[c]; }
  };
  Object.defineProperty(el, "firstChild", { get: function () { return el.children[0] || null; } });
  Object.defineProperty(el, "id", {
    get: function () { return el.attrs.id || ""; },
    set: function (v) { el.attrs.id = String(v); elementsById[String(v)] = el; }
  });
  return el;
}
var keydownHandlers = [];
var elementsById = {};
var elements = {};
globalThis.document = {
  getElementById: function (id) {
    if (elementsById[id]) { return elementsById[id]; }
    if (!elements[id]) { elements[id] = makeEl("div"); elementsById[id] = elements[id]; }
    return elements[id];
  },
  createElement: function (tag) { return makeEl(tag); },
  addEventListener: function (name, fn) { if (name === "keydown") { keydownHandlers.push(fn); } },
  activeElement: null,
  body: makeEl("body")
};
globalThis.performance = { now: function () { return Date.now(); } };
vm.runInThisContext(dataJs, { filename: "data.js" });
vm.runInThisContext(engineJs, { filename: "engine.js" });
function press(key) {
  keydownHandlers.forEach(function (fn) { fn({ key: key, preventDefault: function () {} }); });
}
function textOf(id) {
  var el = globalThis.document.getElementById(id);
  function walk(n) {
    var t = String(n.textContent || "");
    for (var i = 0; i < n.children.length; i++) { t += " " + walk(n.children[i]); }
    return t;
  }
  return walk(el);
}
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
async function waitFor(fn, timeoutMs) {
  var deadline = Date.now() + (timeoutMs || 30000);
  while (Date.now() < deadline) {
    if (fn()) { return true; }
    await sleep(10);
  }
  return false;
}
(async function () {
  // generic driver: press any key at the ready screen, then press the FIRST
  // bound key of each response repeatedly until the end screen appears
  var firstKeys = [];
  for (var i = 0; i < PLAN.meta.responses.length; i++) {
    var binding = PLAN.meta.bindings[PLAN.meta.responses[i].name] || {};
    var ks = Object.keys(binding);
    firstKeys.push(ks.length ? ks[0] : " ");
  }
  await waitFor(function () { return textOf("screen").length > 0; }, 20000);
  press(" ");
  var ticks = 0;
  while (ticks < 40000) {
    ticks += 1;
    if (globalThis.document.getElementById("eventlog") && globalThis.document.getElementById("eventlog").value) { break; }
    for (var j = 0; j < firstKeys.length; j++) { press(firstKeys[j]); }
    await sleep(5);
  }
  var ok = await waitFor(function () {
    var el = globalThis.document.getElementById("eventlog");
    return el && el.value;
  }, 30000);
  if (!ok) {
    console.log("__RESULT__" + JSON.stringify({ verdict: "FAIL", detail: "end screen / event log never appeared" }));
    process.exit(0);
  }
  var events = JSON.parse(globalThis.document.getElementById("eventlog").value);
  var starts = events.filter(function (e) { return e.event === "trial_start"; });
  var responses = events.filter(function (e) { return e.event === "response"; });
  var problems = [];
  if (starts.length !== PLAN.meta.total_trials) { problems.push("trial_start count " + starts.length + " != " + PLAN.meta.total_trials); }
  var expected = PLAN.meta.total_trials * PLAN.meta.responses.length;
  if (responses.length !== expected) { problems.push("response count " + responses.length + " != " + expected); }
  for (var r = 0; r < responses.length; r++) {
    var ev = responses[r];
    if (!("value" in ev) || !("correct" in ev) || !("rt_ms" in ev) || !ev.conditions) {
      problems.push("response event missing fields: " + JSON.stringify(ev).slice(0, 80));
      break;
    }
  }
  var screenText = textOf("screen");
  console.log("__RESULT__" + JSON.stringify({
    verdict: problems.length ? "FAIL" : "PASS",
    detail: problems.length ? problems.join("; ")
      : ("classic game playable: " + starts.length + " trials, " + responses.length + " responses, all events structured"
         + (screenText.indexOf("Self-check OK") >= 0 ? "; engine self-check OK" : ""))
  }));
  process.exit(0);
})();
"""

_NODE_CANDIDATES = [
    shutil.which("node"),
    str(Path.home() / ".workbuddy/binaries/node/versions/22.22.2-6/bin/node"),
    "/opt/homebrew/bin/node",
]


def _node_bin() -> str | None:
    for cand in _NODE_CANDIDATES:
        if cand and Path(cand).is_file():
            return cand
    return None


def check_html_interaction(html_path: Path) -> dict[str, Verdict | str]:
    node = _node_bin()
    if node is None:
        return {"verdict": INCONCLUSIVE, "detail": "node runtime not available; researcher review"}
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(_HTML_CHECK_HARNESS_JS, encoding="utf-8")
        proc = subprocess.run(
            [node, str(harness), str(html_path)],
            capture_output=True, text=True, timeout=180,
        )
        result_line = next(
            (ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__")), None
        )
        if proc.returncode != 0 or result_line is None:
            return {"verdict": FAIL, "detail": f"driver crashed: {proc.stderr[:200]}"}
        return cast(dict[str, Verdict | str], json.loads(result_line[len("__RESULT__"):]))


# ---------------------------------------------------------------------------
# Run-record dimensions (D1/D2/D7/D8) from a run report JSON
# ---------------------------------------------------------------------------


def check_run_record(task_id: str, report: dict[str, Any]) -> dict[str, dict[str, Verdict | str]]:
    out: dict[str, dict[str, Verdict | str]] = {}
    scenario = (report.get("scenarios") or [{}])[0]
    status = scenario.get("loop_status")
    tool_calls = cast(list[dict[str, Any]], scenario.get("tool_calls", []))
    n_tool_calls = int(scenario.get("n_tool_calls") or len(tool_calls))
    rendered = any(tc.get("tool") == "render_game" and tc.get("ok") for tc in tool_calls)

    # D1 task completion: loop completed AND an HTML artifact was rendered
    out["D1_task_completion"] = {
        "verdict": PASS if status == "completed" and rendered else FAIL,
        "detail": f"loop_status={status}; render_game_ok={rendered}",
    }

    # D2 tool-call correctness: every call ok (no unknown_tool / invalid args)
    bad = [tc for tc in tool_calls if not tc.get("ok")]
    out["D2_tool_calls"] = {
        "verdict": PASS if not bad else FAIL,
        "detail": f"{n_tool_calls} tool calls, {len(bad)} not-ok"
                  + (f" (first: {bad[0].get('tool')})" if bad else ""),
    }

    # D7 self-repair: distinguish agent repairs during the run from evaluator
    # findings (this dimension reads ONLY the run's own tool feedback)
    repair_hint = scenario.get("detail") or ""
    repaired = any(tc.get("tool") == "validate_game" for tc in tool_calls) and status == "completed"
    out["D7_self_repair"] = {
        "verdict": PASS if repaired else (NOT_APPLICABLE if n_tool_calls == 0 else FAIL),
        "detail": (f"validate_game repair loop observed and run completed ({repair_hint[:120]})"
                   if repaired else
                   "no observed repair-and-complete cycle (either no errors occurred — "
                   "check D2 — or the run did not complete)"),
    }

    # D8 efficiency: tokens / calls / time / cost
    tokens_total = scenario.get("tokens_total")
    cost = scenario.get("cost_estimate_usd")
    if tokens_total is None or cost is None:
        out["D8_efficiency"] = {
            "verdict": NOT_APPLICABLE,
            "detail": "provider reported no usage (never fabricated)",
        }
    else:
        out["D8_efficiency"] = {
            "verdict": PASS,
            "detail": (f"llm_calls={scenario.get('llm_calls')}, tool_calls={n_tool_calls}, "
                       f"wall_s={scenario.get('wall_s')}, tokens={tokens_total} "
                       f"(in={scenario.get('tokens_in')}, out={scenario.get('tokens_out')}), "
                       f"cost_est=${cost}"),
        }
    return out


# ---------------------------------------------------------------------------
# Artifact scoring entry point
# ---------------------------------------------------------------------------


def score_artifacts(task_id: str, bundle_path: Path, html_path: Path | None) -> dict[str, Any]:
    if task_id not in TASKS:
        raise SystemExit(f"unknown task {task_id!r} (known: {sorted(TASKS)})")
    bundle = _load_bundle(bundle_path)
    result: dict[str, Any] = {
        "task": task_id,
        "bundle": str(bundle_path),
        "scorer_version": SCORER_VERSION,
    }
    result["D3_artifact_validity"] = check_artifact_validity(bundle_path, html_path)
    d4 = check_real_manipulation(bundle, task_id)
    d5 = check_answer_recomputation(bundle, task_id)
    invariants = check_task_invariants(bundle, task_id, html_path)
    if invariants["d4_problems"]:
        d4["verdict"] = FAIL
        prefix = "" if d4["detail"] in ("", "ok") else d4["detail"] + "; "
        d4["detail"] = prefix + "[task] " + "; [task] ".join(invariants["d4_problems"])
    if invariants["d5_problems"]:
        d5["verdict"] = FAIL
        prefix = "" if d5["detail"] in ("", "ok") else d5["detail"] + "; "
        d5["detail"] = prefix + "[task] " + "; [task] ".join(invariants["d5_problems"])
    if invariants["notes"]:
        notes = "; ".join(invariants["notes"])
        d4["detail"] = (d4["detail"] + "; " if d4["detail"] not in ("", "ok") else "") + notes
    result["D4_real_manipulation"] = d4
    result["D5_answer_recomputation"] = d5
    result["task_invariants"] = invariants
    if html_path is not None and Path(html_path).is_file():
        result["D6_html_interaction"] = check_html_interaction(Path(html_path))
    else:
        result["D6_html_interaction"] = {
            "verdict": NOT_APPLICABLE,
            "detail": "no HTML artifact (run did not reach render_game)",
        }
    return result


def score_run(task_id: str, report_path: Path) -> dict[str, Any]:
    if task_id not in TASKS:
        raise SystemExit(f"unknown task {task_id!r}")
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    return {"task": task_id, "report": str(report_path), **check_run_record(task_id, report)}


# ---------------------------------------------------------------------------
# Offline validation (--selfcheck): known-good AND known-bad fixed samples
# ---------------------------------------------------------------------------


def _flanker_reference() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "name": "e1-flanker-reference",
        "version": "0.1.0",
        "seed": 4242,
        "factors": [
            {"name": "congruency", "levels": [{"name": "same"}, {"name": "different"}]},
            {"name": "target", "levels": [{"name": "left"}, {"name": "right"}]},
        ],
        "blocks": [{"name": "main", "trial_count": 8}],
        "constraints": {"balance": True},
        "responses": [
            {"name": "answer", "kind": "choice", "options": ["left", "right"], "correct_from": "target"}
        ],
        "timing": {"fixation_ms": 100, "stimulus_ms": None, "isi_ms": 100},
        "stimulus_spec": {
            "pools": {"left_pool": ["<"], "right_pool": [">"], "arrows": ["<", ">"]},
            "variables": [
                {"name": "center", "when": {"target": "left"}, "pool": "left_pool"},
                {"name": "center", "when": {"target": "right"}, "pool": "right_pool"},
                {"name": "flank", "when": {"congruency": "same"}, "copy_from": {"var": "center"}},
                {"name": "flank", "when": {"congruency": "different"}, "pool": "arrows", "exclude": ["center"]},
            ],
            "factors": {
                "congruency": {
                    "levels": {
                        "same": [["{var:flank}{var:flank}{var:center}{var:flank}{var:flank}"]],
                        "different": [["{var:flank}{var:flank}{var:center}{var:flank}{var:flank}"]],
                    },
                    "match_line_count": True,
                }
            },
        },
    }


def _wm_reference() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "name": "e1-wm-reference",
        "version": "0.1.0",
        "seed": 20261022,
        "factors": [
            {"name": "load", "levels": [{"name": "low"}, {"name": "high"}]},
            {"name": "relation", "levels": [{"name": "repeat"}, {"name": "novel"}]},
        ],
        "blocks": [{"name": "main", "trial_count": 8}],
        "constraints": {"balance": True},
        "responses": [
            {
                "name": "judge",
                "kind": "choice",
                "options": ["repeat", "novel"],
                "correct_rule": {
                    "op": "in",
                    "left": {"var": "probe"},
                    "right": {"var": "items"},
                    "true_option": "repeat",
                    "false_option": "novel",
                },
            }
        ],
        "timing": {"fixation_ms": 100, "stimulus_ms": None, "isi_ms": 100},
        "stimulus_spec": {
            "pools": {"tokens": ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]},
            "variables": [
                {"name": "items", "pool": "tokens", "count": {"factor": "load", "levels": {"low": 2, "high": 4}}},
                {"name": "probe", "when": {"relation": "repeat"}, "copy_from": {"var": "items", "index": "any"}},
                {"name": "probe", "when": {"relation": "novel"}, "pool": "tokens", "count": 1, "exclude": ["items"]},
            ],
            "phases": [
                {"name": "encoding", "lines": ["Remember: {var:items}"], "duration_ms": 120, "advance": "auto", "response_window": False},
                {"name": "probe", "lines": ["Probe: {var:probe}"], "duration_ms": None, "advance": "auto", "response_window": True},
            ],
        },
    }


def _taskswitch_reference() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "name": "e1-taskswitch-reference",
        "version": "0.1.0",
        "seed": 55,
        "factors": [
            {"name": "task", "levels": [{"name": "A"}, {"name": "B"}]},
            {"name": "answer", "levels": [{"name": "yes"}, {"name": "no"}]},
        ],
        "blocks": [{"name": "main", "trial_count": 16}],
        "constraints": {"balance": True},
        "responses": [
            {"name": "judge", "kind": "choice", "options": ["yes", "no"], "correct_from": "answer"}
        ],
        "timing": {"fixation_ms": 100, "stimulus_ms": None, "isi_ms": 100},
        "stimulus_spec": {
            "pools": {"yes_words": ["same"], "no_words": ["different"], "all_words": ["same", "different"]},
            "variables": [
                {"name": "aword", "when": {"answer": "yes"}, "pool": "yes_words"},
                {"name": "aword", "when": {"answer": "no"}, "pool": "no_words"},
                {"name": "word", "when": {"task": "A"}, "copy_from": {"var": "aword"}},
                {"name": "word", "when": {"task": "B"}, "pool": "all_words", "exclude": ["aword"]},
            ],
            "phases": [
                {"name": "cue", "lines": ["Task: {task}"], "duration_ms": 150, "advance": "auto", "response_window": False},
                {"name": "stim", "lines": ["Word: {var:word}"], "duration_ms": None, "advance": "auto", "response_window": True},
            ],
        },
    }


def _t2r_nominal_reference() -> dict[str, Any]:
    """The T2R failure pattern (nominal load, no phases) as a fixed bad sample."""
    return {
        "schema_version": 2,
        "name": "e1-t2r-nominal-bad",
        "version": "0.1.0",
        "seed": 42,
        "factors": [
            {"name": "length", "levels": [{"name": "short"}, {"name": "long"}]},
            {"name": "probe_type", "levels": [{"name": "same"}, {"name": "different"}]},
        ],
        "blocks": [{"name": "main", "trial_count": 12}],
        "constraints": {"balance": True},
        "responses": [
            {"name": "response", "kind": "choice", "options": ["same", "different"], "correct_from": "probe_type"}
        ],
        "timing": {"fixation_ms": 200, "stimulus_ms": None, "isi_ms": 200},
        "stimulus_spec": {
            "factors": {
                "length": {
                    "levels": {
                        "short": [["[memory] length: short", "[probe] state: {probe_type}"]],
                        "long": [["[memory] length: long", "[probe] state: {probe_type}"]],
                    },
                    "match_line_count": True,
                }
            },
            "pools": {},
        },
    }


def _t5_reference() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "name": "e1-t5-reference",
        "version": "0.1.0",
        "seed": 11,
        "factors": [{"name": "color", "levels": [{"name": "red"}, {"name": "blue"}]}],
        "blocks": [{"name": "main", "trial_count": 10}],
        "constraints": {"balance": True},
        "responses": [
            {"name": "answer", "kind": "choice", "options": ["red", "blue"], "correct_from": "color"}
        ],
        "timing": {"fixation_ms": 100, "stimulus_ms": None, "isi_ms": 100},
        "stimulus_spec": {
            "factors": {
                "color": {
                    "levels": {"red": [["RED"]], "blue": [["BLUE"]]},
                    "match_line_count": True,
                }
            },
            "pools": {},
        },
    }


# ---------------------------------------------------------------------------
# Adversarial samples (schema-valid but brief-violating): each must FAIL the
# dimension named in its expectation. These pin the task-level checks against
# real requirement violations, not just the generic nominal signature.
# ---------------------------------------------------------------------------


def _flanker_four_arrows_bad() -> dict[str, Any]:
    config = _flanker_reference()
    levels = config["stimulus_spec"]["factors"]["congruency"]["levels"]
    for key in levels:
        levels[key] = [["{var:flank}{var:center}{var:flank}{var:flank}"]]
    config["name"] = "e1-flanker-four-arrows-bad"
    return config


def _flanker_key_from_congruency_bad() -> dict[str, Any]:
    config = _flanker_reference()
    config["name"] = "e1-flanker-key-from-congruency-bad"
    config["responses"] = [
        {"name": "answer", "kind": "choice", "options": ["same", "different"],
         "correct_from": "congruency"}
    ]
    return config


def _flanker_congruency_not_in_flanks_bad() -> dict[str, Any]:
    config = _flanker_reference()
    config["name"] = "e1-flanker-congruency-not-in-flanks-bad"
    config["stimulus_spec"]["variables"] = [
        {"name": "center", "when": {"congruency": "same"}, "pool": "left_pool"},
        {"name": "center", "when": {"congruency": "different"}, "pool": "right_pool"},
        {"name": "flank", "copy_from": {"var": "center"}},
    ]
    return config


def _wm_three_words_bad() -> dict[str, Any]:
    config = _wm_reference()
    config["name"] = "e1-wm-three-words-bad"
    for var in config["stimulus_spec"]["variables"]:
        if var.get("name") == "items" and isinstance(var.get("count"), dict):
            var["count"]["levels"]["low"] = 3
    return config


def _wm_probe_shows_set_bad() -> dict[str, Any]:
    config = _wm_reference()
    config["name"] = "e1-wm-probe-shows-set-bad"
    for ph in config["stimulus_spec"]["phases"]:
        if ph.get("response_window"):
            ph["lines"] = ["Set: {var:items} Probe: {var:probe}"]
    return config


def _taskswitch_flipped_bad() -> dict[str, Any]:
    config = _taskswitch_reference()
    config["name"] = "e1-taskswitch-flipped-bad"
    config["stimulus_spec"]["variables"] = [
        {"name": "aword", "when": {"answer": "yes"}, "pool": "same_words"},
        {"name": "aword", "when": {"answer": "no"}, "pool": "different_words"},
        # task A: word is the OPPOSITE of aword, so 'same' maps to 'no' (flipped)
        {"name": "word", "when": {"task": "A"}, "pool": "all_words", "exclude": ["aword"]},
        {"name": "word", "when": {"task": "B"}, "copy_from": {"var": "aword"}},
    ]
    config["stimulus_spec"]["pools"] = {
        "same_words": ["same"], "different_words": ["different"], "all_words": ["same", "different"],
    }
    return config


def _t5_unbalanced_bad() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "name": "e1-t5-unbalanced-bad",
        "version": "0.1.0",
        "seed": 12,
        "factors": [{"name": "color", "levels": [{"name": "red"}, {"name": "blue"}]}],
        "blocks": [
            {"name": "a", "trial_count": 9, "factor_filter": {"color": ["red"]}, "shuffle_within": False},
            {"name": "b", "trial_count": 1, "factor_filter": {"color": ["blue"]}, "shuffle_within": False},
        ],
        "constraints": {"balance": False},
        "responses": [
            {"name": "answer", "kind": "choice", "options": ["red", "blue"], "correct_from": "color"}
        ],
        "timing": {"fixation_ms": 100, "stimulus_ms": None, "isi_ms": 100},
        "stimulus_spec": {
            "factors": {
                "color": {
                    "levels": {"red": [["RED"]], "blue": [["BLUE"]]},
                    "match_line_count": True,
                }
            },
            "pools": {},
        },
    }


def _t5_identical_content_bad() -> dict[str, Any]:
    config = _t5_reference()
    config["name"] = "e1-t5-identical-content-bad"
    levels = config["stimulus_spec"]["factors"]["color"]["levels"]
    levels["red"] = [["COLOR"]]
    levels["blue"] = [["COLOR"]]
    return config


def _t2r_two_rooms_game_bad() -> dict[str, Any]:
    """An explore GameSpec with only 2 rooms (the brief demands >= 3) — for the
    HTML-level adversarial test (needs rendering; exercised in pytest)."""
    from src.experiment.export import build_bundle
    from src.experiment.schemas import ExperimentSpec

    bundle = build_bundle(
        ExperimentSpec.model_validate(_t2r_good_reference()), generated_at="2000-01-01T00:00:00Z"
    )
    s = cast(dict[str, Any], bundle["spec"])
    r = cast(dict[str, Any], bundle["reproducibility"])
    n = len(cast(list[object], bundle["trials"]))
    half = n // 2
    keys = {"s": "same", "d": "different"}
    return {
        "schema_version": 2,
        "game": {"name": "t2r-two-rooms-bad", "version": "0.1.0"},
        "experiment_ref": {
            "name": s["name"], "version": s["version"], "seed": s["seed"],
            "config_fingerprint": r["config_fingerprint"],
            "trials_fingerprint": r["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {"title": "Station", "instructions": "Explore; memorize; judge."},
        "input": {"modalities": ["keyboard"], "bindings": [{"response_name": "response", "keys": keys}]},
        "feedback": {"on_response": "outcome-text", "duration_ms": 100},
        "world": {
            "start_room": "hall",
            "rooms": {
                "hall": {
                    "title": "Hall", "description": "Dark hall.",
                    "exits": {"lab": "to the lab"},
                    "objects": [
                        {"object_id": f"panel-{i}", "label": f"panel {i}", "inspect_text": "A panel.",
                         "role": "encounter"}
                        for i in range(1, half + 1)
                    ],
                },
                "lab": {
                    "title": "Lab", "description": "Old lab.",
                    "exits": {"hall": "back"},
                    "objects": [
                        {"object_id": f"panel-{i}", "label": f"panel {i}", "inspect_text": "A panel.",
                         "role": "encounter"}
                        for i in range(half + 1, n + 1)
                    ],
                },
            },
        },
        "mechanics": {"layout": "explore-and-encounter", "inspect_objects": True,
                      "trial_trigger": "explore-encounter"},
        "mapping": {
            "trial_trigger": "explore-encounter",
            "encounter_objects": [f"panel-{i}" for i in range(1, n + 1)],
            "response_bindings": [{"response_name": "response", "keys": keys}],
            "creative_freedom": ["theme", "room_labels", "object_labels", "narrative_text",
                                 "feedback_style"],
            "controlled_invariants": ["trial_order", "conditions", "stimulus_content",
                                      "correct_answers", "timing"],
        },
    }


def _t2r_good_reference() -> dict[str, Any]:
    """A brief-compliant T2R design (real load, phases, membership): the
    good-side reference for the HTML-level checks."""
    return {
        "schema_version": 2,
        "name": "e1-t2r-good-reference",
        "version": "0.1.0",
        "seed": 77,
        "factors": [
            {"name": "length", "levels": [{"name": "short"}, {"name": "long"}]},
            {"name": "probe_type", "levels": [{"name": "same"}, {"name": "different"}]},
        ],
        "blocks": [{"name": "main", "trial_count": 12}],
        "constraints": {"balance": True},
        "responses": [
            {"name": "response", "kind": "choice", "options": ["same", "different"],
             "correct_from": "probe_type"}
        ],
        "timing": {"fixation_ms": 50, "stimulus_ms": None, "isi_ms": 50},
        "stimulus_spec": {
            "pools": {"tokens": ["alpha", "beta", "gamma", "delta", "epsilon", "zeta",
                                  "eta", "theta"]},
            "variables": [
                {"name": "seq", "pool": "tokens",
                 "count": {"factor": "length", "levels": {"short": 2, "long": 4}}},
                {"name": "probe", "when": {"probe_type": "same"},
                 "copy_from": {"var": "seq", "index": "any"}},
                {"name": "probe", "when": {"probe_type": "different"},
                 "pool": "tokens", "count": 1, "exclude": ["seq"]},
            ],
            "phases": [
                {"name": "memorize", "lines": ["Memorize: {var:seq}"], "duration_ms": 120,
                 "advance": "auto", "response_window": False},
                {"name": "probe", "lines": ["Probe: {var:probe}"], "duration_ms": None,
                 "advance": "auto", "response_window": True},
            ],
        },
    }


def _write_bundle(config: dict[str, Any], directory: Path, name: str) -> Path:
    from src.experiment.export import build_bundle
    from src.experiment.schemas import ExperimentSpec

    bundle = build_bundle(ExperimentSpec.model_validate(config), generated_at="2000-01-01T00:00:00Z")
    path = directory / f"{name}.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return path


def run_selfcheck(out_dir: Path | None = None) -> dict[str, Any]:
    """Offline validation matrix: the scorer's behavior on fixed samples.

    Expected outcomes (the scorer is WRONG if any of these flip):
      - t5/flanker/wm/taskswitch/t2r-good references -> D4 PASS, D5 PASS
      - t2r nominal bad sample                     -> D4 FAIL (the T2R signature)
      - ADVERSARIAL samples (schema-valid, brief-violating):
          flanker_four_arrows            -> D4 FAIL (not exactly five arrows)
          flanker_key_from_congruency    -> D5 FAIL (center does not decide)
          flanker_congruency_not_in_flanks -> D4 FAIL (congruency never varies)
                                          +  D5 FAIL (target no longer affects
                                             content, so the key is not derivable)
          wm_three_words                 -> D4 FAIL (3 memorized words)
          wm_probe_shows_set             -> D4 FAIL (probe phase shows the set)
          taskswitch_flipped             -> D5 FAIL (literal direction inverted)
          t5_unbalanced                  -> D4 FAIL (9/1 colors)
          t5_identical_content           -> D4 FAIL + D5 FAIL (same display, two keys)
      - historical T5 bundle (if present) -> D3 PASS, D4 note, D5 PASS
      - historical T2R bundle (if present)-> D4 FAIL on the REAL artifact
      - run records T5/T2R (if present)   -> D1 PASS / D1 FAIL respectively
    """
    from src.experiment.validation import validate_spec

    results: dict[str, Any] = {"scorer_version": SCORER_VERSION}
    tmp = out_dir or Path(tempfile.mkdtemp(prefix="e1-selfcheck-"))
    tmp.mkdir(parents=True, exist_ok=True)

    for task_id, config, expect_d4, expect_d5 in (
        ("e1_t5_retest", _t5_reference(), PASS, PASS),
        ("e1_flanker", _flanker_reference(), PASS, PASS),
        ("e1_wm", _wm_reference(), PASS, PASS),
        ("e1_taskswitch", _taskswitch_reference(), PASS, PASS),
        ("e1_t2r_regression", _t2r_good_reference(), PASS, PASS),
        ("e1_t2r_regression", _t2r_nominal_reference(), FAIL, PASS),
        # adversarial samples (schema-valid but brief-violating)
        ("e1_flanker", _flanker_four_arrows_bad(), FAIL, PASS),
        ("e1_flanker", _flanker_key_from_congruency_bad(), PASS, FAIL),
        ("e1_flanker", _flanker_congruency_not_in_flanks_bad(), FAIL, FAIL),
        ("e1_wm", _wm_three_words_bad(), FAIL, PASS),
        ("e1_wm", _wm_probe_shows_set_bad(), FAIL, PASS),
        ("e1_taskswitch", _taskswitch_flipped_bad(), PASS, FAIL),
        ("e1_t5_retest", _t5_unbalanced_bad(), FAIL, PASS),
        ("e1_t5_retest", _t5_identical_content_bad(), FAIL, FAIL),
    ):
        # the reference itself must be a valid spec (a broken reference would
        # make the expected verdicts meaningless)
        v = validate_spec(config)
        assert v.valid, (config["name"], [(e.error_code, e.message) for e in v.errors])
        name = str(config["name"])
        path = _write_bundle(config, tmp, name)
        scored = score_artifacts(task_id, path, None)
        results[name] = {
            "task": task_id,
            "D4": scored["D4_real_manipulation"],
            "D5": scored["D5_answer_recomputation"],
            "expected_D4": expect_d4,
            "expected_D5": expect_d5,
            "as_expected": (
                scored["D4_real_manipulation"]["verdict"] == expect_d4
                and scored["D5_answer_recomputation"]["verdict"] == expect_d5
            ),
        }

    # historical REAL artifacts (local, gitignored — skipped when absent)
    hist_t5 = REPO_ROOT / "data" / ".test-sandbox" / "model-eval-real" / "experiments" / "eval-t5.json"
    hist_t2r = REPO_ROOT / "data" / ".test-sandbox" / "model-eval-t2-real" / "experiments" / "t2-real.json"
    if hist_t5.is_file():
        scored = score_artifacts("e1_t5_retest", hist_t5, None)
        results["historical_t5_bundle"] = {
            "D3": scored["D3_artifact_validity"],
            "D5": scored["D5_answer_recomputation"],
            "as_expected": (
                scored["D3_artifact_validity"]["verdict"] == PASS
                and scored["D5_answer_recomputation"]["verdict"] == PASS
            ),
        }
    else:
        results["historical_t5_bundle"] = {"as_expected": None, "note": "historical artifact not present locally"}
    if hist_t2r.is_file():
        scored = score_artifacts("e1_t2r_regression", hist_t2r, None)
        d4 = scored["D4_real_manipulation"]
        results["historical_t2r_bundle"] = {
            "D3": scored["D3_artifact_validity"],
            "D4": d4,
            "as_expected": (
                scored["D3_artifact_validity"]["verdict"] == PASS  # schema-valid…
                and d4["verdict"] == FAIL                          # …but scientifically nominal
            ),
            "note": "the real T2R artifact must be schema-valid AND D4-FAIL "
                    "(schema validity is not scientific validity)",
        }
    else:
        results["historical_t2r_bundle"] = {"as_expected": None, "note": "historical artifact not present locally"}

    # historical run records (D1/D7 separation: T5 completed, T2R budget-stopped)
    rep_t5 = REPO_ROOT / "data" / ".test-sandbox" / "model-eval-real" / "eval-report-t5.json"
    rep_t2r = REPO_ROOT / "data" / ".test-sandbox" / "model-eval-t2-real" / "eval-report-t2r.json"
    if rep_t5.is_file():
        run = score_run("e1_t5_retest", rep_t5)
        results["historical_t5_run"] = {
            "D1": run["D1_task_completion"],
            "as_expected": run["D1_task_completion"]["verdict"] == PASS,
        }
    if rep_t2r.is_file():
        run = score_run("e1_t2r_regression", rep_t2r)
        results["historical_t2r_run"] = {
            "D1": run["D1_task_completion"],
            "as_expected": run["D1_task_completion"]["verdict"] == FAIL,
        }

    # known-bad key corruption: D5 must FAIL when the key contradicts content
    wm = _wm_reference()
    from src.experiment.export import build_bundle
    from src.experiment.schemas import ExperimentSpec

    bundle = build_bundle(ExperimentSpec.model_validate(wm), generated_at="2000-01-01T00:00:00Z")
    trials = cast(list[dict[str, Any]], bundle["trials"])
    for t in trials:  # flip every key: relation repeat<->novel inverted
        if "correct" in t:
            t["correct"]["judge"] = "novel" if t["correct"]["judge"] == "repeat" else "repeat"
    bad_path = tmp / "key-corruption.json"
    bad_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    scored = score_artifacts("e1_wm", bad_path, None)
    results["key_corruption_bad_sample"] = {
        "D5": scored["D5_answer_recomputation"],
        "as_expected": scored["D5_answer_recomputation"]["verdict"] == FAIL,
        "note": "inverted answer keys must be caught by probe-membership recomputation",
    }

    results["_all_as_expected"] = all(
        v.get("as_expected") is True for v in results.values() if isinstance(v, dict)
    )
    return results


def _print_results(results: dict[str, Any]) -> None:
    print(json.dumps(results, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="E1 independent scorer (no LLM, no network)")
    parser.add_argument("--selfcheck", action="store_true", help="run the offline validation matrix")
    parser.add_argument("--task", choices=sorted(TASKS), help="task id to score")
    parser.add_argument("--bundle", type=str, help="path to the exported bundle JSON")
    parser.add_argument("--html", type=str, default=None, help="path to the rendered HTML (optional)")
    parser.add_argument("--report", type=str, default=None, help="path to the run report JSON (run-side dims)")
    parser.add_argument("--out", type=str, default=None, help="write results JSON here")
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    if args.selfcheck:
        results = run_selfcheck(Path(args.out).parent if args.out else None)
        _print_results(results)
        if args.out:
            Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        raise SystemExit(0 if results["_all_as_expected"] else 1)

    if not args.task or not args.bundle:
        parser.error("--task and --bundle are required (or --selfcheck)")
    results: dict[str, Any] = score_artifacts(args.task, Path(args.bundle), Path(args.html) if args.html else None)
    if args.report:
        results.update(score_run(args.task, Path(args.report)))
    _print_results(results)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
