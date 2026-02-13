from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class Hit:
    path: str
    line_no: int
    line: str
    before: List[str]
    after: List[str]


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".ivi",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}


def _has_ripgrep() -> bool:
    try:
        subprocess.run(["rg", "--version"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False


def _should_skip_path(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except Exception:
        rel_parts = path.parts

    for part in rel_parts:
        if part in DEFAULT_EXCLUDE_DIRS:
            return True
    return False


def _read_context_lines(path: Path, line_no_1based: int, context: int) -> Tuple[List[str], List[str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ([], [])

    idx = max(0, line_no_1based - 1)
    start = max(0, idx - context)
    end = min(len(lines), idx + context + 1)
    before = lines[start:idx]
    after = lines[idx + 1 : end]
    return (before, after)


def ripgrep_search(
    root: Path,
    query: str,
    max_hits: int = 50,
    context: int = 2,
    glob: Optional[str] = None,
) -> List[Hit]:
    if not _has_ripgrep():
        raise RuntimeError("ripgrep (rg) not found in PATH. Install ripgrep or switch to Python-only search.")

    cmd = ["rg", "--line-number", "--no-heading", "--fixed-strings"]
    if glob:
        cmd += ["--glob", glob]
    cmd += [query, str(root)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"rg failed: {proc.stderr.strip() or proc.stdout.strip()}")

    hits: List[Hit] = []
    for line in proc.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        p_str, ln_str, content = parts[0], parts[1], parts[2]
        try:
            ln = int(ln_str)
        except ValueError:
            continue

        p = Path(p_str)
        if _should_skip_path(p, root):
            continue

        before, after = _read_context_lines(p, ln, context=context)
        hits.append(Hit(path=p_str, line_no=ln, line=content.rstrip("\n"), before=before, after=after))
        if len(hits) >= max_hits:
            break
    return hits


def _rank_hits(hits: List[Hit], query: str) -> List[Hit]:
    q = query
    q_re = re.compile(rf"(?i)\b{re.escape(q)}\b")
    scored: List[Tuple[int, Hit]] = []
    for h in hits:
        score = 0
        if q_re.search(h.line):
            score += 3
        if q.lower() in h.line.lower():
            score += 1
        score -= min(5, h.path.count("/"))
        scored.append((score, h))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [h for _, h in scored]


def summarize_hits(query: str, hits: List[Hit], max_files: int = 6) -> Dict[str, object]:
    ranked = _rank_hits(hits, query)

    by_file: Dict[str, List[Hit]] = {}
    for h in ranked:
        by_file.setdefault(h.path, []).append(h)

    files_sorted = sorted(by_file.items(), key=lambda kv: len(kv[1]), reverse=True)
    files_sorted = files_sorted[:max_files]

    file_summaries: List[Dict[str, object]] = []
    for path, fhits in files_sorted:
        fhits = _rank_hits(fhits, query)[:3]
        bullets: List[str] = []
        for h in fhits:
            ctx = []
            if h.before:
                ctx.append("… " + h.before[-1].strip())
            ctx.append("> " + h.line.strip())
            if h.after:
                ctx.append("… " + h.after[0].strip())
            bullets.append(f"L{h.line_no}: " + " | ".join(ctx))
        file_summaries.append(
            {
                "path": path,
                "hit_count": len(by_file[path]),
                "highlights": bullets,
            }
        )

    return {
        "query": query,
        "total_hits": len(hits),
        "files_considered": len(by_file),
        "top_files": file_summaries,
    }


def ask_repo(root: Path, query: str, max_hits: int = 50, context: int = 2, glob: Optional[str] = None) -> str:
    hits = ripgrep_search(root=root, query=query, max_hits=max_hits, context=context, glob=glob)
    if not hits:
        return f'No matches for "{query}".'

    summary = summarize_hits(query=query, hits=hits, max_files=6)

    lines: List[str] = []
    lines.append(f'QUERY: "{summary["query"]}"')
    lines.append(f"- total_hits: {summary['total_hits']}")
    lines.append(f"- files_with_hits: {summary['files_considered']}")
    lines.append("")
    lines.append("TOP FILES")
    for item in summary["top_files"]:  # type: ignore[index]
        lines.append(f"- {item['path']}  (hits: {item['hit_count']})")
        for b in item["highlights"]:
            lines.append(f"  - {b}")
        lines.append("")
    return "\n".join(lines).rstrip()
