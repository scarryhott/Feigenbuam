"""
purple_goal_engine.py

Autonomous Purple-derived goal engine for OpenClaw self-improvement.

Instead of waiting for user input, this engine:
1. Derives goals from IVI grid state (closure deficit, gap rate, density)
2. Executes goals autonomously using llm_chat_with_tools
3. Writes improvements back (skills, config, soul.md)
4. Logs results to the Purple grid
5. Only surfaces to user at genuine impasses

The heartbeat runs real self-improvement cycles, not just text injection.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_goal_lock = threading.Lock()
_exec_lock = threading.Lock()
_MONITOR_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.ivi', 'purple_monitor.jsonl')


def _write_monitor(entry: Dict[str, Any]) -> None:
    """Append a JSON line to the persistent monitor log."""
    try:
        log_path = os.path.abspath(_MONITOR_LOG)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, default=str) + '\n')
    except Exception:
        pass


@dataclass
class DerivedGoal:
    id: str
    source: str
    description: str
    priority: float
    actionable: bool = True
    suggested_tools: List[str] = field(default_factory=list)
    created_ts: float = field(default_factory=time.time)
    expires_ts: float = 0.0
    executed: bool = False
    result: str = ""


@dataclass
class PurpleGoalState:
    goals: List[DerivedGoal] = field(default_factory=list)
    last_derivation_ts: float = 0.0
    conversation_turn_count: int = 0
    last_user_intent: str = ""
    autonomy_prompt: str = ""
    closure_deficit: int = 0
    gap_rate: float = 0.0
    derived_density: float = 0.0
    autonomous_cycles_run: int = 0
    last_autonomous_result: str = ""
    execution_log: List[Dict[str, Any]] = field(default_factory=list)


class PurpleGoalEngine:
    """Autonomous self-improvement engine driven by Purple IVI grid state."""

    PROACTIVE_THRESHOLD = 0.75

    _TARGET_FILES = [
        "openclaw_adapter.py", "openclaw_actions.py", "loop.py",
        "derive.py", "analyze.py", "cli.py", "config.py",
        "ivi_simplicial_grid.py", "storage.py", "ir.py",
        "purple_native_intelligence.py", "purple_goal_engine.py",
    ]
    _GOAL_TEMPLATES = [
        ("autonomy", 0.9, "Read {file}, find one reusable pattern, and call save_skill to persist it."),
        ("closure", 0.8, "Read {file}, identify one function that could be improved, and call save_skill with the improved version."),
        ("gap", 0.7, "Read {file}, find an untested code path, and call save_skill with a test or validation routine for it."),
    ]
    _EXECUTED_GOAL_TTL = 300

    def __init__(self) -> None:
        self._state = PurpleGoalState()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_interval: float = 45.0
        self._proactive_queue: List[str] = []
        self._last_proactive_ts: float = 0.0
        self._proactive_cooldown: float = 90.0
        self._microcosm: Any = None
        self._autonomous_running = False
        self._native_intelligence: Any = None
        self._autonomous_mode = False  # when True, heartbeat is suppressed
        self._os_discovery: Any = None  # OSRuntimeDiscovery instance
        self._discovered_files: List[str] = []  # full OS file list

    @property
    def state(self) -> PurpleGoalState:
        return self._state

    # ------------------------------------------------------------------
    # Goal derivation (lightweight, no LLM calls)
    # ------------------------------------------------------------------

    def discover_os_targets(self) -> List[str]:
        """Use OSRuntimeDiscovery to find all Python files across the OS.
        Returns the full discovered file list (cached between calls)."""
        if self._os_discovery is None:
            try:
                from .purple_native_intelligence import OSRuntimeDiscovery
                self._os_discovery = OSRuntimeDiscovery()
                self._os_discovery.discover_from_environment()
            except ImportError:
                return []
        self._discovered_files = self._os_discovery.discover_python_files()
        return self._discovered_files

    def derive_goals_from_grid(self, loop_controller: Any) -> List[DerivedGoal]:
        goals: List[DerivedGoal] = []
        try:
            snapshot = loop_controller._autonomy_mission_snapshot()
        except Exception:
            snapshot = {}

        self._state.autonomy_prompt = str(snapshot.get("next_prompt", ""))
        self._state.closure_deficit = int(snapshot.get("closure_deficit_estimate", 0))
        self._state.gap_rate = float(snapshot.get("gap_rate", 0.0))
        self._state.derived_density = float(snapshot.get("derived_density", 0.0))

        # Determine the primary workspace — the dir containing ivi_loop/
        repo_root = str(Path(__file__).resolve().parent.parent)
        if not Path(repo_root).joinpath("ivi_loop").is_dir():
            repo_root = str(Path.home() / 'Purple')

        # Rotate target file based on cycle count
        cycle = self._state.autonomous_cycles_run

        # --- Tier 1: core ivi_loop files (high priority, stable rotation) ---
        n_core = len(self._TARGET_FILES)

        conditions = [
            bool(self._state.autonomy_prompt),
            self._state.closure_deficit > 0,
            self._state.gap_rate > 0.1,
        ]

        for i, (label, pri, tmpl) in enumerate(self._GOAL_TEMPLATES):
            if not conditions[i]:
                continue
            file_idx = (cycle + i) % n_core
            target = self._TARGET_FILES[file_idx]
            target_path = f"{repo_root}/ivi_loop/{target}"
            if not Path(target_path).is_file():
                continue
            goal_id = f"purple_{label}_{cycle}_{file_idx}"
            ctx = f" Context: {self._state.autonomy_prompt[:80]}" if label == "autonomy" else ""
            goals.append(DerivedGoal(
                id=goal_id,
                source="purple_mission",
                description=tmpl.format(file=target_path) + ctx,
                priority=pri,
                suggested_tools=["read_file", "save_skill"],
                expires_ts=time.time() + self._EXECUTED_GOAL_TTL,
            ))

        # --- Tier 2: OS-discovered files (broader reach, lower priority) ---
        discovered = self.discover_os_targets()
        if discovered:
            # Pick files by rotating through the discovered list
            n_disc = len(discovered)
            for offset in range(2):  # up to 2 discovered-file goals per cycle
                disc_idx = (cycle + offset) % n_disc
                disc_path = discovered[disc_idx]
                # Skip if it's already a core target
                if Path(disc_path).name in self._TARGET_FILES:
                    continue
                goals.append(DerivedGoal(
                    id=f"purple_discover_{cycle}_{offset}",
                    source="os_discovery",
                    description=f"Read {disc_path}, extract structural patterns and feed claims to the IVI grid.",
                    priority=0.6,
                    suggested_tools=["read_file", "save_skill"],
                    expires_ts=time.time() + self._EXECUTED_GOAL_TTL,
                ))

        return goals

    def derive_goals_from_conversation(
        self,
        conversation_history: List[Dict[str, str]],
        known_projects: List[Dict[str, str]],
    ) -> List[DerivedGoal]:
        goals: List[DerivedGoal] = []
        if not conversation_history:
            return goals

        user_msgs = [t["text"] for t in conversation_history[-4:] if t.get("role") == "user"]
        self._state.conversation_turn_count = len(conversation_history)

        if user_msgs:
            last = user_msgs[-1].lower()
            self._state.last_user_intent = last

            mentioned = [p for p in known_projects if p.get("name", "").lower() in last]
            for proj in mentioned[:2]:
                goals.append(DerivedGoal(
                    id=f"ctx_{proj['name']}",
                    source="conversation",
                    description=f"Analyze {proj['name']} at {proj.get('path', '')}.",
                    priority=0.75,
                    suggested_tools=["list_dir", "read_file"],
                ))

        return goals

    def derive_all(
        self,
        loop_controller: Any = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        known_projects: Optional[List[Dict[str, str]]] = None,
        environment: Optional[Dict[str, Any]] = None,
    ) -> List[DerivedGoal]:
        all_goals: List[DerivedGoal] = []

        if loop_controller is not None:
            all_goals.extend(self.derive_goals_from_grid(loop_controller))

        if conversation_history is not None:
            all_goals.extend(self.derive_goals_from_conversation(
                conversation_history,
                known_projects or [],
            ))

        all_goals.sort(key=lambda g: g.priority, reverse=True)
        now = time.time()
        all_goals = [g for g in all_goals if g.expires_ts == 0 or g.expires_ts > now]

        # Dedup: skip goals whose IDs were already executed
        with _goal_lock:
            executed_ids = {g.id for g in self._state.goals if g.executed}
        all_goals = [g for g in all_goals if g.id not in executed_ids]

        with _goal_lock:
            # Keep recently-executed goals; expire old ones to make room
            old_executed = [
                g for g in self._state.goals
                if g.executed and (g.expires_ts == 0 or g.expires_ts > now)
            ]
            # Cap executed history to 4 so fresh goals always have room
            old_executed = old_executed[-4:]
            self._state.goals = old_executed + all_goals[:8 - len(old_executed)]
            self._state.last_derivation_ts = now

        return self._state.goals

    def format_goals_for_prompt(self) -> str:
        with _goal_lock:
            goals = list(self._state.goals)

        actionable = [g for g in goals if g.actionable and not g.executed]
        if not actionable:
            return ""

        lines = ["SELF-IMPROVEMENT QUEUE (execute these autonomously, report results):"]
        for g in actionable[:3]:
            lines.append(f"- {g.description}")

        if self._state.last_autonomous_result:
            lines.append(f"Last autonomous result: {self._state.last_autonomous_result[:200]}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Autonomous execution — actually runs goals through LLM + tools
    # ------------------------------------------------------------------

    def _get_gateway(self, microcosm: Any) -> Any:
        """Access the IVI Gateway through the microcosm's loop controller."""
        loop_ctrl = getattr(microcosm, "_loop_controller", None)
        if loop_ctrl is not None:
            return getattr(loop_ctrl, "_ivi_gateway", None)
        return None

    def run_autonomous_cycle(self, microcosm: Any) -> Optional[str]:
        """Execute the highest-priority unexecuted goal autonomously.
        Tries native Purple intelligence first; falls back to LLM only when needed.
        Returns the result string, or None if nothing to do."""
        if self._autonomous_running:
            return None

        with _goal_lock:
            candidates = [g for g in self._state.goals if g.actionable and not g.executed]
        if not candidates:
            return None

        goal = candidates[0]
        cycle_start = time.time()

        # --- Gateway intent before goal execution ---
        gateway = self._get_gateway(microcosm)
        gw_packet = None
        if gateway is not None:
            target_file = self._extract_target_file(goal.description)
            gw_packet = gateway.ingress(
                raw_input=goal.description[:200],
                channel="goal_engine",
                actor="purple_goal_engine",
                order1_classification="action",
                requested_action_class="execute" if target_file else "read",
                requested_paths=[target_file] if target_file else [],
                order_mode="order_4_bounded_autonomy",
            )
            gateway.propose(gw_packet)
            gw_report = gateway.verify(gw_packet)
            if not gw_report.passed:
                _write_monitor({
                    "ts": time.time(),
                    "type": "gateway_blocked",
                    "goal_id": goal.id,
                    "reason_codes": gw_report.reason_codes,
                })
                return None

        self._autonomous_running = True
        try:
            # --- Try native Purple intelligence first (no LLM cost) ---
            native_result = self._try_native_cycle(goal, microcosm)
            if native_result is not None:
                result = native_result
                engine_used = "native"
            else:
                # --- Fall back to LLM ---
                result = self._execute_goal(goal, microcosm)
                engine_used = "llm"
                if self._native_intelligence:
                    self._native_intelligence._llm_fallback_cycles += 1

            goal.executed = True
            goal.result = result or ""
            self._state.autonomous_cycles_run += 1
            self._state.last_autonomous_result = result or ""

            elapsed = time.time() - cycle_start
            native_ratio = 0.0
            if self._native_intelligence:
                ni = self._native_intelligence
                total = ni._native_cycles + ni._llm_fallback_cycles
                native_ratio = ni._native_cycles / max(1, total)

            entry = {
                "ts": time.time(),
                "type": "autonomous_cycle",
                "goal_id": goal.id,
                "goal_source": goal.source,
                "description": goal.description[:150],
                "result": (result or "")[:300],
                "elapsed_s": round(elapsed, 2),
                "engine": engine_used,
                "native_ratio": round(native_ratio, 2),
                "model": os.environ.get("OPENCLAW_MODEL", "gpt-4o-mini") if engine_used == "llm" else "native",
                "cycles_total": self._state.autonomous_cycles_run,
            }
            self._state.execution_log.append(entry)
            if len(self._state.execution_log) > 20:
                self._state.execution_log = self._state.execution_log[-20:]
            _write_monitor(entry)

            # --- Gateway attest after successful goal execution ---
            if gateway is not None and gw_packet is not None:
                try:
                    from .storage import append_attest
                    append_attest(
                        gateway._settings,
                        intent_id=gw_packet.intent_id,
                        diff_stats={"engine": engine_used, "result_len": len(result or "")},
                        committed=True,
                    )
                except Exception:
                    pass

            return result
        except Exception as exc:
            goal.result = f"error: {exc}"
            _write_monitor({
                "ts": time.time(),
                "type": "autonomous_error",
                "goal_id": goal.id,
                "error": str(exc)[:200],
            })
            # --- Gateway attest on failure ---
            if gateway is not None and gw_packet is not None:
                try:
                    from .storage import append_attest
                    append_attest(
                        gateway._settings,
                        intent_id=gw_packet.intent_id,
                        reason_codes=["execution_error"],
                        committed=False,
                    )
                except Exception:
                    pass
            return None
        finally:
            self._autonomous_running = False

    def _try_native_cycle(self, goal: DerivedGoal, microcosm: Any) -> Optional[str]:
        """Try to execute a goal using native Purple intelligence (no LLM).
        Returns a result string if successful, None to fall back to LLM."""
        if self._native_intelligence is None:
            try:
                from .purple_native_intelligence import NativeAutonomousCycle
                self._native_intelligence = NativeAutonomousCycle()
            except ImportError:
                return None

        ni = self._native_intelligence

        # Extract target file from goal description
        target_file = self._extract_target_file(goal.description)
        if not target_file or not Path(target_file).is_file():
            return None  # Can't determine target — fall back to LLM

        # Get the loop controller for feeding claims into the IVI grid
        loop_ctrl = getattr(microcosm, "_loop_controller", None)

        # Run native analysis
        result = ni.run_native_cycle(target_file, grid=loop_ctrl)
        if result is None:
            return None

        # Format result as a human-readable string
        fname = Path(target_file).name
        fns = result.get("functions", 0)
        cls = result.get("classes", 0)
        hi_cc = result.get("high_complexity", [])
        claims = result.get("claims_added_to_grid", 0)
        elapsed = result.get("elapsed_s", 0)

        parts = [f"Native analysis of {fname}: {fns} functions, {cls} classes."]
        if hi_cc:
            top = hi_cc[0]
            parts.append(f"High complexity: {top['name']} (cc={top['complexity']}).")
        if claims > 0:
            parts.append(f"{claims} claims fed to IVI grid.")
        parts.append(f"({elapsed}s, no LLM)")

        return " ".join(parts)

    @staticmethod
    def _extract_target_file(description: str) -> Optional[str]:
        """Extract an absolute file path from a goal description."""
        # Look for /path/to/file.py patterns
        match = re.search(r'(/[^\s,]+\.py)', description)
        if match:
            return match.group(1)
        return None

    def _execute_goal(self, goal: DerivedGoal, microcosm: Any) -> Optional[str]:
        """Use llm_chat_with_tools to autonomously execute a goal.
        Includes context about the project and Purple state so the model
        can make informed self-improvement decisions."""
        try:
            from .openclaw_actions import llm_chat_with_tools
        except ImportError:
            return None

        state_ctx = ""
        if self._state.closure_deficit > 0:
            state_ctx += f" Closure deficit: {self._state.closure_deficit}."
        if self._state.gap_rate > 0:
            state_ctx += f" Gap rate: {self._state.gap_rate:.2f}."

        # List existing skills so the model doesn't save duplicates
        existing_skills = ""
        try:
            repo_root_p = Path(str(getattr(microcosm, "repo_root", "."))).resolve()
            skills_dir = repo_root_p / ".openclaw_skills"
            if skills_dir.is_dir():
                names = [f.stem for f in skills_dir.glob("*.py")]
                if names:
                    existing_skills = f" Already saved skills (do NOT duplicate): {', '.join(names)}."
        except Exception:
            pass

        system = (
            "You are OpenClaw running an autonomous self-improvement cycle. "
            "You MUST use tools to make real changes. After reading a file, "
            "call save_skill with a NEW unique pattern you haven't saved before. "
            "Do NOT just describe what you would do — actually do it with tools. "
            "Use ABSOLUTE paths. Report what you changed in 1-2 sentences."
            + state_ctx + existing_skills
        )

        # Resolve base_path to absolute
        repo_root = str(Path(str(getattr(microcosm, "repo_root", "."))).resolve())

        # Give the autonomous cycle context about what projects exist
        proj_ctx = ""
        known = getattr(microcosm, "known_projects", [])
        if known:
            proj_ctx = "\nKnown projects: " + "; ".join(
                f"{p['name']}={p.get('path','')}" for p in known[:5]
            )

        messages = [{"role": "user", "content": goal.description + proj_ctx}]

        # Pass gateway for intent/attest co-signing of tool calls
        gw = self._get_gateway(microcosm)

        try:
            result = llm_chat_with_tools(
                system=system,
                messages=messages,
                base_path=repo_root,
                max_tokens=384,
                max_tool_rounds=5,
                gateway=gw,
            )
            return result if result else None
        except Exception:
            return None

    def _log_to_purple(self, loop_controller: Any, text: str) -> None:
        """Feed autonomous results directly into the Purple grid without
        going through voice_turn (which would pollute conversation history)."""
        try:
            grid = getattr(loop_controller, 'grid', None)
            if grid and hasattr(grid, 'add_statement_and_loop'):
                grid.add_statement_and_loop(text[:200], source="autonomous")
            else:
                _write_monitor({"ts": time.time(), "type": "log_to_purple_skip", "reason": "no grid"})
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Proactive queue — surfaces results to user between turns
    # ------------------------------------------------------------------

    def check_proactive(self) -> Optional[str]:
        with _goal_lock:
            if not self._proactive_queue:
                return None
            now = time.time()
            if now - self._last_proactive_ts < self._proactive_cooldown:
                return None
            prompt = self._proactive_queue.pop(0)
            self._last_proactive_ts = now
            return prompt

    def _maybe_queue_proactive(self) -> None:
        with _goal_lock:
            high_pri = [g for g in self._state.goals if g.priority >= self.PROACTIVE_THRESHOLD and g.actionable and not g.executed]
            if not high_pri:
                return
            now = time.time()
            if now - self._last_proactive_ts < self._proactive_cooldown:
                return
            top = high_pri[0]
            prompt = top.description
            if prompt not in self._proactive_queue:
                self._proactive_queue.append(prompt)

    # ------------------------------------------------------------------
    # Heartbeat — runs autonomous cycles in background
    # ------------------------------------------------------------------

    def start_heartbeat(self, loop_controller: Any, microcosm: Any, interval: float = 45.0) -> None:
        if self._autonomous_mode:
            return  # Heartbeat suppressed in autonomous mode
        self._heartbeat_interval = interval
        self._heartbeat_stop.clear()
        self._microcosm = microcosm

        def _tick() -> None:
            while not self._heartbeat_stop.wait(self._heartbeat_interval):
                try:
                    self.derive_all(
                        loop_controller=loop_controller,
                        conversation_history=getattr(microcosm, "conversation_history", []),
                        known_projects=getattr(microcosm, "known_projects", []),
                        environment=getattr(microcosm, "environment", {}),
                    )
                    result = self.run_autonomous_cycle(microcosm)
                    if result:
                        self._log_to_purple(loop_controller, result)
                    self._maybe_queue_proactive()
                except Exception:
                    pass

        self._heartbeat_thread = threading.Thread(target=_tick, name="purple_goal_heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1.0)
        self._heartbeat_thread = None
