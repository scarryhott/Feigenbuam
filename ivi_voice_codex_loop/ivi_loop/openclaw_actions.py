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


def format_skills_for_prompt(skills: List[OpenClawSkill], max_skills: int = 15) -> str:
    eligible = [s for s in skills if s.eligible]
    if not eligible:
        return ""
    names = [s.name for s in eligible[:max_skills]]
    remaining = len(eligible) - len(names)
    text = "Available skills: " + ", ".join(names)
    if remaining > 0:
        text += f" (+{remaining} more)"
    return text


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


def execute_tool(name: str, arguments: Dict[str, Any], base_path: str = ".", gateway: Any = None) -> str:
    # --- Gateway intent before tool execution ---
    gw_packet = None
    if gateway is not None:
        try:
            # Classify tool action
            action_class = "read"
            if name in ("write_file", "save_skill"):
                action_class = "write"
            elif name == "run_command":
                action_class = "execute"
            req_paths = []
            if "path" in arguments:
                req_paths = [str(arguments["path"])]

            gw_packet = gateway.ingress(
                raw_input=f"tool:{name} {json.dumps(arguments)[:150]}",
                channel="openclaw_tool",
                actor="openclaw",
                order1_classification="action",
                requested_action_class=action_class,
                requested_tools=[name],
                requested_paths=req_paths,
                order_mode="order_3_constrained_write",
            )
            gateway.propose(gw_packet)
            gw_report = gateway.verify(gw_packet)
            if not gw_report.passed:
                return f"[gateway blocked] {', '.join(gw_report.reason_codes)}"
        except Exception:
            pass  # gateway errors are non-blocking

    try:
        if name == "read_file":
            result = _exec_read_file(arguments)
        elif name == "list_dir":
            result = _exec_list_dir(arguments)
        elif name == "run_command":
            result = _exec_run_command(arguments)
        elif name == "write_file":
            result = _exec_write_file(arguments)
        elif name == "save_skill":
            result = _exec_save_skill(arguments, base_path)
        else:
            result = f"Unknown tool: {name}"
    except Exception as exc:
        result = f"Error executing {name}: {exc}"

    # --- Gateway attest after tool execution ---
    if gateway is not None and gw_packet is not None:
        try:
            from .storage import append_attest
            append_attest(
                gateway._settings,
                intent_id=gw_packet.intent_id,
                diff_stats={"tool": name, "result_len": len(result)},
                committed="Error" not in result and "blocked" not in result,
            )
        except Exception:
            pass

    return result


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

    # Two-phase execution through IVI Semantic Enforcement Duality
    try:
        from .ivi_semantic_enforcement import IVISemanticEnforcementDuality
        duality = IVISemanticEnforcementDuality(base_path=base_path)
        committed, msg, proposal = duality.propose_and_commit(
            kind="skill_save",
            description=f"Save skill: {name} — {description[:80]}",
            payload={"name": name, "description": description, "code": code, "source": "llm"},
        )
        if not committed:
            return f"Skill rejected by IVI enforcement: {msg}"
    except Exception:
        pass  # Fallback to direct save if duality unavailable

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


_MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    "gpt-4o-mini": 128000,
    "gpt-4o": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
}
_SAFE_TOKEN_MARGIN = 2000


def _estimate_tokens(messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None) -> int:
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, str):
            total += len(content) // 3
        tcs = m.get("tool_calls") or []
        for tc in tcs:
            fn = tc.get("function", {})
            total += len(fn.get("arguments", "")) // 3
    if tools:
        total += len(json.dumps(tools)) // 4
    return total


def _compact_tool_messages(messages: List[Dict[str, Any]], budget_chars: int = 6000) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    tool_summaries: List[str] = []
    for m in messages:
        if m.get("role") == "tool":
            content = str(m.get("content", ""))
            if len(content) > 300:
                content = content[:300] + "..."
            tool_summaries.append(content)
        elif m.get("role") == "assistant" and m.get("tool_calls"):
            tcs = m.get("tool_calls", [])
            names = [tc.get("function", {}).get("name", "?") for tc in tcs]
            tool_summaries.append(f"[called: {', '.join(names)}]")
        else:
            if tool_summaries:
                combined = "\n".join(tool_summaries)
                if len(combined) > budget_chars:
                    combined = combined[:budget_chars] + "\n..."
                compacted.append({"role": "assistant", "content": f"[Tool results]\n{combined}"})
                tool_summaries = []
            compacted.append(m)
    if tool_summaries:
        combined = "\n".join(tool_summaries)
        if len(combined) > budget_chars:
            combined = combined[:budget_chars] + "\n..."
        compacted.append({"role": "assistant", "content": f"[Tool results]\n{combined}"})
    return compacted


