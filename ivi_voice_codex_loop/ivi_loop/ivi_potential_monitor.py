"""
ivi_potential_monitor.py

Continuous monitor that watches the system as it builds potential AI
to replace possibility AI functions.

Possibility AI = flat LLM output, unverified, probabilistic.
Potential AI   = backed by Lean proofs, IVI grid triangles, gateway
                 attests, native capabilities, layer-invariant enforcement.

This monitor tracks the transition from one to the other in real-time:
  - Which native capabilities are replacing LLM functions
  - Gateway attest commit/reject rates (imaginary→real transitions)
  - Grid triangle closure rate (S→D→E completion)
  - Constraint accumulation from failures (potential space growing)
  - Lean verification pass rates
  - Skill derivation rate from grid structure

Runs as a background thread alongside the autonomous loop.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 1. Potential Score — quantifies how much of the system is "potential" vs "possibility"
# ---------------------------------------------------------------------------

@dataclass
class PotentialScore:
    """Snapshot of the system's potential-vs-possibility balance.

    potential_ratio approaches 1.0 as the system replaces possibility
    functions with verified, structured alternatives."""
    ts: float = 0.0

    # Gateway metrics (intent/attest)
    total_intents: int = 0
    committed_attests: int = 0
    rejected_attests: int = 0
    open_intents: int = 0           # imaginary: not yet resolved

    # Grid metrics (structural knowledge)
    triangles_closed: int = 0       # S→D→E complete = potential
    orphan_statements: int = 0      # unconnected = possibility
    orphan_equations: int = 0       # unverified = possibility
    total_claims: int = 0
    total_derivations: int = 0

    # Native capability metrics (replacing LLM)
    native_invocations: int = 0
    llm_fallbacks: int = 0
    native_ratio: float = 0.0      # native / (native + llm)
    capabilities_above_threshold: int = 0  # confidence >= 0.8

    # Lean metrics
    lean_checks_run: int = 0
    lean_passes: int = 0
    lean_failures: int = 0

    # Skill metrics
    skills_derived: int = 0
    skills_active: int = 0

    # Constraint accumulation (potential space growth)
    constraints_from_failures: int = 0
    successful_patterns: int = 0

    # Layer metrics
    layers_active: int = 0
    invariants_enforced: int = 0

    @property
    def potential_ratio(self) -> float:
        """0.0 = pure possibility, 1.0 = pure potential.
        Weighted composite of all sub-metrics."""
        scores: List[Tuple[float, float]] = []  # (score, weight)

        # Gateway: committed / total attests
        total_attests = self.committed_attests + self.rejected_attests
        if total_attests > 0:
            scores.append((self.committed_attests / total_attests, 3.0))

        # Grid: triangles / (triangles + orphans)
        grid_total = self.triangles_closed + self.orphan_statements + self.orphan_equations
        if grid_total > 0:
            scores.append((self.triangles_closed / grid_total, 2.0))

        # Native ratio: native / (native + llm)
        if self.native_invocations + self.llm_fallbacks > 0:
            scores.append((self.native_ratio, 2.0))

        # Lean: passes / total
        if self.lean_checks_run > 0:
            scores.append((self.lean_passes / self.lean_checks_run, 3.0))

        # Capabilities above threshold
        if self.capabilities_above_threshold > 0:
            scores.append((min(self.capabilities_above_threshold / 7.0, 1.0), 1.0))

        # Skills active
        if self.skills_derived > 0:
            scores.append((min(self.skills_active / max(1, self.skills_derived), 1.0), 1.0))

        if not scores:
            return 0.0

        weighted_sum = sum(s * w for s, w in scores)
        total_weight = sum(w for _, w in scores)
        return round(weighted_sum / total_weight, 4)

    @property
    def phase(self) -> str:
        """Human-readable phase of the possibility→potential transition."""
        r = self.potential_ratio
        if r < 0.2:
            return "possibility-dominant"
        elif r < 0.4:
            return "early-potential"
        elif r < 0.6:
            return "potential-emerging"
        elif r < 0.8:
            return "potential-dominant"
        else:
            return "potential-converged"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "potential_ratio": self.potential_ratio,
            "phase": self.phase,
            "gateway": {
                "intents": self.total_intents,
                "committed": self.committed_attests,
                "rejected": self.rejected_attests,
                "open": self.open_intents,
            },
            "grid": {
                "triangles_closed": self.triangles_closed,
                "orphan_statements": self.orphan_statements,
                "orphan_equations": self.orphan_equations,
                "total_claims": self.total_claims,
                "total_derivations": self.total_derivations,
            },
            "native": {
                "invocations": self.native_invocations,
                "llm_fallbacks": self.llm_fallbacks,
                "native_ratio": self.native_ratio,
                "capabilities_above_threshold": self.capabilities_above_threshold,
            },
            "lean": {
                "checks": self.lean_checks_run,
                "passes": self.lean_passes,
                "failures": self.lean_failures,
            },
            "skills": {
                "derived": self.skills_derived,
                "active": self.skills_active,
            },
            "potential_space": {
                "constraints_from_failures": self.constraints_from_failures,
                "successful_patterns": self.successful_patterns,
            },
            "layers": {
                "active": self.layers_active,
                "invariants_enforced": self.invariants_enforced,
            },
        }


# ---------------------------------------------------------------------------
# 2. FunctionReplacementTracker — tracks possibility→potential per function
# ---------------------------------------------------------------------------

@dataclass
class FunctionReplacement:
    """Tracks a single function's transition from possibility to potential."""
    name: str
    llm_function: str          # what LLM task it replaces
    first_seen_ts: float = 0.0
    native_uses: int = 0
    llm_uses: int = 0
    confidence: float = 0.0
    last_lean_result: str = ""
    grid_triangles: int = 0    # triangles referencing this function
    status: str = "possibility"  # "possibility" | "transitioning" | "potential"

    def update_status(self) -> None:
        """Recompute status based on metrics."""
        if self.confidence >= 0.85 and self.native_uses > self.llm_uses * 2:
            self.status = "potential"
        elif self.confidence >= 0.6 or self.native_uses > 0:
            self.status = "transitioning"
        else:
            self.status = "possibility"


