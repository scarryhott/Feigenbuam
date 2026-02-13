from __future__ import annotations

from typing import Any, Dict, List

from .config import Settings
from .storage import load_state, write_json


def _histogram(vals: List[float], bins: List[float]) -> Dict[str, int]:
    hist: Dict[str, int] = {}
    for i in range(len(bins) - 1):
        hist[f"{bins[i]}-{bins[i+1]}"] = 0
    for v in vals:
        placed = False
        for i in range(len(bins) - 1):
            if bins[i] <= v < bins[i + 1]:
                hist[f"{bins[i]}-{bins[i+1]}"] += 1
                placed = True
                break
        if not placed and v >= bins[-1]:
            hist[f"{bins[-2]}-{bins[-1]}"] += 1
    return hist


def analyze_state(settings: Settings) -> Dict[str, Any]:
    state = load_state(settings)
    claims = list(state.get("logic_claims", {}).values())
    equations = state.get("equations", {})
    derivations = state.get("derivations", {})
    triangles = state.get("triangles", {})

    accepted = [c for c in claims if c.get("status") == "accepted"]
    quarantined = [c for c in claims if c.get("status") == "quarantined"]

    confs = [float(c.get("confidence", 0.0)) for c in claims]
    a_confs = [float(c.get("confidence", 0.0)) for c in accepted]
    q_confs = [float(c.get("confidence", 0.0)) for c in quarantined]

    def_map: Dict[str, str] = {}
    eq_map: Dict[str, str] = {}
    conflicts: List[Dict[str, Any]] = []

    for c in accepted:
        text = str(c.get("text", "")).strip()
        if text.startswith("def "):
            parts = text.split(":=", 1)
            if len(parts) == 2:
                name = parts[0].replace("def", "", 1).strip()
                rhs = parts[1].strip()
                if name in def_map and def_map[name] != rhs:
                    conflicts.append({"type": "def_conflict", "name": name, "a": def_map[name], "b": rhs, "claim": c.get("id")})
                def_map[name] = rhs
        if " = " in text and "->" not in text and not text.startswith("def "):
            lhs, rhs = text.split("=", 1)
            lhs = lhs.strip()
            rhs = rhs.strip()
            if lhs in eq_map and eq_map[lhs] != rhs:
                conflicts.append({"type": "eq_conflict", "lhs": lhs, "a": eq_map[lhs], "b": rhs, "claim": c.get("id")})
            eq_map[lhs] = rhs

    eq_ids = set(equations.keys())
    der_ids = set(derivations.keys())
    broken_triangles = 0
    for tri in triangles.values():
        if tri.get("equation_id") not in eq_ids or tri.get("derivation_id") not in der_ids:
            broken_triangles += 1

    report = {
        "counts": {
            "claims_total": len(claims),
            "accepted": len(accepted),
            "quarantined": len(quarantined),
            "conflicts": len(conflicts),
            "equations": len(equations),
            "derivations": len(derivations),
            "triangles": len(triangles),
            "broken_triangles": broken_triangles,
        },
        "confidence": {
            "hist_total": _histogram(confs, bins=[0.0, 0.25, 0.5, 0.7, 0.85, 1.01]),
            "hist_accepted": _histogram(a_confs, bins=[0.0, 0.25, 0.5, 0.7, 0.85, 1.01]),
            "hist_quarantined": _histogram(q_confs, bins=[0.0, 0.25, 0.5, 0.7, 0.85, 1.01]),
            "avg_total": sum(confs) / max(1, len(confs)),
            "avg_accepted": sum(a_confs) / max(1, len(a_confs)),
            "avg_quarantined": sum(q_confs) / max(1, len(q_confs)),
        },
        "conflicts": conflicts,
        "notes": [
            "No Lean compilation performed (by design).",
            "Conflicts are heuristic: duplicate defs/equalities with different RHS.",
            "Triangle integrity checks ensure derivation/equation links remain connected.",
        ],
    }

    out_path = settings.reports_dir / "analysis_phase1_report.json"
    write_json(out_path, report)
    return report
