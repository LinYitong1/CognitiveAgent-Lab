"""Documentation-consistency tests for the public Codex Agent Skill.

Scope — what these tests DO cover (documentation invariants):

- ``skills/cognitive-agent/SKILL.md`` is a structurally valid skill file
  (frontmatter with required ``name``/``description`` fields, sane limits,
  name matching the directory);
- the embedded Python example is syntactically valid Python;
- the documented install URL points at this repository's actual git remote.

Scope — what these tests deliberately DO NOT cover (agent behavior):

- whether an external agent (Codex or other) picks the right workflow for a
  given natural-language request, builds a valid ExperimentSpec from it, or
  honors the documented boundaries. That is interactive agent behavior and
  cannot be asserted from this repository; the ``description`` frontmatter is
  the trigger surface for it, so at minimum these tests assert the
  description names the trigger conditions.

The workflows themselves are exercised end-to-end elsewhere (integration
tests, the ``cognitive-agent`` CLI tests and the recorded fresh-install
verification in the skill's delivery commit).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "cognitive-agent"
SKILL_PATH = SKILL_DIR / "SKILL.md"


def _read_skill() -> str:
    assert SKILL_PATH.is_file(), f"missing skill file: {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    """Minimal frontmatter parser (no pyyaml dependency needed for two flat keys)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m is not None, "SKILL.md must start with a YAML frontmatter block"
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        fm = re.match(r"^([a-z_]+): (.+)$", line)
        if fm:
            fields[fm.group(1)] = fm.group(2).strip().strip("'\"")
    return fields


def test_skill_frontmatter_has_required_fields() -> None:
    fields = _frontmatter(_read_skill())
    assert "name" in fields, "frontmatter must contain 'name'"
    assert "description" in fields, "frontmatter must contain 'description'"


def test_skill_name_matches_directory_and_limits() -> None:
    fields = _frontmatter(_read_skill())
    name = fields["name"]
    assert name == SKILL_DIR.name, "skill name must match its directory name"
    assert re.fullmatch(r"[a-z0-9-]+", name) is not None, "name must be a slug"
    assert len(name) <= 64, "name must be at most 64 characters"


def test_skill_description_is_trigger_condition() -> None:
    description = _frontmatter(_read_skill())["description"]
    assert 32 <= len(description) <= 1024, "description within sane length limits"
    lowered = description.lower()
    # The description is the implicit-invocation trigger surface: it must say
    # what the skill does and when to use it (validated capability keywords).
    assert "experiment" in lowered, "description must name the experiment domain"
    assert "use when" in lowered, "description must state when to trigger"
    assert "no llm" in lowered or "not invoke any llm" in lowered or "deterministic" in lowered


def test_skill_python_example_compiles() -> None:
    """The worked example must be syntactically valid Python (compile-only)."""
    text = _read_skill()
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    assert blocks, "SKILL.md must contain at least one python example block"
    for i, block in enumerate(blocks):
        compile(block, f"<SKILL.md python block {i}>", "exec")


def test_skill_install_url_matches_git_remote() -> None:
    """The documented pip install URL must point at this repository's remote."""
    text = _read_skill()
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=True,
    ).stdout.strip()
    # normalize git@github.com:o/r.git and https://github.com/o/r.git forms
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", remote)
    assert m is not None, f"unparsable origin remote: {remote}"
    repo_slug = m.group(1)
    expected_url = f"git+https://github.com/{repo_slug}.git"
    assert expected_url in text, (
        f"SKILL.md must document the install URL {expected_url} (origin: {remote})"
    )


def test_skill_documents_all_cli_workflows() -> None:
    """The skill's bash examples must exercise the real CLI surface."""
    text = _read_skill()
    for command in ("cognitive-agent demo", "cognitive-agent verify"):
        assert command in text, f"SKILL.md must document '{command}'"
    # the real-LLM path must be explicitly fenced as opt-in only
    assert "run" in text and ("explicitly" in text or "Never run" in text)
