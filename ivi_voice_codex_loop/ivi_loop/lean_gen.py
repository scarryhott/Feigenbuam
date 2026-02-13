from __future__ import annotations

import re
from pathlib import Path
from typing import List

from .config import Settings, read_analysis_config
from .storage import load_state

RE_DEF = re.compile(r"^\s*def\s+([A-Za-z0-9_.']+)\s*:=\s*(.+)\s*$")
RE_RULE = re.compile(r"^\s*(.+?)\s*->\s*(.+?)\s*$")
RE_EQ = re.compile(r"^\s*([A-Za-z0-9_.']+)\s*=\s*(.+?)\s*$")


def _sanitize_ident(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_'.]", "_", s.strip())
    if not s:
        return "x"
    if s[0].isdigit():
        s = "x_" + s
    return s


def generate_lean_phase1(settings: Settings) -> Path:
    cfg = read_analysis_config(settings.analysis_config_path)
    ns = cfg["instructions"]["lean"].get("namespace", "IVI.Derived.Phase1")

    state = load_state(settings)
    claims = list(state.get("logic_claims", {}).values())
    accepted = [c for c in claims if c.get("status") == "accepted"]
    accepted.sort(key=lambda x: x.get("created_at", ""))

    lines: List[str] = [f"namespace {ns}", "", "-- AUTO-GENERATED. Edit upstream claims, then regenerate.", "",
                        "universe u", "", "-- Phase 1 derived artifacts", ""]

    emitted_defs = set()
    emit_axioms_ge = float(cfg["instructions"]["lean"].get("emit_axioms_only_if_confidence_ge", 0.7))

    for c in accepted:
        text = str(c.get("text", "")).strip()
        conf = float(c.get("confidence", 0.0))
        kind = c.get("kind", "hypothesis")
        lines.append(f"/- claim {c.get('id')} (kind={kind}, conf={conf}) -/")
        if m := RE_DEF.match(text):
            name = _sanitize_ident(m.group(1))
            rhs = m.group(2).strip()
            if name in emitted_defs:
                lines.append(f"-- skipped duplicate def {name}")
            else:
                emitted_defs.add(name)
                lines.append(f"constant {name} : Sort u")
                lines.append(f"-- intended: {name} := {rhs}")
        elif m := RE_RULE.match(text):
            lhs = m.group(1).strip()
            rhs = m.group(2).strip()
            thm_name = _sanitize_ident(f"rule_{c.get('id')}")
            lines.append(f"axiom {thm_name} : ({lhs}) → ({rhs})")
        elif m := RE_EQ.match(text):
            lhs = _sanitize_ident(m.group(1))
            rhs = m.group(2).strip()
            ax_name = _sanitize_ident(f"fact_{c.get('id')}")
            lines.append(f"axiom {ax_name} : {lhs} = ({rhs})")
        else:
            if conf >= emit_axioms_ge:
                ax_name = _sanitize_ident(f"hyp_{c.get('id')}")
                lines.append(f"axiom {ax_name} : True")
                lines.append(f"-- text: {text}")
            else:
                lines.append(f"-- quarantined/low-structure text: {text}")
        lines.append("")

    lines.append(f"end {ns}")
    out_path = settings.lean_out_dir / "Phase1_Derived.lean"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
