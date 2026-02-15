"""
openclaw_actions.py

Native OpenClaw skills loader + action executor for IVI voice interface.
Loads SKILL.md files from bundled/managed/workspace locations,
gates by platform/bins, and provides base execution tools.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import ssl
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Native OpenClaw Skill Loader
# ---------------------------------------------------------------------------

@dataclass
class OpenClawSkill:
    name: str
    description: str
    path: Path
    instructions: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    eligible: bool = True
    gate_reason: str = ""


def _parse_skill_md(skill_path: Path) -> Optional[OpenClawSkill]:
    try:
        raw = skill_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", raw, re.DOTALL)
    if not fm_match:
        return None
    fm_text = fm_match.group(1)
    body = fm_match.group(2).strip()
    name = ""
    description = ""
    metadata: Dict[str, Any] = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if line.startswith("name:"):
            name = line[5:].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            description = line[12:].strip().strip('"').strip("'")
        elif line.startswith("metadata:"):
            pass
        elif line.startswith("{") and not metadata:
            try:
                rest = fm_text[fm_text.index("{"):]
                brace_depth = 0
                end = 0
                for i, c in enumerate(rest):
                    if c == "{":
                        brace_depth += 1
                    elif c == "}":
                        brace_depth -= 1
                        if brace_depth == 0:
                            end = i + 1
                            break
                if end:
                    metadata = json.loads(rest[:end])
            except (json.JSONDecodeError, ValueError):
                pass
    if not name:
        name = skill_path.parent.name
    return OpenClawSkill(
        name=name,
        description=description,
        path=skill_path,
        instructions=body[:2000],
        metadata=metadata,
    )


def _gate_skill(skill: OpenClawSkill) -> Tuple[bool, str]:
    oc = skill.metadata.get("openclaw", {})
    if not isinstance(oc, dict):
        return True, ""
    os_list = oc.get("os", [])
    if os_list and isinstance(os_list, list):
        current = platform.system().lower()
        plat_map = {"darwin": "darwin", "linux": "linux", "windows": "win32"}
        if plat_map.get(current, current) not in os_list:
            return False, f"os:{current} not in {os_list}"
    requires = oc.get("requires", {})
    if not isinstance(requires, dict):
        return True, ""
    bins = requires.get("bins", [])
    if isinstance(bins, list):
        for b in bins:
            if not shutil.which(str(b)):
                return False, f"missing bin: {b}"
    any_bins = requires.get("anyBins", [])
    if isinstance(any_bins, list) and any_bins:
        if not any(shutil.which(str(b)) for b in any_bins):
            return False, f"none of anyBins found: {any_bins}"
    env_reqs = requires.get("env", [])
    if isinstance(env_reqs, list):
        for e in env_reqs:
            if not os.environ.get(str(e)):
                return False, f"missing env: {e}"
    return True, ""


def discover_skills(
    openclaw_repo: Optional[str] = None,
    workspace: Optional[str] = None,
) -> List[OpenClawSkill]:
    skill_dirs: List[Path] = []
    home = Path.home()
    managed = home / ".openclaw" / "skills"
    if managed.is_dir():
        skill_dirs.append(managed)
    if openclaw_repo:
        bundled = Path(openclaw_repo) / "skills"
        if bundled.is_dir():
            skill_dirs.append(bundled)
    else:
        for candidate in [
            home / "Purple" / "openclaw" / "skills",
            home / ".openclaw" / "bundled" / "skills",
        ]:
            if candidate.is_dir():
                skill_dirs.append(candidate)
                break
    if workspace:
        ws = Path(workspace) / "skills"
        if ws.is_dir():
            skill_dirs.append(ws)
    seen: Dict[str, OpenClawSkill] = {}
    for sdir in skill_dirs:
        try:
            for entry in sorted(sdir.iterdir()):
                if not entry.is_dir():
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.is_file():
                    continue
                skill = _parse_skill_md(skill_md)
                if skill is None:
                    continue
                eligible, reason = _gate_skill(skill)
                skill.eligible = eligible
                skill.gate_reason = reason
                seen[skill.name] = skill
        except OSError:
            pass
    return list(seen.values())


def format_skills_for_prompt(skills: List[OpenClawSkill], max_skills: int = 20) -> str:
    eligible = [s for s in skills if s.eligible]
    if not eligible:
        return ""
    lines = ["## Available OpenClaw Skills"]
    for s in eligible[:max_skills]:
        emoji = s.metadata.get("openclaw", {}).get("emoji", "")
        prefix = f"{emoji} " if emoji else ""
        lines.append(f"- **{prefix}{s.name}**: {s.description}")
        if s.instructions:
            summary = s.instructions[:200].replace("\n", " ").strip()
            lines.append(f"  {summary}")
    lines.append("")
    lines.append(f"Total: {len(eligible)} skills available. Use them via bash/run_command.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Saved skills (user-created via save_skill tool)
# ---------------------------------------------------------------------------

SKILLS_DIR_NAME = ".openclaw_skills"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Returns the text content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative path to the file to read."},
                    "max_lines": {"type": "integer", "description": "Max lines to return (default 200).", "default": 200},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and directories at a path. Returns names with / suffix for directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to list. Defaults to current directory."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return stdout/stderr. Use for analysis, searching, testing. Timeout 30s.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run."},
                    "cwd": {"type": "string", "description": "Working directory. Defaults to CWD."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates parent directories if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to write to."},
                    "content": {"type": "string", "description": "Content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_skill",
            "description": "Save a reusable script/tool to the skills directory for future use.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name (used as filename, e.g. 'analyze_math')."},
                    "description": {"type": "string", "description": "What this skill does."},
                    "code": {"type": "string", "description": "Python code for the skill."},
                },
                "required": ["name", "description", "code"],
            },
        },
    },
]


def _ensure_skills_dir(base_path: str) -> Path:
    skills = Path(base_path) / SKILLS_DIR_NAME
    skills.mkdir(parents=True, exist_ok=True)
    return skills


def execute_tool(name: str, arguments: Dict[str, Any], base_path: str = ".") -> str:
    try:
        if name == "read_file":
            return _exec_read_file(arguments)
        elif name == "list_dir":
            return _exec_list_dir(arguments)
        elif name == "run_command":
            return _exec_run_command(arguments)
        elif name == "write_file":
            return _exec_write_file(arguments)
        elif name == "save_skill":
            return _exec_save_skill(arguments, base_path)
        else:
            return f"Unknown tool: {name}"
    except Exception as exc:
        return f"Error executing {name}: {exc}"


def _exec_read_file(args: Dict[str, Any]) -> str:
    path = Path(args["path"]).expanduser()
    if not path.exists():
        return f"File not found: {path}"
    if not path.is_file():
        return f"Not a file: {path}"
    max_lines = int(args.get("max_lines", 200))
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if len(lines) > max_lines:
            return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
        return "\n".join(lines)
    except OSError as exc:
        return f"Cannot read {path}: {exc}"


def _exec_list_dir(args: Dict[str, Any]) -> str:
    path = Path(args.get("path", ".")).expanduser()
    if not path.exists():
        return f"Path not found: {path}"
    if not path.is_dir():
        return f"Not a directory: {path}"
    items: List[str] = []
    try:
        for entry in sorted(path.iterdir()):
            if entry.name.startswith("."):
                continue
            label = f"{entry.name}/" if entry.is_dir() else entry.name
            items.append(label)
            if len(items) >= 50:
                break
    except OSError as exc:
        return f"Cannot list {path}: {exc}"
    return "\n".join(items) if items else "(empty directory)"


def _exec_run_command(args: Dict[str, Any]) -> str:
    command = str(args["command"])
    cwd = args.get("cwd") or None
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        output = ""
        if result.stdout:
            output += result.stdout[:4000]
        if result.stderr:
            output += f"\n[stderr] {result.stderr[:2000]}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "[command timed out after 30s]"
    except OSError as exc:
        return f"Cannot run command: {exc}"


def _exec_write_file(args: Dict[str, Any]) -> str:
    path = Path(args["path"]).expanduser()
    content = str(args["content"])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Written {len(content)} bytes to {path}"
    except OSError as exc:
        return f"Cannot write {path}: {exc}"


def _exec_save_skill(args: Dict[str, Any], base_path: str) -> str:
    name = str(args["name"]).strip().replace(" ", "_").replace("/", "_")
    description = str(args.get("description", ""))
    code = str(args["code"])
    skills_dir = _ensure_skills_dir(base_path)
    skill_path = skills_dir / f"{name}.py"
    header = f'"""\nSkill: {name}\n{description}\n"""\n\n'
    skill_path.write_text(header + code, encoding="utf-8")
    return f"Skill saved: {skill_path}"


def list_skills(base_path: str = ".") -> List[Dict[str, str]]:
    skills_dir = Path(base_path) / SKILLS_DIR_NAME
    if not skills_dir.is_dir():
        return []
    skills: List[Dict[str, str]] = []
    for f in sorted(skills_dir.glob("*.py")):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            first_lines = text[:200]
            skills.append({"name": f.stem, "path": str(f), "preview": first_lines})
        except OSError:
            pass
    return skills


def llm_chat_with_tools(
    system: str,
    messages: List[Dict[str, Any]],
    base_path: str = ".",
    model: str = "",
    max_tokens: int = 1024,
    max_tool_rounds: int = 5,
) -> str:
    import ssl as _ssl
    import urllib.request as _urllib

    from .openclaw_adapter import _load_dotenv

    _load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    resolved_model = model or os.environ.get("OPENCLAW_MODEL", "gpt-4o-mini")

    chat_messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
    chat_messages.extend(messages)

    for _round in range(max_tool_rounds):
        body = json.dumps({
            "model": resolved_model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "tools": TOOLS,
        }).encode("utf-8")

        req = _urllib.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            ctx = _ssl.create_default_context()
            with _urllib.urlopen(req, timeout=45, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            _log.debug("Tool LLM call failed: %s", exc)
            return ""

        choices = data.get("choices", [])
        if not choices:
            return ""

        choice = choices[0]
        message = choice.get("message", {})
        finish = choice.get("finish_reason", "")

        if finish == "tool_calls" or message.get("tool_calls"):
            chat_messages.append(message)
            tool_calls = message.get("tool_calls", [])
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}
                result = execute_tool(tool_name, tool_args, base_path=base_path)
                chat_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result,
                })
            continue

        content = str(message.get("content", "")).strip()
        return content

    return ""
