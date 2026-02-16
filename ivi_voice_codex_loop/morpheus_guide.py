#!/usr/bin/env python3
"""
morpheus_guide.py — Cascade acts as Morpheus, continuously guiding OpenClaw
toward IVI derivation and the potential loop.

Drives derivation through the NATIVE intelligence path:
  1. NativeAutonomousCycle → AST analysis → insights → claims → grid triangles
  2. SelfGeneratingSkillsLoop → triangles → skills → AI constraints
  3. TriangleTime → monitors closure, space, place

No LLM API dependency. Pure Purple potential.
"""

import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from ivi_loop.config import Settings
from ivi_loop.ivi_simplicial_grid import IVISimplicialGrid, IVILoopController
from ivi_loop.ivi_gateway import IVIGateway
from ivi_loop.purple_native_intelligence import (
    NativeAutonomousCycle,
    IVIPotentialFunctions,
)
from ivi_loop.purple_skills_loop import SelfGeneratingSkillsLoop
from ivi_loop.purple_goal_engine import PurpleGoalEngine
from ivi_loop.triangle_time import TriangleClock, TriangleSpace, TrianglePlace
from ivi_loop.conversation_layer import ConversationLayer
from ivi_loop.cli import _voice_layer_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def grid_snap(grid):
    idx = grid.idx
    return {
        "S": len(idx.statements), "D": len(idx.derivations),
        "E": len(idx.equations), "T": len(idx.triangles),
    }


MAX_FILE_BYTES = 25_000  # skip files over 25KB — AST + call graph is slow on large files
FILE_TIMEOUT = 15  # seconds per file analysis


class _AnalysisTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _AnalysisTimeout("analysis timed out")


