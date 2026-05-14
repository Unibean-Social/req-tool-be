"""Builds the body_snapshot dict for any hierarchy item."""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.requirements import Epic, Feature, Story, Task


def _references_section(refs: list[str]) -> str:
    if not refs:
        return ""
    lines = "\n".join(f"- {r}" for r in refs)
    return f"\n\n### References\n{lines}"


def format_epic(epic: "Epic") -> dict[str, Any]:
    refs = epic.references or []
    body = (
        f"### Summary\n"
        f"**Prefix:** {epic.prefix}  \n"
        f"**Type:** Epic\n\n"
        f"### Information\n"
        f"**Description:** {epic.description or '_No description_'}  \n"
        f"**Status:** {epic.status.value}  \n"
        f"**Priority:** {epic.priority.value}"
        f"{_references_section(refs)}"
    )
    return {
        "title": f"{epic.prefix} — {epic.title}",
        "body": body,
        "github_labels": list(epic.labels or []),
    }


def format_feature(feature: "Feature") -> dict[str, Any]:
    refs = feature.references or []
    body = (
        f"### Summary\n"
        f"**Prefix:** {feature.prefix}  \n"
        f"**Type:** Feature\n\n"
        f"### Information\n"
        f"**Description:** {feature.description or '_No description_'}  \n"
        f"**Status:** {feature.status.value}  \n"
        f"**Priority:** {feature.priority.value}  \n"
        f"**NFR Note:** {feature.nfr_note or '_None_'}"
        f"{_references_section(refs)}"
    )
    return {
        "title": f"{feature.prefix} — {feature.title}",
        "body": body,
        "github_labels": list(feature.labels or []),
    }


def format_story(story: "Story") -> dict[str, Any]:
    refs = story.references or []

    ac_lines = ""
    if story.acceptance_criteria:
        items = "\n".join(f"- [ ] {ac.description}" for ac in story.acceptance_criteria)
        ac_lines = f"\n\n### Acceptance Criteria\n{items}"

    body = (
        f"### Summary\n"
        f"**Prefix:** {story.prefix}  \n"
        f"**Type:** Story\n\n"
        f"### Information\n"
        f"**Description:** {story.description or '_No description_'}  \n"
        f"**Status:** {story.status.value}  \n"
        f"**Priority:** {story.priority.value}  \n"
        f"**Actor:** {story.actor_ref or '_None_'}  \n"
        f"**Action:** {story.action_text or '_None_'}  \n"
        f"**Goal:** {story.goal_text or '_None_'}"
        f"{ac_lines}"
        f"{_references_section(refs)}"
    )
    return {
        "title": f"{story.prefix} — {story.title}",
        "body": body,
        "github_labels": list(story.labels or []),
    }


def format_task(task: "Task") -> dict[str, Any]:
    refs = task.references or []
    body = (
        f"### Summary\n"
        f"**Prefix:** {task.prefix}  \n"
        f"**Type:** Task\n\n"
        f"### Information\n"
        f"**Description:** {task.description or '_No description_'}  \n"
        f"**Status:** {task.status.value}  \n"
        f"**Priority:** {task.priority.value}"
        f"{_references_section(refs)}"
    )
    return {
        "title": f"{task.prefix} — {task.title}",
        "body": body,
        "github_labels": list(task.labels or []),
    }


def format_item(item: Any, item_type: str) -> dict[str, Any]:
    if item_type == "epic":
        return format_epic(item)
    if item_type == "feature":
        return format_feature(item)
    if item_type == "story":
        return format_story(item)
    if item_type == "task":
        return format_task(item)
    raise ValueError(f"Unknown item_type: {item_type}")
