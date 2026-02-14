from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


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

    @staticmethod
    def from_repo(repo_root: str) -> "OpenClawMicrocosm":
        root = Path(repo_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"OpenClaw repo root not found: {root}")

        soul_path = _find_soul_path(root)
        if soul_path is None:
            raise FileNotFoundError(f"No soul.md found under OpenClaw root: {root}")

        soul_text = soul_path.read_text(encoding="utf-8", errors="ignore").strip()
        if not soul_text:
            raise ValueError(f"OpenClaw soul file is empty: {soul_path}")

        return OpenClawMicrocosm(repo_root=root, soul_path=soul_path, soul_text=soul_text)

    def summary(self) -> Dict[str, str]:
        first_line = self.soul_text.splitlines()[0].strip() if self.soul_text else ""
        return {
            "agent": "openclaw",
            "repo_root": str(self.repo_root),
            "soul_path": str(self.soul_path),
            "soul_anchor": first_line,
        }

    def walktalk_envelope(self, utterance: str) -> Dict[str, str]:
        return {
            "agent": "openclaw",
            "mode": "walktalk",
            "soul_anchor": self.summary().get("soul_anchor", ""),
            "voice_utterance": utterance,
        }
