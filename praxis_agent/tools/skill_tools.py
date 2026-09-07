"""Tools that let the agent discover and load skill files on demand — domain/technique
knowledge the agent explicitly decides it needs, rather than silently injected via RAG.
Mirrors this CLI's own skill-invocation pattern.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import tool

from praxis_agent.agent.context import get_current_bus
from praxis_agent.agent.events import EventType
from praxis_agent.tools._tool_utils import instrumented

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _parse_skill_file(path: Path) -> dict[str, Any]:
    text = path.read_text()
    frontmatter: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
    return {
        "name": frontmatter.get("name", path.stem),
        "tags": frontmatter.get("tags", []),
        "summary": frontmatter.get("summary", ""),
        "body": body,
        "file": path.name,
    }


def _all_skills() -> list[dict[str, Any]]:
    if not SKILLS_DIR.exists():
        return []
    return [_parse_skill_file(p) for p in sorted(SKILLS_DIR.glob("*.md"))]


@tool
@instrumented("list_skills")
async def list_skills() -> list[dict]:
    """List every available skill: domain/technique playbooks (e.g. concurrency-testing,
    mock-based-testing, performance-testing, production-issue-repro) and service-specific
    notes (e.g. mob-service, edi-service). Returns name/tags/summary only — call load_skill
    with the name to get the full content before relying on it."""
    return [{"name": s["name"], "tags": s["tags"], "summary": s["summary"]} for s in _all_skills()]


@tool
@instrumented("load_skill")
async def load_skill(name: str) -> str:
    """Load the full content of a skill by name (see list_skills). Call this whenever you're
    about to do something technique-specific (concurrency testing, mock-based testing,
    performance testing, production repro) or need service-specific domain notes, before
    acting, so your plan follows the established playbook rather than improvising."""
    for skill in _all_skills():
        if skill["name"] == name or skill["file"] == name or skill["file"] == f"{name}.md":
            bus = get_current_bus()
            if bus:
                bus.publish(EventType.SKILL_LOADED, {"name": skill["name"]})
            return skill["body"]
    available = ", ".join(s["name"] for s in _all_skills())
    return f"No skill named '{name}' found. Available skills: {available}"
