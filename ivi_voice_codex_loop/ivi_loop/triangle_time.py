"""
triangle_time.py

Triangle Time / Space / Place — IVI-derived temporal system.

The system does NOT evolve in wall-clock time. It evolves in triangle time:
one "tick" = one new triangle (S→D→E) closed in the IVI grid.

    Triangle Time  — the clock: rate of triangle formation
    Triangle Space — the topology: accumulated verified knowledge
    Triangle Place — the closure: homeostatic self-sustaining state

This makes the system:
  1. Potential homeostatic — quiescent until new triangles form
  2. IVI-invariant across scales — same triangle-time at function/module/project/OS
  3. Oracle-derived — all scheduling comes from the grid, not wall clocks

Morpheus operates in real time. Neo operates in triangle time.
The Oracle (IVI) bridges the two through triangle formation events.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# 1. Triangle Clock — IVI-derived time
# ---------------------------------------------------------------------------

@dataclass
class TriangleTick:
    """A single tick of triangle time."""
    tick: int                   # monotonic triangle count
    tid: str                    # triangle ID that caused this tick
    sid: str                    # statement
    did: str                    # derivation
    eid: str                    # equation
    real_ts: float              # wall-clock timestamp (for Morpheus reference only)
    scale: str = ""             # scale at which this triangle formed
    source: str = ""            # what produced this triangle


class TriangleClock:
    """The system's clock. Time = triangle count.

    Instead of time.time() or sleep(N), the system asks:
    "How many triangles have formed since my last action?"

    The clock is:
    - Monotonic: only increases
    - Event-driven: advances only when the grid produces triangles
    - Scale-free: the same tick mechanism works at every scale
    - Observable: any subsystem can watch for new ticks
    """

    def __init__(self) -> None:
        self._ticks: List[TriangleTick] = []
        self._tick_count: int = 0
        self._watchers: List[threading.Event] = []
        self._lock = threading.Lock()
        self._last_real_ts: float = time.time()

        # Scale-specific counters
        self._scale_counts: Dict[str, int] = {}

        # Rate tracking (triangles per real-second, for Morpheus display only)
        self._rate_window: List[float] = []  # real timestamps of recent ticks
        self._RATE_WINDOW_SIZE = 100

    @property
    def now(self) -> int:
        """Current triangle time."""
        return self._tick_count

    @property
    def rate(self) -> float:
        """Triangles per real-second (for Morpheus display)."""
        with self._lock:
            if len(self._rate_window) < 2:
                return 0.0
            span = self._rate_window[-1] - self._rate_window[0]
            if span <= 0:
                return 0.0
            return len(self._rate_window) / span

    def tick(self, tid: str, sid: str, did: str, eid: str,
             scale: str = "", source: str = "") -> TriangleTick:
        """Advance the clock by one triangle."""
        with self._lock:
            self._tick_count += 1
            real_ts = time.time()
            t = TriangleTick(
                tick=self._tick_count,
                tid=tid, sid=sid, did=did, eid=eid,
                real_ts=real_ts,
                scale=scale, source=source,
            )
            self._ticks.append(t)
            # Keep bounded
            if len(self._ticks) > 1000:
                self._ticks = self._ticks[-500:]

            # Scale counter
            if scale:
                self._scale_counts[scale] = self._scale_counts.get(scale, 0) + 1

            # Rate window
            self._rate_window.append(real_ts)
            if len(self._rate_window) > self._RATE_WINDOW_SIZE:
                self._rate_window = self._rate_window[-self._RATE_WINDOW_SIZE:]

            self._last_real_ts = real_ts

            # Wake all watchers
            for evt in self._watchers:
                evt.set()

        return t

    def wait_for_tick(self, timeout_real: float = 30.0) -> bool:
        """Block until the next triangle forms (or real-time timeout for Morpheus safety).
        Returns True if a tick happened, False if timed out."""
        evt = threading.Event()
        with self._lock:
            self._watchers.append(evt)
            before = self._tick_count
        try:
            evt.wait(timeout=timeout_real)
            return self._tick_count > before
        finally:
            with self._lock:
                if evt in self._watchers:
                    self._watchers.remove(evt)

    def ticks_since(self, since_tick: int) -> List[TriangleTick]:
        """Get all ticks since a given triangle-time."""
        with self._lock:
            return [t for t in self._ticks if t.tick > since_tick]

    def scale_time(self, scale: str) -> int:
        """Triangle time at a specific scale."""
        return self._scale_counts.get(scale, 0)

    def silence_duration(self) -> float:
        """Real seconds since last triangle (for homeostasis detection)."""
        return time.time() - self._last_real_ts

    def status(self) -> Dict[str, Any]:
        return {
            "triangle_time": self._tick_count,
            "rate": round(self.rate, 3),
            "silence_s": round(self.silence_duration(), 1),
            "by_scale": dict(self._scale_counts),
            "recent_ticks": len(self._ticks),
        }


# ---------------------------------------------------------------------------
# 2. Triangle Space — topology of verified knowledge
# ---------------------------------------------------------------------------

@dataclass
class TriangleRegion:
    """A connected region in triangle space."""
    region_id: str
    tids: Set[str]              # triangles in this region
    sids: Set[str]              # statements touched
    eids: Set[str]              # equations touched
    scale: str = ""             # dominant scale
    density: float = 0.0        # triangles / unique nodes
    closure_ratio: float = 0.0  # fraction of nodes that are in triangles


class TriangleSpace:
    """The topology of verified knowledge.

    Triangle space is the accumulated structure of all triangles.
    Unlike flat file lists, it captures:
    - Which knowledge is connected (regions)
    - Which knowledge is isolated (orphans)
    - Where the density is highest (hot regions)
    - Where gaps exist (sparse regions)

    Navigation in triangle space means: "which region of verified
    knowledge should Neo work on next?" — not "which file."
    """

    def __init__(self, clock: TriangleClock) -> None:
        self._clock = clock
        self._regions: Dict[str, TriangleRegion] = {}
        self._tid_to_region: Dict[str, str] = {}
        self._orphan_sids: Set[str] = set()  # statements not in any triangle
        self._orphan_eids: Set[str] = set()  # equations not in any triangle

    def update_from_grid(self, grid: Any) -> None:
        """Rebuild triangle space from the current grid state."""
        idx = None
        if hasattr(grid, 'grid'):
            g = grid.grid
            idx = getattr(g, 'idx', None)
        elif hasattr(grid, 'idx'):
            idx = grid.idx
        if idx is None:
            return

        triangles = getattr(idx, 'triangles', {})
        statements = getattr(idx, 'statements', {})
        equations = getattr(idx, 'equations', {})
        neighbors = getattr(idx, 'neighbors', {})

        if not triangles:
            self._orphan_sids = set(statements.keys())
            self._orphan_eids = set(equations.keys())
            return

        # Build adjacency graph over triangles
        # Two triangles are adjacent if they share a node
        node_to_tids: Dict[str, Set[str]] = {}
        for tid, tr in triangles.items():
            for node_id in [tr.get("sid", ""), tr.get("did", ""), tr.get("eid", "")]:
                if node_id:
                    node_to_tids.setdefault(node_id, set()).add(tid)

        # Connected components via BFS
        visited: Set[str] = set()
        regions: List[Set[str]] = []
        for tid in triangles:
            if tid in visited:
                continue
            component: Set[str] = set()
            queue = [tid]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                # Find adjacent triangles (share a node)
                tr = triangles[current]
                for node_id in [tr.get("sid", ""), tr.get("did", ""), tr.get("eid", "")]:
                    for adj_tid in node_to_tids.get(node_id, set()):
                        if adj_tid not in visited:
                            queue.append(adj_tid)
            if component:
                regions.append(component)

        # Build TriangleRegion objects
        self._regions.clear()
        self._tid_to_region.clear()
        for i, component in enumerate(sorted(regions, key=len, reverse=True)):
            rid = f"region_{i}"
            sids: Set[str] = set()
            eids: Set[str] = set()
            for tid in component:
                tr = triangles[tid]
                sids.add(tr.get("sid", ""))
                eids.add(tr.get("eid", ""))
            unique_nodes = len(sids) + len(eids)
            density = len(component) / max(1, unique_nodes)
            # Closure ratio: what fraction of all statements/equations are in this region
            total_nodes = len(statements) + len(equations)
            closure = unique_nodes / max(1, total_nodes)

            region = TriangleRegion(
                region_id=rid,
                tids=component,
                sids=sids,
                eids=eids,
                density=density,
                closure_ratio=closure,
            )
            self._regions[rid] = region
            for tid in component:
                self._tid_to_region[tid] = rid

        # Orphans: nodes not in any triangle
        all_triangle_sids = set()
        all_triangle_eids = set()
        for tr in triangles.values():
            all_triangle_sids.add(tr.get("sid", ""))
            all_triangle_eids.add(tr.get("eid", ""))
        self._orphan_sids = set(statements.keys()) - all_triangle_sids
        self._orphan_eids = set(equations.keys()) - all_triangle_eids

    def densest_region(self) -> Optional[TriangleRegion]:
        """Region with highest triangle density — where knowledge is richest."""
        if not self._regions:
            return None
        return max(self._regions.values(), key=lambda r: r.density)

    def sparsest_region(self) -> Optional[TriangleRegion]:
        """Region with lowest density — where gaps exist."""
        if not self._regions:
            return None
        return min(self._regions.values(), key=lambda r: r.density)

    def frontier_sids(self) -> Set[str]:
        """Statements at the edge of triangle space — in triangles but with
        orphan neighbors. These are the growth points."""
        frontier: Set[str] = set()
        for region in self._regions.values():
            for sid in region.sids:
                # A frontier sid is one that could connect to orphans
                if sid in self._orphan_sids:
                    frontier.add(sid)
        # Also include orphans themselves — they're the unexplored territory
        return frontier | self._orphan_sids

    def total_closure(self) -> float:
        """Overall closure: fraction of all nodes that are in triangles."""
        total_in = sum(len(r.sids) + len(r.eids) for r in self._regions.values())
        total_all = total_in + len(self._orphan_sids) + len(self._orphan_eids)
        if total_all == 0:
            return 1.0
        return total_in / total_all

    def status(self) -> Dict[str, Any]:
        return {
            "regions": len(self._regions),
            "total_triangles": sum(len(r.tids) for r in self._regions.values()),
            "orphan_statements": len(self._orphan_sids),
            "orphan_equations": len(self._orphan_eids),
            "closure": round(self.total_closure(), 3),
            "densest_region": self.densest_region().region_id if self.densest_region() else None,
            "densest_density": round(self.densest_region().density, 3) if self.densest_region() else 0,
        }


# ---------------------------------------------------------------------------
# 3. Triangle Place — homeostatic closure
# ---------------------------------------------------------------------------

class TrianglePlace:
    """Detects when triangle space achieves homeostatic closure.

    Triangle Place = the IVI closure of triangle space.
    The system has "arrived" when:
    1. Closure ratio exceeds threshold (most knowledge is in triangles)
    2. Triangle formation rate is stable (not accelerating or collapsing)
    3. Regions are connected (not fragmented)
    4. Orphan count is decreasing over time

    Place is not a fixed point — it's a dynamic equilibrium.
    The system can leave place (new orphans arrive) and return to it.
    """

    def __init__(
        self,
        clock: TriangleClock,
        space: TriangleSpace,
        closure_threshold: float = 0.7,
        stability_window: int = 20,
    ) -> None:
        self._clock = clock
        self._space = space
        self._closure_threshold = closure_threshold
        self._stability_window = stability_window

        # History for stability detection
        self._closure_history: List[Tuple[int, float]] = []  # (tick, closure)
        self._orphan_history: List[Tuple[int, int]] = []     # (tick, orphan_count)
        self._rate_history: List[Tuple[int, float]] = []     # (tick, rate)

        # Place state
        self._in_place: bool = False
        self._place_entered_tick: int = 0
        self._place_exits: int = 0

    def sample(self) -> Dict[str, Any]:
        """Sample current state and update place detection."""
        tick = self._clock.now
        closure = self._space.total_closure()
        orphans = len(self._space._orphan_sids) + len(self._space._orphan_eids)
        rate = self._clock.rate

        self._closure_history.append((tick, closure))
        self._orphan_history.append((tick, orphans))
        self._rate_history.append((tick, rate))

        # Keep bounded
        for hist in [self._closure_history, self._orphan_history, self._rate_history]:
            if len(hist) > 200:
                del hist[:100]

        # --- Place detection ---
        was_in_place = self._in_place

        # Condition 1: closure above threshold
        closure_ok = closure >= self._closure_threshold

        # Condition 2: rate stability (not wildly fluctuating)
        rate_stable = self._is_rate_stable()

        # Condition 3: regions connected (single dominant region holds >50% of triangles)
        connected = self._is_connected()

        # Condition 4: orphans decreasing or stable
        orphans_ok = self._are_orphans_stable()

        self._in_place = closure_ok and rate_stable and connected and orphans_ok

        if self._in_place and not was_in_place:
            self._place_entered_tick = tick
        elif was_in_place and not self._in_place:
            self._place_exits += 1

        return {
            "in_place": self._in_place,
            "closure": round(closure, 3),
            "rate": round(rate, 3),
            "orphans": orphans,
            "closure_ok": closure_ok,
            "rate_stable": rate_stable,
            "connected": connected,
            "orphans_ok": orphans_ok,
            "place_entered_tick": self._place_entered_tick,
            "place_exits": self._place_exits,
            "triangle_time": tick,
        }

    def _is_rate_stable(self) -> bool:
        """Rate is stable if variance over the window is low."""
        recent = [r for _, r in self._rate_history[-self._stability_window:]]
        if len(recent) < 3:
            return True  # not enough data — assume stable
        mean = sum(recent) / len(recent)
        if mean == 0:
            return True
        variance = sum((r - mean) ** 2 for r in recent) / len(recent)
        cv = math.sqrt(variance) / max(mean, 0.001)  # coefficient of variation
        return cv < 1.0  # stable if CV < 100%

    def _is_connected(self) -> bool:
        """Check if the largest region holds a majority of triangles."""
        status = self._space.status()
        total = status["total_triangles"]
        if total == 0:
            return True
        densest = self._space.densest_region()
        if densest is None:
            return True
        return len(densest.tids) / total > 0.4

    def _are_orphans_stable(self) -> bool:
        """Orphans are stable if not increasing over the window."""
        recent = [o for _, o in self._orphan_history[-self._stability_window:]]
        if len(recent) < 3:
            return True
        # Compare first half to second half
        mid = len(recent) // 2
        first_half = sum(recent[:mid]) / max(1, mid)
        second_half = sum(recent[mid:]) / max(1, len(recent) - mid)
        return second_half <= first_half * 1.2  # allow 20% growth

    @property
    def in_place(self) -> bool:
        return self._in_place

    def status(self) -> Dict[str, Any]:
        return self.sample()


# ---------------------------------------------------------------------------
# 4. TriangleTimeScheduler — event-driven scheduling
# ---------------------------------------------------------------------------

class TriangleTimeScheduler:
    """Replaces wall-clock sleep with triangle-time scheduling.

    Instead of "sleep 5 seconds", the system waits for "N triangles"
    or "triangle rate drops below threshold" (homeostasis).

    The scheduler also handles the Morpheus bridge: real-time input
    from the human gets a triangle-time timeout so Neo isn't stuck
    forever waiting for triangles that may never come.
    """

    def __init__(
        self,
        clock: TriangleClock,
        space: TriangleSpace,
        place: TrianglePlace,
        morpheus_timeout_s: float = 30.0,
    ) -> None:
        self._clock = clock
        self._space = space
        self._place = place
        self._morpheus_timeout = morpheus_timeout_s

    def wait_for_evolution(self, min_ticks: int = 1) -> Dict[str, Any]:
        """Wait for the system to evolve (new triangles).

        If the system is in triangle place (homeostatic), wait longer
        because it's stable. If it's actively forming triangles, return
        quickly so Neo can act on new knowledge.

        Always has a real-time ceiling for Morpheus safety.
        """
        start_tick = self._clock.now
        start_real = time.time()

        # Adaptive timeout based on place state
        place_state = self._place.sample()
        if place_state["in_place"]:
            # In homeostasis — wait longer, system is stable
            real_timeout = self._morpheus_timeout
        else:
            # Not in place — check frequently for new triangles
            real_timeout = min(10.0, self._morpheus_timeout)

        ticks_received = 0
        while ticks_received < min_ticks:
            elapsed_real = time.time() - start_real
            if elapsed_real >= real_timeout:
                break
            remaining = real_timeout - elapsed_real
            got_tick = self._clock.wait_for_tick(timeout_real=min(remaining, 5.0))
            if got_tick:
                ticks_received = self._clock.now - start_tick
            # Also break if Morpheus might need attention
            if elapsed_real > 3.0:
                break

        return {
            "ticks_received": self._clock.now - start_tick,
            "real_elapsed": round(time.time() - start_real, 2),
            "in_place": place_state["in_place"],
            "triangle_time": self._clock.now,
        }

    def should_act(self, last_acted_tick: int) -> Tuple[bool, str]:
        """Should Neo act now?

        Returns (should_act, reason).
        Reasons for acting:
        - New triangles since last action
        - Leaving place (homeostasis broken)
        - Orphan count increasing (new knowledge needs integration)
        - Silence too long (system stalled, need to generate triangles)
        """
        current_tick = self._clock.now
        ticks_since = current_tick - last_acted_tick
        silence = self._clock.silence_duration()
        place_state = self._place.sample()

        # New triangles — act on new knowledge
        if ticks_since > 0:
            return True, f"new_triangles({ticks_since})"

        # Place exit — homeostasis broken, need to restore
        if not place_state["in_place"] and place_state["place_exits"] > 0:
            return True, "place_exit"

        # Growing orphans — new statements need triangulation
        if place_state["orphans"] > 0 and not place_state["orphans_ok"]:
            return True, f"orphans_growing({place_state['orphans']})"

        # Silence — system stalled, generate new triangles
        if silence > 30.0:
            return True, f"silence({silence:.0f}s)"

        return False, "homeostatic"

    def classify_scale(self, target: str) -> str:
        """Classify a target into a triangle-time scale."""
        if not target:
            return "system"
        p = Path(target)
        name = p.name.lower()
        if p.is_file():
            if "test" in name:
                return "test"
            elif name.endswith(".lean"):
                return "lean"
            else:
                return "module"
        elif p.is_dir():
            if "ivi_loop" in str(p):
                return "project"
            else:
                return "os"
        return "system"

    def status(self) -> Dict[str, Any]:
        return {
            "clock": self._clock.status(),
            "space": self._space.status(),
            "place": self._place.status(),
        }