class FunctionReplacementTracker:
    """Tracks which possibility-AI functions are being replaced by potential-AI."""

    def __init__(self) -> None:
        self._replacements: Dict[str, FunctionReplacement] = {}

    def register_from_capabilities(self, capabilities: Dict[str, Any]) -> None:
        """Import capability data from CapabilityRegistry."""
        for name, info in capabilities.items():
            if name not in self._replacements:
                self._replacements[name] = FunctionReplacement(
                    name=name,
                    llm_function=info.get("replaces", ""),
                    first_seen_ts=time.time(),
                )
            rep = self._replacements[name]
            rep.confidence = info.get("confidence", rep.confidence)
            rep.native_uses = info.get("invocations", rep.native_uses)
            rep.update_status()

    def record_native_use(self, name: str) -> None:
        if name in self._replacements:
            self._replacements[name].native_uses += 1
            self._replacements[name].update_status()

    def record_llm_fallback(self, name: str) -> None:
        if name in self._replacements:
            self._replacements[name].llm_uses += 1
            self._replacements[name].update_status()

    def record_lean_result(self, name: str, result: str) -> None:
        if name in self._replacements:
            self._replacements[name].last_lean_result = result

    def record_triangle(self, name: str) -> None:
        if name in self._replacements:
            self._replacements[name].grid_triangles += 1
            self._replacements[name].update_status()

    def summary(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {"possibility": 0, "transitioning": 0, "potential": 0}
        for rep in self._replacements.values():
            by_status[rep.status] = by_status.get(rep.status, 0) + 1
        return {
            "total_tracked": len(self._replacements),
            "by_status": by_status,
            "replacements": {
                name: {
                    "replaces": rep.llm_function,
                    "status": rep.status,
                    "confidence": round(rep.confidence, 2),
                    "native_uses": rep.native_uses,
                    "llm_uses": rep.llm_uses,
                    "grid_triangles": rep.grid_triangles,
                }
                for name, rep in self._replacements.items()
            },
        }


# ---------------------------------------------------------------------------
# 3. PotentialMonitor — continuous background watcher
# ---------------------------------------------------------------------------

class PotentialMonitor:
    """Continuously monitors the system building potential AI.

    Reads events.jsonl, queries the gateway, grid, native intelligence,
    and skills loop to produce live PotentialScore snapshots.

    Can run as a background thread that periodically samples and reports.
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self._scores: List[PotentialScore] = []
        self._tracker = FunctionReplacementTracker()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval: float = 30.0  # sample every 30 seconds
        self._event_cursor: int = 0   # position in events file for tailing
        self._live_metrics: Dict[str, Any] = {}

    @property
    def tracker(self) -> FunctionReplacementTracker:
        return self._tracker

    # ------------------------------------------------------------------
    # Sample: collect one PotentialScore snapshot
    # ------------------------------------------------------------------

    def sample(
        self,
        gateway: Any = None,
        grid: Any = None,
        native_cycle: Any = None,
        skills_loop: Any = None,
    ) -> PotentialScore:
        """Collect a single PotentialScore from all available sources."""
        score = PotentialScore(ts=time.time())

        # 1. Gateway metrics
        if gateway is not None:
            try:
                gw_status = gateway.status()
                score.total_intents = gw_status.get("intents_in_session", 0)
                domain = gw_status.get("domain", {})
                score.committed_attests = domain.get("real_committed", 0)
                score.rejected_attests = domain.get("rejected", 0)
                score.open_intents = domain.get("imaginary_staged", 0)

                # Layer metrics
                nav = gw_status.get("navigation", {})
                score.layers_active = len(nav.get("stack", []))
                score.invariants_enforced = len(nav.get("active_invariants", []))

                # Closure metrics from the closure operator
                if hasattr(gateway, "closure"):
                    potential = gateway.closure.reconstruct_potential_from_real()
                    score.constraints_from_failures = len(
                        potential.get("constraints_from_failures", [])
                    )
                    score.successful_patterns = len(
                        potential.get("successful_patterns", [])
                    )
            except Exception:
                pass

        # 2. Grid metrics
        if grid is not None:
            try:
                g = grid.grid if hasattr(grid, "grid") else grid
                if hasattr(g, "idx"):
                    score.triangles_closed = len(g.idx.triangles)
                    score.total_claims = len(g.idx.statements)
                    score.total_derivations = len(g.idx.derivations)

                    # Count orphans
                    connected_sids = set()
                    connected_eids = set()
                    for tr in g.idx.triangles.values():
                        connected_sids.add(tr.get("sid", ""))
                        connected_eids.add(tr.get("eid", ""))
                    score.orphan_statements = len(
                        set(g.idx.statements.keys()) - connected_sids
                    )
                    score.orphan_equations = len(
                        set(g.idx.equations.keys()) - connected_eids
                    )
            except Exception:
                pass

        # 3. Native capability metrics
        if native_cycle is not None:
            try:
                ns = native_cycle.status()
                score.native_invocations = ns.get("native_cycles", 0)
                score.llm_fallbacks = ns.get("llm_fallback_cycles", 0)
                score.native_ratio = ns.get("native_ratio", 0.0)

                caps = ns.get("capabilities", {}).get("capabilities", {})
                score.capabilities_above_threshold = sum(
                    1 for c in caps.values() if c.get("confidence", 0) >= 0.8
                )
                # Feed into replacement tracker
                self._tracker.register_from_capabilities(caps)
            except Exception:
                pass

        # 4. Skills metrics
        if skills_loop is not None:
            try:
                sk = skills_loop.status()
                score.skills_derived = sk.get("skills_extracted", 0)
                score.skills_active = sk.get("skills_active", 0)
            except Exception:
                pass

        # 5. Lean metrics from event log
        if self._settings is not None:
            try:
                self._scan_events_for_lean(score)
            except Exception:
                pass

        self._scores.append(score)
        self._live_metrics = score.to_dict()
        return score

    def _scan_events_for_lean(self, score: PotentialScore) -> None:
        """Scan events.jsonl from cursor for Lean results."""
        if self._settings is None:
            return
        events_path = self._settings.events_path
        if not events_path.exists():
            return

        with events_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines[self._event_cursor:]:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "attest":
                    payload = obj.get("payload", {})
                    lean_result = payload.get("lean_result", "")
                    if lean_result and lean_result != "skipped":
                        score.lean_checks_run += 1
                        if lean_result == "pass":
                            score.lean_passes += 1
                        else:
                            score.lean_failures += 1
            except (json.JSONDecodeError, KeyError):
                pass

        self._event_cursor = len(lines)

    # ------------------------------------------------------------------
    # Report: format current state for display
    # ------------------------------------------------------------------

    def report(self, score: Optional[PotentialScore] = None) -> str:
        """Format a human-readable report of the potential-building progress."""
        s = score or (self._scores[-1] if self._scores else None)
        if s is None:
            return "[potential monitor] no data yet"

        r = s.potential_ratio
        bar_len = 30
        filled = int(r * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        lines = [
            f"[potential] {bar} {r:.1%} — {s.phase}",
            f"  gateway: {s.committed_attests} committed, {s.rejected_attests} rejected, {s.open_intents} open",
            f"  grid: {s.triangles_closed} triangles, {s.orphan_statements} orphan stmts, {s.total_derivations} derivations",
            f"  native: {s.native_invocations} native, {s.llm_fallbacks} llm, ratio={s.native_ratio:.0%}",
            f"  lean: {s.lean_passes}/{s.lean_checks_run} passed",
            f"  skills: {s.skills_active}/{s.skills_derived} active",
            f"  layers: {s.layers_active} active, {s.invariants_enforced} invariants",
            f"  potential space: {s.constraints_from_failures} constraints, {s.successful_patterns} patterns",
        ]

        # Replacement tracker
        ts = self._tracker.summary()
        by_status = ts.get("by_status", {})
        if ts["total_tracked"] > 0:
            lines.append(
                f"  replacements: {by_status.get('potential', 0)} potential, "
                f"{by_status.get('transitioning', 0)} transitioning, "
                f"{by_status.get('possibility', 0)} possibility"
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Trend: how is the ratio changing over time
    # ------------------------------------------------------------------

    def trend(self) -> Dict[str, Any]:
        """Compute the trend of the potential ratio over recent samples."""
        if len(self._scores) < 2:
            return {"direction": "insufficient_data", "samples": len(self._scores)}

        recent = self._scores[-10:]
        ratios = [s.potential_ratio for s in recent]
        first_half = sum(ratios[:len(ratios)//2]) / max(1, len(ratios)//2)
        second_half = sum(ratios[len(ratios)//2:]) / max(1, len(ratios) - len(ratios)//2)
        delta = second_half - first_half

        if delta > 0.02:
            direction = "improving"
        elif delta < -0.02:
            direction = "declining"
        else:
            direction = "stable"

        return {
            "direction": direction,
            "delta": round(delta, 4),
            "latest_ratio": ratios[-1],
            "samples": len(self._scores),
            "latest_phase": self._scores[-1].phase,
        }

    # ------------------------------------------------------------------
    # Background thread: continuous monitoring
    # ------------------------------------------------------------------

    def start(
        self,
        gateway: Any = None,
        grid: Any = None,
        native_cycle: Any = None,
        skills_loop: Any = None,
        interval: float = 30.0,
        print_reports: bool = True,
    ) -> None:
        """Start continuous monitoring in a background thread."""
        if self._running:
            return
        self._interval = interval
        self._running = True

        def _monitor_loop() -> None:
            while self._running:
                try:
                    score = self.sample(
                        gateway=gateway,
                        grid=grid,
                        native_cycle=native_cycle,
                        skills_loop=skills_loop,
                    )
                    if print_reports:
                        report = self.report(score)
                        print(report, file=sys.stderr, flush=True)

                    # Write snapshot to .ivi/potential_monitor.json
                    if self._settings is not None:
                        try:
                            monitor_path = self._settings.ivi_dir / "potential_monitor.json"
                            monitor_path.parent.mkdir(parents=True, exist_ok=True)
                            snapshot = {
                                "score": score.to_dict(),
                                "trend": self.trend(),
                                "replacements": self._tracker.summary(),
                            }
                            with monitor_path.open("w", encoding="utf-8") as f:
                                json.dump(snapshot, f, indent=2, ensure_ascii=False)
                        except Exception:
                            pass

                except Exception as exc:
                    print(
                        f"[potential monitor] error: {exc}",
                        file=sys.stderr, flush=True,
                    )

                # Sleep in small intervals so we can stop quickly
                for _ in range(int(self._interval)):
                    if not self._running:
                        break
                    time.sleep(1)

        self._thread = threading.Thread(
            target=_monitor_loop, daemon=True, name="potential-monitor"
        )
        self._thread.start()

    def stop(self) -> Dict[str, Any]:
        """Stop the background monitor and return final summary."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

        final = {
            "samples_collected": len(self._scores),
            "trend": self.trend(),
            "replacements": self._tracker.summary(),
        }
        if self._scores:
            final["final_score"] = self._scores[-1].to_dict()
            final["final_report"] = self.report()
        return final

    def status(self) -> Dict[str, Any]:
        """Current monitor status."""
        return {
            "running": self._running,
            "samples": len(self._scores),
            "interval": self._interval,
            "live_metrics": self._live_metrics,
            "trend": self.trend(),
        }
