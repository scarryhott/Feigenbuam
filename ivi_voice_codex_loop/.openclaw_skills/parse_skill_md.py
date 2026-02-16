"""
Skill: parse_skill_md
Parses a .md file to extract metadata and body, returning an OpenClawSkill object if successful.
"""

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
            name = line.split("name:", 1)[1].strip()
        elif line.startswith("description:"):
            description = line.split("description:", 1)[1].strip()
        else:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip()
    return OpenClawSkill(name=name, description=description, path=skill_path, instructions=body, metadata=metadata)