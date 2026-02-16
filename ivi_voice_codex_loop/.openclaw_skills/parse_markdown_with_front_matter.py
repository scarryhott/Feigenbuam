"""
Skill: parse_markdown_with_front_matter
Parses a markdown file with front matter and extracts metadata and body content.
"""

import re
from pathlib import Path
from typing import Dict, Optional

def parse_markdown_with_front_matter(skill_path: Path) -> Optional[Dict[str, str]]:
    """Parses a markdown file with front matter and extracts metadata and body content."""
    try:
        raw = skill_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", raw, re.DOTALL)
    if not fm_match:
        return None
    fm_text = fm_match.group(1)
    body = fm_match.group(2).strip()
    metadata: Dict[str, str] = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if ':' in line:
            key, value = line.split(':', 1)
            metadata[key.strip()] = value.strip()
    return {'metadata': metadata, 'body': body}