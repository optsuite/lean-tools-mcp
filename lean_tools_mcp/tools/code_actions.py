# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_code_actions — inspect quick fixes and other code actions at a position.
"""

from __future__ import annotations

from typing import Any

from ..project.manager import LeanProjectManager


def _format_single_action(index: int, action: dict[str, Any]) -> str:
    title = action.get("title", "<untitled action>")
    kind = action.get("kind", "")
    preferred = action.get("isPreferred")
    disabled = action.get("disabled")
    command = action.get("command")

    lines = [f"{index}. {title}"]
    if kind:
        lines.append(f"   Kind: {kind}")
    if preferred is True:
        lines.append("   Preferred: yes")
    if isinstance(disabled, dict) and disabled.get("reason"):
        lines.append(f"   Disabled: {disabled['reason']}")
    if isinstance(command, dict):
        command_id = command.get("command", "")
        command_title = command.get("title", "")
        command_text = command_id or command_title
        if command_text:
            lines.append(f"   Command: {command_text}")
    elif isinstance(action.get("command"), str):
        lines.append(f"   Command: {action['command']}")
    elif action.get("edit"):
        lines.append("   Edit: workspace edit available")
    return "\n".join(lines)


def _format_code_actions(actions: list[dict[str, Any]], max_actions: int = 20) -> str:
    if not actions:
        return "No code actions available at this position."

    shown = actions[:max_actions]
    lines = [f"Code actions ({len(shown)} shown):"]
    lines.extend(_format_single_action(i, action) for i, action in enumerate(shown, 1))

    if len(actions) > len(shown):
        lines.append(f"... {len(actions) - len(shown)} more action(s) omitted.")

    return "\n".join(lines)


async def lean_code_actions(
    project_manager: LeanProjectManager,
    *,
    file_path: str,
    line: int,
    column: int,
    end_line: int | None = None,
    end_column: int | None = None,
    max_actions: int = 20,
) -> str:
    """Get code actions for a position or small range."""
    actions = await project_manager.code_actions(
        file_path=file_path,
        line=line,
        column=column,
        end_line=end_line,
        end_column=end_column,
    )
    return _format_code_actions(actions, max_actions=max_actions)
