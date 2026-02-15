from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


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


@dataclass(frozen=True)
class OpenClawMicrocosm:
    repo_root: Path
    soul_path: Path
    soul_text: str
    voice_profile: Dict[str, Any]
    memory_profile: Dict[str, Any]

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

        return OpenClawMicrocosm(
            repo_root=root,
            soul_path=soul_path,
            soul_text=soul_text,
            voice_profile=merged_profile,
            memory_profile=memory_profile,
        )

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
