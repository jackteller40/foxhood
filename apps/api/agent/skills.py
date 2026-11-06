"""Skills: reusable, documented procedures in skills/<name>/SKILL.md (YAML frontmatter + body).

Progressive disclosure: the system prompt lists only each skill's name and description; the
agent calls load_skill to read the full instructions when a task needs one."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from langchain_core.tools import tool

from core.config import ROOT

SKILLS_DIR = ROOT / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path


def _parse(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path} is missing YAML frontmatter")
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter) or {}
    name, desc = meta.get("name"), meta.get("description")
    if not name or not desc:
        raise ValueError(f"{path}: frontmatter needs 'name' and 'description'")
    if name != path.parent.name:
        raise ValueError(f"{path}: name '{name}' must match its folder '{path.parent.name}'")
    return Skill(name=name, description=" ".join(str(desc).split()), body=body.strip(), path=path)


def discover_skills() -> dict[str, Skill]:
    """Read fresh on every run, so edits to a SKILL.md apply without restarting."""
    return {s.name: s for s in (_parse(p) for p in sorted(SKILLS_DIR.glob("*/SKILL.md")))}


def catalog_text(skills: dict[str, Skill]) -> str:
    if not skills:
        return "(none)"
    return "\n".join(f"- {s.name}: {s.description}" for s in skills.values())


def make_skill_tool(skills: dict[str, Skill]):
    names = sorted(skills)

    @tool
    def load_skill(name: str) -> str:
        """Load the full step-by-step instructions for one skill listed under AVAILABLE SKILLS.
        Call this before starting a task a skill covers, then follow the instructions exactly."""
        skill = skills.get(name.strip())
        if skill is None:
            return json.dumps({"error": f"Unknown skill '{name}'. Available: {names}"})
        return f"# SKILL: {skill.name}\n\n{skill.body}"

    return load_skill