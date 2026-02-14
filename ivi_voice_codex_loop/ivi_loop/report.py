from __future__ import annotations

from .config import Settings
from .config import read_analysis_config
from .storage import load_state, read_json


def format_status(settings: Settings) -> str:
    state = load_state(settings)
    counts = state.get("counts", {})
    cfg = read_analysis_config(settings.analysis_config_path)
    derive_mode = str(cfg.get("instructions", {}).get("derive", {}).get("mode", "")).lower()
    active_memory_mode = "strict_derived_only" if derive_mode == "strict" else "permissive_mixed"

    quarantine = read_json(settings.quarantine_path, default={"claims": {}})
    qn_archive = len(quarantine.get("claims", {}))
    qn_state = int(counts.get("quarantined_claims", 0))

    lines = ["IVI LOOP STATUS"]
    lines.append(f"- active_memory_mode: {active_memory_mode}")
    lines.append(f"- events_total: {counts.get('events_total', 0)}")
    lines.append(f"- utterances:   {counts.get('utterances', 0)}")
    lines.append(f"- claims_active:{counts.get('logic_claims', 0)}")
    lines.append(f"- claims_quarantine_state: {qn_state}")
    lines.append(f"- notes:        {counts.get('analysis_notes', 0)}")
    lines.append(f"- equations:    {counts.get('equations', 0)}")
    lines.append(f"- derivations:  {counts.get('derivations', 0)}")
    lines.append(f"- triangles:    {counts.get('triangles', 0)}")
    lines.append(f"- quarantined_archive:  {qn_archive}")
    return "\n".join(lines)
