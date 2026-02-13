from __future__ import annotations

from .config import Settings
from .storage import load_state, read_json


def format_status(settings: Settings) -> str:
    state = load_state(settings)
    counts = state.get("counts", {})
    quarantine = read_json(settings.quarantine_path, default={"claims": {}})
    qn = len(quarantine.get("claims", {}))

    lines = ["IVI LOOP STATUS"]
    lines.append(f"- events_total: {counts.get('events_total', 0)}")
    lines.append(f"- utterances:   {counts.get('utterances', 0)}")
    lines.append(f"- claims:       {counts.get('logic_claims', 0)}")
    lines.append(f"- notes:        {counts.get('analysis_notes', 0)}")
    lines.append(f"- quarantined:  {qn}")
    return "\n".join(lines)
