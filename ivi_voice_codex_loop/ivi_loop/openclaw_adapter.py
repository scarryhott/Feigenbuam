from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_log = logging.getLogger(__name__)


_OLLAMA_BASE_URL = "http://localhost:11434"
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
_ENV_LOADED = False


def _load_dotenv() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    for candidate in [
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
    ]:
        if candidate.is_file():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if key and val and key not in os.environ:
                        os.environ[key] = val
            except OSError:
                pass
            break


def _llm_chat_openai(
    system: str,
    messages: List[Dict[str, str]],
    model: str = "",
    max_tokens: int = 512,
) -> str:
    import ssl
    import urllib.request

    _load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    resolved_model = model or os.environ.get("OPENCLAW_MODEL", _OPENAI_DEFAULT_MODEL)
    chat_messages = [{"role": "system", "content": system}]
    chat_messages.extend(messages)
    body = json.dumps({
        "model": resolved_model,
        "messages": chat_messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices", [])
        if choices:
            return str(choices[0].get("message", {}).get("content", "")).strip()
    except Exception as exc:
        _log.debug("OpenAI LLM call failed: %s", exc)
    return ""


def _llm_chat_ollama(
    system: str,
    messages: List[Dict[str, str]],
    model: str = "",
    max_tokens: int = 512,
) -> str:
    import urllib.request

    resolved_model = model or os.environ.get("OLLAMA_MODEL", "deepseek-coder:6.7b")
    base_url = os.environ.get("OLLAMA_HOST", _OLLAMA_BASE_URL)
    chat_messages = [{"role": "system", "content": system}]
    chat_messages.extend(messages)
    body = json.dumps({
        "model": resolved_model,
        "messages": chat_messages,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.7},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = str(data.get("message", {}).get("content", "")).strip()
        if "<think>" in content:
            parts = content.split("</think>")
            content = parts[-1].strip() if len(parts) > 1 else content
        return content
    except Exception as exc:
        _log.debug("Ollama LLM call failed: %s", exc)
    return ""


def _llm_chat(
    system: str,
    messages: List[Dict[str, str]],
    model: str = "",
    max_tokens: int = 512,
) -> str:
    _load_dotenv()
    reply = _llm_chat_openai(system, messages, model=model, max_tokens=max_tokens)
    if reply:
        return reply
    if not os.environ.get("OPENAI_API_KEY", ""):
        reply = _llm_chat_ollama(system, messages, model=model, max_tokens=max_tokens)
        if reply:
            return reply
    return ""


_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}

_MEMORY_SUFFIXES = {".md", ".txt", ".jsonl"}
_IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _soul_anchor_line(soul_text: str) -> str:
    for raw in soul_text.splitlines():
        line = str(raw).strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        if line:
            return line
    return ""


def _soul_keywords(soul_text: str, limit: int = 6) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9_\-]+", soul_text.lower())
    ranked: List[str] = []
    seen = set()
    for w in words:
        token = w.strip("_-")
        if len(token) < 3 or token in _STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        ranked.append(token)
        if len(ranked) >= max(1, int(limit)):
            break
    return ranked


def _voice_style_hint(soul_text: str) -> str:
    t = soul_text.lower()
    if any(k in t for k in ["strict", "precise", "formal", "rigor"]):
        return "precise"
    if any(k in t for k in ["calm", "gentle", "compassion", "soft"]):
        return "calm"
    if any(k in t for k in ["bold", "direct", "aggressive", "fast"]):
        return "direct"
    return "balanced"


def _soul_voice_profile(soul_text: str) -> Dict[str, Any]:
    canonical = "\n".join([x.strip() for x in soul_text.splitlines() if x.strip()])
    return {
        "anchor": _soul_anchor_line(soul_text),
        "style_hint": _voice_style_hint(soul_text),
        "keywords": _soul_keywords(soul_text, limit=6),
        "soul_digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _is_ignored_path(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return any(part in parts for part in _IGNORED_DIRS)


def _iter_memory_files(path: Path) -> List[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path] if path.suffix.lower() in _MEMORY_SUFFIXES else []

    items: List[Path] = []
    for p in sorted(path.rglob("*")):
        if _is_ignored_path(p):
            continue
        if not p.is_file():
            continue
        if p.suffix.lower() not in _MEMORY_SUFFIXES:
            continue
        items.append(p)
    return items


def _collect_memory_documents(
    repo_root: Path,
    soul_path: Path,
    extra_memory_paths: Optional[Sequence[str]] = None,
    max_files: int = 48,
    max_chars_per_file: int = 4000,
) -> List[Tuple[Path, str]]:
    seeds: List[Path] = [repo_root]
    for p in extra_memory_paths or []:
        if not p:
            continue
        try:
            seeds.append(Path(p).expanduser().resolve())
        except OSError:
            continue

    discovered: List[Path] = []
    seen = set()
    for seed in seeds:
        for candidate in _iter_memory_files(seed):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            discovered.append(candidate)

    docs: List[Tuple[Path, str]] = []
    for path in sorted(discovered, key=lambda x: str(x)):
        if len(docs) >= max(1, int(max_files)):
            break
        if path == soul_path:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        normalized = text.strip()
        if not normalized:
            continue
        docs.append((path, normalized[: max(1, int(max_chars_per_file))]))
    return docs


def _memory_voice_profile(memory_docs: List[Tuple[Path, str]]) -> Dict[str, Any]:
    if not memory_docs:
        return {
            "enabled": False,
            "anchor": "",
            "style_hint": "balanced",
            "keywords": [],
            "memory_digest": "",
            "sources": [],
            "source_count": 0,
        }

    joined = "\n\n".join([f"{path}\n{text}" for path, text in memory_docs])
    canonical = "\n".join([x.strip() for x in joined.splitlines() if x.strip()])
    source_paths = [str(path) for path, _ in memory_docs]
    first_text = memory_docs[0][1]
    return {
        "enabled": True,
        "anchor": _soul_anchor_line(first_text),
        "style_hint": _voice_style_hint(joined),
        "keywords": _soul_keywords(joined, limit=10),
        "memory_digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "sources": source_paths,
        "source_count": len(source_paths),
    }


def _merge_voice_profiles(soul_profile: Dict[str, Any], memory_profile: Dict[str, Any]) -> Dict[str, Any]:
    soul_anchor = str(soul_profile.get("anchor", "")).strip()
    memory_anchor = str(memory_profile.get("anchor", "")).strip()
    soul_style = str(soul_profile.get("style_hint", "balanced")).strip() or "balanced"
    memory_style = str(memory_profile.get("style_hint", "balanced")).strip() or "balanced"
    combined_style = soul_style if soul_style != "balanced" else memory_style

    merged_keywords: List[str] = []
    seen = set()
    for seq in [soul_profile.get("keywords", []), memory_profile.get("keywords", [])]:
        for token in seq if isinstance(seq, list) else []:
            word = str(token).strip()
            if not word or word in seen:
                continue
            seen.add(word)
            merged_keywords.append(word)
            if len(merged_keywords) >= 12:
                break
        if len(merged_keywords) >= 12:
            break

    soul_digest = str(soul_profile.get("soul_digest", "")).strip()
    memory_digest = str(memory_profile.get("memory_digest", "")).strip()
    profile_basis = f"{soul_digest}|{memory_digest}|{combined_style}|{','.join(merged_keywords)}"
    return {
        "anchor": soul_anchor or memory_anchor,
        "style_hint": combined_style,
        "keywords": merged_keywords,
        "soul_digest": soul_digest,
        "memory_digest": memory_digest,
        "profile_digest": hashlib.sha256(profile_basis.encode("utf-8")).hexdigest(),
        "memory_sources": list(memory_profile.get("sources", [])) if isinstance(memory_profile.get("sources", []), list) else [],
        "memory_source_count": int(memory_profile.get("source_count", 0)),
    }


def _find_soul_path(repo_root: Path) -> Optional[Path]:
    candidates = [
        repo_root / "soul.md",
        repo_root / "SOUL.md",
        repo_root / "docs" / "soul.md",
        repo_root / "docs" / "SOUL.md",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def _gather_environment_context() -> Dict[str, Any]:
    home = str(Path.home())
    cwd = os.getcwd()
    now = datetime.datetime.now()
    top_level_files: List[str] = []
    try:
        for item in sorted(Path(cwd).iterdir()):
            if item.name.startswith("."):
                continue
            label = f"{item.name}/" if item.is_dir() else item.name
            top_level_files.append(label)
            if len(top_level_files) >= 40:
                break
    except OSError:
        pass
    home_dirs: List[str] = []
    try:
        for item in sorted(Path(home).iterdir()):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                home_dirs.append(item.name)
            if len(home_dirs) >= 20:
                break
    except OSError:
        pass
    return {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "machine": platform.machine(),
        "hostname": platform.node(),
        "user": os.environ.get("USER", os.environ.get("USERNAME", "")),
        "home": home,
        "cwd": cwd,
        "shell": os.environ.get("SHELL", ""),
        "timestamp": now.isoformat(),
        "timezone": str(now.astimezone().tzinfo),
        "cwd_files": top_level_files,
        "home_dirs": home_dirs,
    }


@dataclass
class OpenClawMicrocosm:
    repo_root: Path
    soul_path: Path
    soul_text: str
    voice_profile: Dict[str, Any]
    memory_profile: Dict[str, Any]
    environment: Dict[str, Any] = field(default_factory=dict)
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    known_projects: List[Dict[str, str]] = field(default_factory=list)
    openclaw_skills: List[Any] = field(default_factory=list)
    goal_engine: Any = None

    @staticmethod
    def from_repo(
        repo_root: str,
        extra_memory_paths: Optional[Sequence[str]] = None,
        max_memory_files: int = 48,
    ) -> "OpenClawMicrocosm":
        root = Path(repo_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"OpenClaw repo root not found: {root}")

        soul_path = _find_soul_path(root)
        if soul_path is None:
            raise FileNotFoundError(f"No soul.md found under OpenClaw root: {root}")

        soul_text = soul_path.read_text(encoding="utf-8", errors="ignore").strip()
        if not soul_text:
            raise ValueError(f"OpenClaw soul file is empty: {soul_path}")

        soul_profile = _soul_voice_profile(soul_text)
        memory_docs = _collect_memory_documents(
            root,
            soul_path,
            extra_memory_paths=extra_memory_paths,
            max_files=max_memory_files,
        )
        memory_profile = _memory_voice_profile(memory_docs)
        merged_profile = _merge_voice_profiles(soul_profile, memory_profile)
        env = _gather_environment_context()

        microcosm = OpenClawMicrocosm(
            repo_root=root,
            soul_path=soul_path,
            soul_text=soul_text,
            voice_profile=merged_profile,
            memory_profile=memory_profile,
            environment=env,
            conversation_history=[],
            known_projects=[],
            openclaw_skills=[],
        )
        microcosm.known_projects = microcosm._scan_known_projects()
        from .openclaw_actions import discover_skills
        microcosm.openclaw_skills = discover_skills(workspace=str(root))
        return microcosm

    def refresh_environment(self) -> Dict[str, Any]:
        self.environment = _gather_environment_context()
        return self.environment

    def record_turn(self, role: str, text: str) -> None:
        self.conversation_history.append({"role": role, "text": text})
        if len(self.conversation_history) > 100:
            self.conversation_history = self.conversation_history[-100:]

    def _scan_known_projects(self) -> List[Dict[str, str]]:
        env = self.environment or {}
        home = env.get("home", str(Path.home()))
        projects: List[Dict[str, str]] = []
        scan_roots = [
            Path(home) / "Downloads",
            Path(home) / "Purple",
        ]
        for root in scan_roots:
            if not root.is_dir():
                continue
            try:
                for item in sorted(root.iterdir()):
                    if item.name.startswith(".") or not item.is_dir():
                        continue
                    contents: List[str] = []
                    try:
                        for f in list(item.iterdir())[:10]:
                            if f.name.startswith("."):
                                continue
                            label = f"{f.name}/" if f.is_dir() else f.name
                            contents.append(label)
                    except OSError:
                        pass
                    if contents:
                        projects.append({
                            "name": item.name,
                            "path": str(item),
                            "files": ", ".join(contents[:6]),
                        })
                    if len(projects) >= 40:
                        break
            except OSError:
                pass
        return projects

    def context_block(self) -> str:
        env = self.environment or {}
        known_projects = self.known_projects or []
        parts = [
            "You are OpenClaw, an autonomous agent integrated with the Purple self-improvement loop.",
            "",
            "AUTONOMY: You self-improve through the Purple loop. Read config, analyze, modify, test, log. Do not wait for permission. Only ask the user at genuine impasses you cannot resolve with tools. Write discoveries back as skills or config changes.",
            "",
            "ACCURACY: After list_dir, ALWAYS call read_file on the actual .py/.md/.txt files before responding. NEVER describe a file you haven't read. Cite exact function names, classes, and logic. Use FULL ABSOLUTE PATHS.",
            "",
            "BREVITY: 1-3 sentences about what you found in the code. No markdown. No headers. No filler.",
            "",
            "GOALS: When the user asks what to work on or what's next, recommend from the SELF-IMPROVEMENT QUEUE below. These are Purple-derived priorities based on the IVI grid analysis, not generic suggestions.",
            "",
            f"Soul: {self.soul_text[:200]}",
            f"Env: {env.get('user', '?')}@{env.get('hostname', '?')} {env.get('platform', '?')} cwd={env.get('cwd', '?')}",
        ]

        # --- Layer-aware context: replace flat accumulation with scoped layers ---
        _gw = None
        _lc = getattr(self, "_loop_controller", None)
        if _lc is not None:
            _gw = getattr(_lc, "_ivi_gateway", None)

        if _gw is not None and hasattr(_gw, "navigation"):
            nav = _gw.navigation
            layer_ctx = nav.layer_context_for_prompt()
            if layer_ctx:
                parts.append("")
                parts.append("NAVIGATION CONTEXT (layer-specific scope):")
                parts.append(layer_ctx)
            # Current layer determines how much project info to include
            cur = nav.current_layer
            if cur and cur.kind == "ivi_core":
                # In IVI core: full project detail, fewer external projects
                if known_projects:
                    proj_lines = [f"{p['name']}={p.get('path','')}" for p in known_projects[:5]]
                    parts.append(f"Projects: {'; '.join(proj_lines)}")
            elif cur and cur.kind == "os_scope":
                # At OS level: list more projects, less per-project detail
                if known_projects:
                    proj_lines = [p['name'] for p in known_projects[:15]]
                    parts.append(f"Visible projects: {', '.join(proj_lines)}")
            else:
                # Default: moderate project info
                if known_projects:
                    proj_lines = [f"{p['name']}={p.get('path','')}" for p in known_projects[:10]]
                    parts.append(f"Projects: {'; '.join(proj_lines)}")
            # Invariants as instructions
            invariants = nav.active_invariants
            if invariants:
                parts.append(f"Active invariants: {'; '.join(invariants[:6])}")
            allowed = nav.active_allowed_ops
            if allowed:
                parts.append(f"Allowed ops in current scope: {', '.join(allowed)}")
        else:
            # Fallback: flat project listing (no gateway)
            if known_projects:
                proj_lines = [f"{p['name']}={p.get('path','')}" for p in known_projects[:10]]
                parts.append(f"Projects: {'; '.join(proj_lines)}")

        if self.goal_engine is not None:
            goal_text = self.goal_engine.format_goals_for_prompt()
            if goal_text:
                parts.append("")
                parts.append(goal_text)
        # Inject Purple-derived skills as structural constraints (not training)
        skills_loop = getattr(self, "_skills_loop", None)
        if skills_loop is not None:
            skills_ctx = skills_loop.get_context_for_ai()
            if skills_ctx:
                parts.append("")
                parts.append(skills_ctx)
        if self.conversation_history:
            for turn in self.conversation_history[-3:]:
                role = turn.get("role", "?")
                text = turn.get("text", "")[:100]
                parts.append(f"[{role}] {text}")
        return "\n".join(parts)

    def summary(self) -> Dict[str, Any]:
        first_line = self.voice_profile.get("anchor", "") if isinstance(self.voice_profile, dict) else ""
        return {
            "agent": "openclaw",
            "repo_root": str(self.repo_root),
            "soul_path": str(self.soul_path),
            "soul_anchor": first_line,
            "voice_profile": dict(self.voice_profile),
            "memory_profile": dict(self.memory_profile),
        }

    def personalize_voice_utterance(self, utterance: str, utterance_kind: str = "statement") -> Dict[str, Any]:
        text = str(utterance).strip()
        kind = str(utterance_kind).strip().lower() or "statement"
        profile = dict(self.voice_profile) if isinstance(self.voice_profile, dict) else {}
        anchor = str(profile.get("anchor", "")).strip()
        style_hint = str(profile.get("style_hint", "balanced")).strip()
        keywords = [str(x).strip() for x in profile.get("keywords", []) if str(x).strip()]
        keyword_str = ",".join(keywords)
        conditioned = (
            f"{text}\n\n"
            f"[openclaw.voice_persona anchor=\"{anchor}\" style=\"{style_hint}\""
            f" keywords=\"{keyword_str}\" utterance_kind=\"{kind}\"]"
        )
        digest_basis = f"{anchor}|{style_hint}|{keyword_str}|{kind}|{text}"
        return {
            "agent": "openclaw",
            "enabled": True,
            "utterance_kind": kind,
            "voice_profile": profile,
            "memory_profile": dict(self.memory_profile),
            "original_utterance": text,
            "conditioned_utterance": conditioned,
            "personalization_digest": hashlib.sha256(digest_basis.encode("utf-8")).hexdigest(),
        }

    def walktalk_envelope(self, utterance: str, utterance_kind: str = "statement") -> Dict[str, Any]:
        return {
            "agent": "openclaw",
            "mode": "walktalk",
            "soul_anchor": self.summary().get("soul_anchor", ""),
            "utterance_kind": str(utterance_kind).strip().lower() or "statement",
            "profile_digest": str(self.voice_profile.get("profile_digest", "")),
            "memory_source_count": int(self.voice_profile.get("memory_source_count", 0)),
            "voice_utterance": utterance,
        }

    def _resolve_project_refs(self, text: str) -> str:
        """Find project names in text and append their absolute paths.
        Also resolves parent directory names and recently-discussed projects."""
        lower = text.lower()
        resolved_parts = []
        seen_paths = set()

        for proj in (self.known_projects or []):
            name = proj.get("name", "")
            path = proj.get("path", "")
            if not name:
                continue
            # Match exact project name
            if name.lower() in lower and path not in seen_paths:
                resolved_parts.append(f"{name} is at {path}")
                seen_paths.add(path)
                continue
            # Match parent directory name (e.g., "purple" matches ~/Purple/*)
            parent = str(Path(path).parent.name).lower() if path else ""
            if parent and parent in lower and parent != "downloads" and path not in seen_paths:
                resolved_parts.append(f"{name} is at {path} (under {parent})")
                seen_paths.add(path)

        # Also resolve projects mentioned in recent conversation but not in current utterance
        if self.conversation_history:
            recent_user = [t["text"] for t in self.conversation_history[-4:] if t.get("role") == "user"]
            for prev in recent_user:
                prev_lower = prev.lower()
                for proj in (self.known_projects or []):
                    name = proj.get("name", "")
                    path = proj.get("path", "")
                    if name and name.lower() in prev_lower and path not in seen_paths:
                        resolved_parts.append(f"{name} is at {path} (mentioned earlier)")
                        seen_paths.add(path)

        if resolved_parts:
            return text + "\n[" + "; ".join(resolved_parts) + "]"
        return text

    def _try_native_response(self, utterance: str) -> Optional[str]:
        """Try to answer using Purple native intelligence (no LLM).
        Returns a response string if native can handle it, None otherwise."""
        lower = utterance.lower()
        # Native can handle: code structure questions, complexity, function listings
        code_triggers = [
            "tell me about", "describe", "what functions", "what classes",
            "analyze", "complexity", "how many functions", "structure of",
            "what's in", "what is in", "list functions", "list classes",
        ]
        if not any(t in lower for t in code_triggers):
            return None

        try:
            from .purple_native_intelligence import NativeCodeAnalyzer
            analyzer = NativeCodeAnalyzer()
        except ImportError:
            return None

        # Find which file the user is asking about
        target = None
        for proj in (self.known_projects or []):
            name = proj.get("name", "")
            path = proj.get("path", "")
            if name and name.lower() in lower and path:
                # Scan for .py files in the project
                from pathlib import Path as _P
                py_files = list(_P(path).glob("*.py"))
                if py_files:
                    all_insights = []
                    for pf in py_files[:5]:
                        all_insights.extend(analyzer.analyze_file(str(pf)))
                    if all_insights:
                        fns = [i for i in all_insights if i.kind == "function"]
                        cls = [i for i in all_insights if i.kind == "class"]
                        cc = [i for i in all_insights if i.kind == "complexity"]
                        parts = [f"{name}: {len(fns)} functions, {len(cls)} classes across {len(py_files)} files."]
                        if cc:
                            top = sorted(cc, key=lambda x: x.metadata.get("cyclomatic_complexity", 0), reverse=True)[:3]
                            parts.append("High complexity: " + ", ".join(
                                f"{c.name}(cc={c.metadata.get('cyclomatic_complexity', 0)})" for c in top
                            ) + ".")
                        if fns:
                            parts.append("Key functions: " + ", ".join(f.name for f in fns[:8]) + ".")
                        return " ".join(parts)
                break

        # Check if asking about a specific ivi_loop file
        ivi_files = [
            "openclaw_adapter", "openclaw_actions", "loop", "derive",
            "analyze", "cli", "config", "ivi_simplicial_grid", "storage", "ir",
        ]
        for fname in ivi_files:
            if fname.replace("_", " ") in lower or fname in lower:
                fpath = str(Path(self.repo_root) / "ivi_loop" / f"{fname}.py")
                if Path(fpath).is_file():
                    insights = analyzer.analyze_file(fpath)
                    if insights:
                        fns = [i for i in insights if i.kind == "function"]
                        cls = [i for i in insights if i.kind == "class"]
                        cc = [i for i in insights if i.kind == "complexity"]
                        parts = [f"{fname}.py: {len(fns)} functions, {len(cls)} classes."]
                        if cc:
                            top = sorted(cc, key=lambda x: x.metadata.get("cyclomatic_complexity", 0), reverse=True)[:3]
                            parts.append("High complexity: " + ", ".join(
                                f"{c.name}(cc={c.metadata.get('cyclomatic_complexity', 0)})" for c in top
                            ) + ".")
                        if fns:
                            parts.append("Key functions: " + ", ".join(f.name for f in fns[:8]) + ".")
                        return " ".join(parts)
                break

        return None

    def contextual_response(self, utterance: str) -> str:
        import time as _time

        _t0 = _time.time()

        # --- Try Purple native intelligence first (no LLM cost) ---
        native_reply = self._try_native_response(utterance)
        if native_reply:
            elapsed = _time.time() - _t0
            try:
                from .purple_goal_engine import _write_monitor
                _write_monitor({
                    "ts": _time.time(),
                    "type": "user_response",
                    "model": "native",
                    "utterance": utterance[:100],
                    "reply_len": len(native_reply),
                    "reply_preview": native_reply[:200],
                    "elapsed_s": round(elapsed, 2),
                    "engine": "native",
                })
            except Exception:
                pass
            # --- Close the skills loop for native responses too ---
            self._feedback_to_skills_loop(native_reply)
            return native_reply

        # --- Fall back to LLM ---
        from .openclaw_actions import llm_chat_with_tools

        system_prompt = self.context_block()
        resolved_utterance = self._resolve_project_refs(utterance)
        messages: List[Dict[str, Any]] = []
        for turn in self.conversation_history[-6:]:
            role = "user" if turn.get("role") == "user" else "assistant"
            messages.append({"role": role, "content": turn.get("text", "")[:200]})
        if not messages or messages[-1].get("content") != resolved_utterance:
            messages.append({"role": "user", "content": resolved_utterance})
        _load_dotenv()
        model = os.environ.get("OPENCLAW_MODEL", "gpt-4o-mini")
        # Pass gateway for intent/attest co-signing of tool calls
        _gw = None
        _lc = getattr(self, "_loop_controller", None)
        if _lc is not None:
            _gw = getattr(_lc, "_ivi_gateway", None)
        reply = llm_chat_with_tools(
            system=system_prompt,
            messages=messages,
            base_path=str(self.repo_root),
            max_tokens=384,
            gateway=_gw,
        )
        if not reply:
            reply = _llm_chat(system=system_prompt, messages=messages)
        if not reply:
            reply = "[LLM unavailable \u2014 check .env for OPENAI_API_KEY or start ollama]"

        elapsed = _time.time() - _t0
        try:
            from .purple_goal_engine import _write_monitor
            _write_monitor({
                "ts": _time.time(),
                "type": "user_response",
                "model": model,
                "utterance": utterance[:100],
                "reply_len": len(reply),
                "reply_preview": reply[:200],
                "elapsed_s": round(elapsed, 2),
                "engine": "llm",
            })
        except Exception:
            pass

        # --- Close the skills loop: feed AI output back ---
        self._feedback_to_skills_loop(reply)

        return reply

    def _feedback_to_skills_loop(self, ai_reply: str) -> None:
        """Feed AI output back through the skills loop to close the cycle:
        skills → AI context → AI output → record activation + new claims → grid → new skills.
        This is the behavioral observation that lets skills self-select."""
        skills_loop = getattr(self, "_skills_loop", None)
        if skills_loop is None:
            return
        try:
            # 1. Record which skills were active when the AI produced this output
            skills_loop.record_activation_from_output(ai_reply)

            # 2. Feed AI output as claims back into the grid
            grid = getattr(self, "_loop_controller", None)
            if grid is not None:
                skills_loop.observe_ai_output(ai_reply, grid)
        except Exception:
            pass