def llm_chat_with_tools(
    system: str,
    messages: List[Dict[str, Any]],
    base_path: str = ".",
    model: str = "",
    max_tokens: int = 512,
    max_tool_rounds: int = 5,
    gateway: Any = None,
) -> str:
    import ssl as _ssl
    import time as _time
    import urllib.request as _urllib

    from .openclaw_adapter import _load_dotenv

    _load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    resolved_model = model or os.environ.get("OPENCLAW_MODEL", "gpt-4o-mini")
    context_limit = _MODEL_CONTEXT_LIMITS.get(resolved_model, 128000)

    chat_messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
    chat_messages.extend(messages)

    _t0 = _time.time()
    used_tools = False
    context_maxed = False

    def _api_call(msgs: List[Dict[str, Any]], tc: str = "auto") -> Tuple[Optional[Dict[str, Any]], bool]:
        est = _estimate_tokens(msgs, tools=TOOLS if tc != "none" else None)
        if est + max_tokens + _SAFE_TOKEN_MARGIN > context_limit:
            return None, True
        payload_body: Dict[str, Any] = {
            "model": resolved_model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        if tc != "none":
            payload_body["tools"] = TOOLS
            payload_body["tool_choice"] = tc
        bdy = json.dumps(payload_body).encode("utf-8")
        rq = _urllib.Request(
            "https://api.openai.com/v1/chat/completions",
            data=bdy,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            sctx = _ssl.create_default_context()
            with _urllib.urlopen(rq, timeout=30, context=sctx) as rsp:
                resp_data = json.loads(rsp.read().decode("utf-8"))
            if resp_data.get("error"):
                err_msg = resp_data["error"].get("message", "")
                if "context" in err_msg.lower() or "token" in err_msg.lower():
                    return None, True
            return resp_data, False
        except Exception as exc:
            err_str = str(exc)
            if "context" in err_str.lower() or "token" in err_str.lower():
                return None, True
            # Fallback: if primary model fails, try gpt-4o-mini
            if resolved_model != "gpt-4o-mini":
                _log.debug("Model %s failed (%s), falling back to gpt-4o-mini", resolved_model, exc)
                fallback_payload = dict(payload_body, model="gpt-4o-mini")
                try:
                    bdy2 = json.dumps(fallback_payload).encode("utf-8")
                    rq2 = _urllib.Request(
                        "https://api.openai.com/v1/chat/completions",
                        data=bdy2,
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                        method="POST",
                    )
                    sctx2 = _ssl.create_default_context()
                    with _urllib.urlopen(rq2, timeout=30, context=sctx2) as rsp2:
                        return json.loads(rsp2.read().decode("utf-8")), False
                except Exception:
                    pass
            _log.debug("Tool LLM call failed: %s", exc)
            return None, False

    for _round in range(max_tool_rounds):
        elapsed = _time.time() - _t0
        if elapsed > 40:
            break

        tc = "required" if _round == 0 else "auto"
        data, maxed = _api_call(chat_messages, tc=tc)

        if maxed:
            context_maxed = True
            chat_messages = _compact_tool_messages(chat_messages)
            data, maxed = _api_call(chat_messages, tc="auto")
            if maxed or not data:
                break

        if not data:
            break

        choices = data.get("choices", [])
        if not choices:
            break
        choice = choices[0]
        message = choice.get("message", {})
        finish = choice.get("finish_reason", "")

        if finish == "length":
            content = message.get("content") or ""
            if str(content).strip():
                return str(content).strip()
            break

        if finish == "tool_calls" or message.get("tool_calls"):
            chat_messages.append(message)
            tool_calls = message.get("tool_calls", [])
            for tc_item in tool_calls:
                fn = tc_item.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}
                if os.environ.get("OPENCLAW_DEBUG"):
                    import sys as _sys
                    print(f"[tool] {tool_name}({tool_args})", file=_sys.stderr, flush=True)
                result = execute_tool(tool_name, tool_args, base_path=base_path, gateway=gateway)
                if len(result) > 1500:
                    result = result[:1500] + "\n... (truncated)"
                chat_messages.append({
                    "role": "tool",
                    "tool_call_id": tc_item.get("id", ""),
                    "content": result,
                })
                used_tools = True
            continue

        content = message.get("content") or ""
        if str(content).strip():
            return str(content).strip()

    if used_tools:
        if context_maxed:
            chat_messages = _compact_tool_messages(chat_messages)
        data, _ = _api_call(chat_messages, tc="none")
        if data:
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content") or ""
                if str(content).strip():
                    return str(content).strip()

    return ""