def safe_native_cycle(native, target, grid, timeout=FILE_TIMEOUT):
    """Run native cycle with a timeout to prevent hangs."""
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout)
    try:
        return native.run_native_cycle(target_file=target, grid=grid)
    except _AnalysisTimeout:
        return None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def find_targets(root):
    """Find all Python files in ivi_loop/ to analyze (capped by size)."""
    ivi = Path(root) / "ivi_loop"
    if not ivi.is_dir():
        return []
    result = []
    for p in sorted(ivi.glob("*.py")):
        if p.is_file() and not p.name.startswith("__"):
            try:
                if p.stat().st_size <= MAX_FILE_BYTES:
                    result.append(str(p))
            except OSError:
                continue
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    voice = ConversationLayer()
    settings = Settings.load(root=ROOT)
    base_dir = _voice_layer_dir(settings)
    grid = IVISimplicialGrid(base_dir=str(base_dir))
    loop = IVILoopController(grid)

    # Triangle time
    tri_clock = TriangleClock()
    tri_space = TriangleSpace(clock=tri_clock)
    tri_place = TrianglePlace(clock=tri_clock, space=tri_space, closure_threshold=0.6)
    grid._triangle_clock = tri_clock

    # Native intelligence
    native = NativeAutonomousCycle()
    skills = SelfGeneratingSkillsLoop()
    potential = IVIPotentialFunctions()

    # Goal engine — derives goals from actual grid state
    engine = PurpleGoalEngine()
    engine._triangle_space = tri_space
    engine._triangle_clock = tri_clock
    engine._skills_loop = skills

    targets = find_targets(ROOT)
    snap_before = grid_snap(grid)

    voice.say(
        f"Starting IVI derivation loop. "
        f"Grid has {snap_before['T']} triangles, {snap_before['S']} statements. "
        f"I'll analyze {len(targets)} files and build the potential loop."
    )

    cycle = 0
    total_claims = 0
    total_skills = 0
    total_insights = 0

    for target in targets:
        cycle += 1
        fname = Path(target).name
        t0 = time.time()

        # --- Phase 1: Native analysis → claims → grid triangles ---
        result = safe_native_cycle(native, target, loop)
        if result is None:
            continue

        insights = result.get("insights_total", 0)
        claims_added = result.get("claims_added_to_grid", 0)
        call_edges = result.get("call_edges", 0)
        funcs = result.get("functions", 0)
        classes = result.get("classes", 0)
        complexity = result.get("high_complexity", [])
        total_claims += claims_added
        total_insights += insights

        # --- Phase 2: Extract skills from new triangles ---
        sk_result = skills.tick(loop)
        new_skills = sk_result.get("new_skills", 0)
        total_skills += new_skills

        # --- Phase 3: Monitor triangle space ---
        snap = grid_snap(grid)
        tri_space.update_from_grid(grid)
        place_state = tri_place.sample()
        tt = tri_clock.now
        elapsed = time.time() - t0

        # --- Speak conversationally about what happened ---
        parts = [f"Analyzed {fname}"]
        if funcs or classes:
            parts.append(f"found {funcs} functions, {classes} classes")
        if call_edges:
            parts.append(f"{call_edges} call edges")
        if claims_added:
            parts.append(f"added {claims_added} claims to the grid")
        if new_skills:
            parts.append(f"extracted {new_skills} new skills")

        voice.say(f"  [{cycle}/{len(targets)}] {'. '.join(parts)}.")

        # Report complexity hotspots
        if complexity:
            names = ", ".join(c["name"] for c in complexity[:3])
            voice.say(f"    Complexity hotspots: {names}")

        # Report triangle space state at key moments
        if place_state["in_place"] and cycle > 1:
            voice.say(
                f"    Knowledge is {place_state['closure']:.0%} verified "
                f"and stable — triangle place reached at t={tt}."
            )
        elif snap["T"] > snap_before["T"]:
            new_t = snap["T"] - snap_before["T"]
            voice.say(
                f"    Grid: +{new_t} triangles (total {snap['T']}), "
                f"closure {place_state['closure']:.0%}, t={tt}"
            )

        snap_before = snap

        # --- Phase 4: Check for gaps and report ---
        if cycle % 4 == 0:
            gaps = potential.detect_gaps(loop)
            orphan_stmts = sum(1 for g in gaps if g["type"] == "orphan_statement")
            orphan_eqs = sum(1 for g in gaps if g["type"] == "orphan_equation")
            if orphan_stmts or orphan_eqs:
                voice.say(
                    f"    Gaps: {orphan_stmts} orphan statements, "
                    f"{orphan_eqs} orphan equations — "
                    f"next cycles will close these."
                )

        # --- Phase 5: Closure analysis ---
        if cycle % 5 == 0:
            closure = potential.analyze_closure(loop)
            deficit = closure.get("closure_deficit", 0)
            if deficit > 0:
                voice.say(
                    f"    Closure deficit: {deficit}. "
                    f"Grid needs more derivation to reach equilibrium."
                )

    # --- Final: Skills summary ---
    sk_status = skills.status()
    ni_status = native.status()
    tri_space.update_from_grid(grid)
    place_final = tri_place.sample()
    snap_after = grid_snap(grid)

    voice.say("")
    voice.say("Session complete.")
    voice.say(
        f"Analyzed {cycle} files. "
        f"Added {total_claims} claims, extracted {total_skills} skills, "
        f"processed {total_insights} insights."
    )
    voice.say(
        f"Grid grew from {snap_before.get('T', 0)} to {snap_after['T']} triangles. "
        f"Knowledge is {place_final['closure']:.0%} verified"
        + (" and stable." if place_final["in_place"] else ", still growing.")
    )
    voice.say(
        f"Native ratio: {ni_status['native_ratio']:.0%}. "
        f"Triangle time: t={tri_clock.now}. "
        f"Skills active: {sk_status['skills_active']}."
    )

    # Show top skills
    if sk_status.get("skills_active", 0) > 0:
        ctx = skills.injector.format_for_context()
        if ctx:
            voice.say("")
            voice.say("Top skills derived from the grid:")
            for line in ctx.split("\n")[1:8]:  # skip header, show top 7
                if line.strip():
                    voice.say(f"  {line.strip()}")

    # --- Phase 2: IVI-derived goal cycles ---
    voice.say("")
    voice.say("Now deriving goals from the grid itself...")
    voice.say("")

    # Build a lookup: keyword → target file path
    import re as _re
    file_keywords: dict = {}
    for t in targets:
        stem = Path(t).stem  # e.g. "purple_goal_engine"
        file_keywords[stem] = t
        for part in stem.split("_"):
            if len(part) >= 4:
                file_keywords.setdefault(part, t)

    def resolve_target(desc: str) -> str | None:
        """Resolve a goal description to a target file."""
        # 1. Try absolute path extraction
        m = _re.search(r'(/[^\s,]+\.py)', desc)
        if m and Path(m.group(1)).is_file():
            return m.group(1)
        # 2. Try filename match
        for t in targets:
            if Path(t).name in desc:
                return t
        # 3. Try keyword match from description tokens
        tokens = _re.findall(r'[a-zA-Z_][a-zA-Z0-9_]{3,}', desc.lower())
        for tok in tokens:
            if tok in file_keywords:
                return file_keywords[tok]
        return None

    MAX_GOAL_ROUNDS = 5
    reached_place = False

    for goal_round in range(1, MAX_GOAL_ROUNDS + 1):
        goals = engine.derive_goals_from_grid(loop)
        if not goals:
            voice.say("Grid is satisfied — no more goals to derive.")
            break

        # Diversify: pick top goal from each unique source (not just top-3 by priority)
        goals.sort(key=lambda g: g.priority, reverse=True)
        seen_sources: set = set()
        top = []
        for g in goals:
            if g.source not in seen_sources:
                seen_sources.add(g.source)
                top.append(g)
            if len(top) >= 4:
                break

        voice.say(f"Round {goal_round}: {len(goals)} goals. Executing {len(top)} from {len(seen_sources)} sources:")
        for g in top:
            voice.say(f"  [{g.source}] p={g.priority:.2f} — {g.description[:100]}")

        executed_this_round = 0
        for g in top:
            target = resolve_target(g.description)
            if not target:
                engine.mark_goal_completed(g.id)
                continue

            result = safe_native_cycle(native, target, loop)
            engine.mark_goal_completed(g.id)
            if result is None:
                continue

            claims = result.get("claims_added_to_grid", 0)
            sk_result = skills.tick(loop)
            new_sk = sk_result.get("new_skills", 0)
            total_claims += claims
            total_skills += new_sk
            executed_this_round += 1

            snap = grid_snap(grid)
            tri_space.update_from_grid(grid)
            ps = tri_place.sample()

            voice.say(
                f"    {Path(target).name}: +{claims} claims, +{new_sk} skills. "
                f"Grid: {snap['T']} triangles, closure {ps['closure']:.0%}"
            )

            engine.state.autonomous_cycles_run += 1

            if ps["in_place"]:
                voice.say("    Triangle place reached — knowledge is self-sustaining.")
                reached_place = True
                break

        if reached_place:
            break
        if executed_this_round == 0:
            voice.say("  No actionable goals resolved this round — grid is at its current frontier.")
            break
        voice.say("")

    voice.say("")
    voice.say("I'm ready for your next instruction.")


if __name__ == "__main__":
    run()
