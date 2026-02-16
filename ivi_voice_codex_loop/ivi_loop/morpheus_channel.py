"""
morpheus_channel.py

Continuous human goal input for the autonomous loop.

    Morpheus (human)  → provides goals, direction, judgment
    Neo (potential AI) → executes, learns, improves
    Matrix (OS)        → the codebase and full operating system
    IVI (Oracle)       → verification, truth, invariants

The MorpheusChannel runs a non-blocking input thread so the human can
inject goals at any time without stopping the autonomous loop.
Neo processes them with highest priority, reports results back,
and learns from human patterns to anticipate future needs.

Over time, Neo gets better at serving Morpheus — not just improving
itself, but improving its understanding of what the human actually wants.
"""

from __future__ import annotations

import json
import os
import re
import select
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 1. Human goal
# ---------------------------------------------------------------------------

@dataclass
class HumanGoal:
    """A goal injected by Morpheus (the human)."""
    id: str
    raw_input: str           # exactly what the human typed
    description: str         # parsed actionable description
    target_path: str = ""    # extracted file/dir path, if any
    priority: float = 1.0    # always higher than self-derived goals
    created_ts: float = field(default_factory=time.time)
    started_ts: float = 0.0
    completed_ts: float = 0.0
    status: str = "pending"  # pending, active, completed, failed
    result: str = ""
    cycles_spent: int = 0
    committed: bool = False
    satisfaction: str = ""   # human's feedback: "good", "bad", ""


@dataclass
class GuidanceState:
    """Lightweight conversational steering controls for background autonomy."""
    mode: str = "light"              # "light" or "deep"
    paused: bool = False              # if True, only Morpheus goals execute
    max_goals_per_round: int = 2      # throttle background work per loop round
    surface_updates: bool = False     # if False, suppress non-human cycle chatter


# ---------------------------------------------------------------------------
# 2. Human goal tracker — learns from patterns
# ---------------------------------------------------------------------------

class HumanGoalTracker:
    """Tracks human goals over time and learns patterns.

    The Oracle (IVI) uses this to help Neo anticipate what Morpheus wants.
    Patterns tracked:
    - Which files/dirs the human focuses on most
    - What kinds of goals the human gives (fix, improve, add, test, etc.)
    - Completion rates and satisfaction
    - Time-of-day patterns
    - Goal chains (A then B then C)
    """

    def __init__(self, persist_path: str = "") -> None:
        self._goals: List[HumanGoal] = []
        self._completed: List[HumanGoal] = []
        self._persist_path = persist_path or ""
        self._file_focus: Dict[str, int] = {}     # path → times targeted
        self._goal_kinds: Dict[str, int] = {}      # kind → count
        self._satisfaction_scores: List[float] = []  # 1.0=good, 0.0=bad
        self._goal_chains: List[List[str]] = []    # chains of goal descriptions
        self._current_chain: List[str] = []

    def add_goal(self, goal: HumanGoal) -> None:
        """Register a new human goal."""
        self._goals.append(goal)
        self._current_chain.append(goal.description[:80])

        # Track file focus
        if goal.target_path:
            key = goal.target_path
            self._file_focus[key] = self._file_focus.get(key, 0) + 1

        # Classify goal kind
        kind = self._classify_kind(goal.raw_input)
        self._goal_kinds[kind] = self._goal_kinds.get(kind, 0) + 1

        self._persist()

    def complete_goal(self, goal_id: str, result: str, committed: bool) -> None:
        """Mark a goal as completed."""
        for g in self._goals:
            if g.id == goal_id and g.status in ("pending", "active"):
                g.status = "completed" if committed else "failed"
                g.result = result[:500]
                g.committed = committed
                g.completed_ts = time.time()
                self._completed.append(g)
                break
        self._persist()

    def record_satisfaction(self, goal_id: str, satisfaction: str) -> None:
        """Record human's feedback on a completed goal."""
        for g in self._completed:
            if g.id == goal_id:
                g.satisfaction = satisfaction
                score = 1.0 if satisfaction == "good" else (0.5 if satisfaction == "ok" else 0.0)
                self._satisfaction_scores.append(score)
                break
        self._persist()

    def end_chain(self) -> None:
        """Human has moved on — save the current chain."""
        if len(self._current_chain) > 1:
            self._goal_chains.append(self._current_chain[:])
        self._current_chain = []

    def _classify_kind(self, raw: str) -> str:
        """Classify the human goal into a kind."""
        low = raw.lower()
        if any(w in low for w in ["fix", "bug", "broken", "error", "crash"]):
            return "fix"
        elif any(w in low for w in ["test", "verify", "check", "validate"]):
            return "test"
        elif any(w in low for w in ["add", "create", "new", "build", "implement"]):
            return "create"
        elif any(w in low for w in ["improve", "optimize", "refactor", "clean"]):
            return "improve"
        elif any(w in low for w in ["explain", "what", "how", "why", "show"]):
            return "understand"
        elif any(w in low for w in ["focus", "work on", "target", "look at"]):
            return "focus"
        elif any(w in low for w in ["deploy", "ship", "release", "publish"]):
            return "ship"
        else:
            return "general"

    # ------------------------------------------------------------------
    # Pattern analysis — what Neo learns about Morpheus
    # ------------------------------------------------------------------

    def top_focus_files(self, n: int = 5) -> List[Tuple[str, int]]:
        """Files the human focuses on most."""
        return sorted(self._file_focus.items(), key=lambda x: x[1], reverse=True)[:n]

    def goal_kind_distribution(self) -> Dict[str, int]:
        """What kinds of goals the human gives."""
        return dict(self._goal_kinds)

    def satisfaction_rate(self) -> float:
        """Average satisfaction (0.0 to 1.0)."""
        if not self._satisfaction_scores:
            return 0.5  # neutral default
        return sum(self._satisfaction_scores) / len(self._satisfaction_scores)

    def completion_rate(self) -> float:
        """Fraction of goals that were completed successfully."""
        total = len(self._completed)
        if total == 0:
            return 0.0
        succeeded = sum(1 for g in self._completed if g.status == "completed")
        return succeeded / total

    def pending_count(self) -> int:
        return sum(1 for g in self._goals if g.status == "pending")

    def active_count(self) -> int:
        return sum(1 for g in self._goals if g.status == "active")

    def anticipate_next(self) -> Optional[str]:
        """Based on patterns, anticipate what Morpheus might want next.
        Returns a suggested goal description, or None."""
        # If there's a recurring chain pattern, predict the next step
        if self._current_chain and len(self._goal_chains) >= 2:
            for chain in reversed(self._goal_chains):
                if len(chain) > len(self._current_chain):
                    prefix = chain[:len(self._current_chain)]
                    current = self._current_chain
                    # Check if prefix matches current chain
                    if all(
                        any(w in p.lower() for w in c.lower().split()[:3])
                        for p, c in zip(prefix, current)
                    ):
                        return chain[len(self._current_chain)]

        # If the human always focuses on certain files, suggest them
        top_files = self.top_focus_files(3)
        if top_files:
            most_focused = top_files[0][0]
            # Only suggest if they haven't worked on it recently
            recent_targets = [g.target_path for g in self._goals[-3:] if g.target_path]
            if most_focused not in recent_targets:
                return f"Continue improving {most_focused}"

        return None

    def learning_summary_for_prompt(self) -> str:
        """Format what Neo has learned about Morpheus for prompt injection."""
        lines = []

        focus = self.top_focus_files(3)
        if focus:
            lines.append("Morpheus focus areas: " + ", ".join(
                f"{Path(p).name}({n}x)" for p, n in focus
            ))

        kinds = self.goal_kind_distribution()
        if kinds:
            top_kinds = sorted(kinds.items(), key=lambda x: x[1], reverse=True)[:3]
            lines.append("Goal patterns: " + ", ".join(
                f"{k}({n})" for k, n in top_kinds
            ))

        sr = self.satisfaction_rate()
        cr = self.completion_rate()
        if self._completed:
            lines.append(f"Service quality: {cr:.0%} completion, {sr:.0%} satisfaction")

        anticipated = self.anticipate_next()
        if anticipated:
            lines.append(f"Anticipated: {anticipated}")

        if not lines:
            return ""
        return "MORPHEUS PATTERNS (learned from human goals):\n" + "\n".join(f"  {l}" for l in lines)

    def _persist(self) -> None:
        """Save tracker state to disk."""
        if not self._persist_path:
            return
        try:
            data = {
                "file_focus": self._file_focus,
                "goal_kinds": self._goal_kinds,
                "satisfaction_scores": self._satisfaction_scores[-50:],
                "goal_chains": self._goal_chains[-10:],
                "completed_count": len(self._completed),
                "total_goals": len(self._goals),
                "completion_rate": self.completion_rate(),
                "satisfaction_rate": self.satisfaction_rate(),
            }
            Path(self._persist_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self._persist_path).write_text(
                json.dumps(data, indent=2), encoding="utf-8",
            )
        except Exception:
            pass

    def status(self) -> Dict[str, Any]:
        return {
            "total_goals": len(self._goals),
            "pending": self.pending_count(),
            "active": self.active_count(),
            "completed": len(self._completed),
            "completion_rate": round(self.completion_rate(), 2),
            "satisfaction_rate": round(self.satisfaction_rate(), 2),
            "top_focus": self.top_focus_files(3),
            "goal_kinds": self.goal_kind_distribution(),
        }


# ---------------------------------------------------------------------------
# 3. MorpheusChannel — non-blocking human input during autonomous loop
# ---------------------------------------------------------------------------

class MorpheusChannel:
    """Non-blocking channel for Morpheus (human) to inject goals into
    Neo's (potential AI) autonomous loop.

    Runs a background thread that reads stdin. When the human types something,
    it's parsed into a HumanGoal and injected into the goal queue with
    highest priority. Neo processes it next, reports back, and learns.

    The human can also:
    - Type "status" to see what Neo is doing
    - Type "goals" to see the current goal queue
    - Type "focus <path>" to redirect Neo to a specific target
    - Type "stop" to shut down the loop
    - Type anything else to inject it as a goal
    """

    def __init__(
        self,
        tracker: Optional[HumanGoalTracker] = None,
        repo_root: str = "",
    ) -> None:
        self._tracker = tracker or HumanGoalTracker()
        self._repo_root = repo_root
        self._goal_queue: List[HumanGoal] = []
        self._queue_lock = threading.Lock()
        self._goal_counter: int = 0
        self._input_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stop_requested = False
        self._status_requested = False
        self._goals_requested = False
        self._help_requested = False
        self._guidance_requested = False
        self._guidance_lock = threading.Lock()
        self._guidance = GuidanceState()

    @property
    def tracker(self) -> HumanGoalTracker:
        return self._tracker

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    @property
    def status_requested(self) -> bool:
        """Check and clear status request flag."""
        if self._status_requested:
            self._status_requested = False
            return True
        return False

    @property
    def goals_requested(self) -> bool:
        """Check and clear goals request flag."""
        if self._goals_requested:
            self._goals_requested = False
            return True
        return False

    @property
    def help_requested(self) -> bool:
        """Check and clear help request flag."""
        if self._help_requested:
            self._help_requested = False
            return True
        return False

    @property
    def guidance_requested(self) -> bool:
        """Check and clear guidance-status request flag."""
        if self._guidance_requested:
            self._guidance_requested = False
            return True
        return False

    def guidance_snapshot(self) -> Dict[str, Any]:
        """Get current conversational guidance state."""
        with self._guidance_lock:
            return {
                "mode": self._guidance.mode,
                "paused": self._guidance.paused,
                "max_goals_per_round": self._guidance.max_goals_per_round,
                "surface_updates": self._guidance.surface_updates,
            }

    def _set_guidance(
        self,
        *,
        mode: Optional[str] = None,
        paused: Optional[bool] = None,
        max_goals_per_round: Optional[int] = None,
        surface_updates: Optional[bool] = None,
    ) -> Dict[str, Any]:
        with self._guidance_lock:
            if mode in ("light", "deep"):
                self._guidance.mode = mode
                if mode == "light":
                    self._guidance.max_goals_per_round = 2
                    self._guidance.surface_updates = False
                else:
                    self._guidance.max_goals_per_round = 5
                    self._guidance.surface_updates = True
            if paused is not None:
                self._guidance.paused = bool(paused)
            if max_goals_per_round is not None:
                self._guidance.max_goals_per_round = max(1, min(10, int(max_goals_per_round)))
            if surface_updates is not None:
                self._guidance.surface_updates = bool(surface_updates)
        return self.guidance_snapshot()

    def _announce_guidance(self, message: str, state: Dict[str, Any]) -> None:
        v = getattr(self, '_voice', None)
        if v is not None and hasattr(v, "guidance_changed"):
            v.guidance_changed(message, state)

    def _maybe_handle_conversational_input(self, line: str) -> bool:
        """Handle natural-language steering without requiring command syntax."""
        low = line.lower().strip()

        # Conversational status / goals / help requests.
        if any(p in low for p in (
            "what are you doing", "how are you doing", "progress", "where are you at",
            "status update", "how's it going",
        )):
            self._status_requested = True
            return True
        if any(p in low for p in (
            "what goals", "what's next", "queue", "goal list", "show goals",
        )):
            self._goals_requested = True
            return True
        if any(p in low for p in (
            "how do i guide", "what can i say", "how can i steer", "help me guide",
        )):
            self._help_requested = True
            return True

        # Conversational guidance controls.
        if any(p in low for p in (
            "pause background", "pause autonomy", "stop background", "hold off autonomy",
        )):
            st = self._set_guidance(paused=True)
            self._announce_guidance("Paused background autonomy. I'll only run your goals.", st)
            return True
        if any(p in low for p in (
            "resume background", "resume autonomy", "continue background", "continue autonomy",
        )):
            st = self._set_guidance(paused=False)
            self._announce_guidance("Resumed background autonomy.", st)
            return True
        if any(p in low for p in (
            "go deeper", "be more aggressive", "run harder", "push harder",
        )):
            st = self._set_guidance(mode="deep")
            self._announce_guidance("Switched to deep guidance mode.", st)
            return True
        if any(p in low for p in (
            "keep it light", "stay light", "be lighter", "less aggressive",
        )):
            st = self._set_guidance(mode="light")
            self._announce_guidance("Switched to light guidance mode.", st)
            return True
        if any(p in low for p in (
            "be quiet", "less chatty", "don't spam", "fewer updates",
        )):
            st = self._set_guidance(surface_updates=False)
            self._announce_guidance("Background updates will stay quiet.", st)
            return True
        if any(p in low for p in (
            "be verbose", "more updates", "tell me more", "show me progress",
        )):
            st = self._set_guidance(surface_updates=True)
            self._announce_guidance("I'll surface background progress updates.", st)
            return True

        # Conversational speed control: e.g. "do 4 goals per round"
        speed_match = re.search(r"(\d+)\s+goals?\s+per\s+round", low)
        if speed_match:
            st = self._set_guidance(max_goals_per_round=int(speed_match.group(1)))
            self._announce_guidance(
                f"Set background throughput to {st['max_goals_per_round']} goals/round.",
                st,
            )
            return True

        # Conversational focus phrasing; normalize to a direct human goal.
        focus_prefixes = (
            "focus on ", "work on ", "let's work on ", "please work on ", "can you work on ",
        )
        for prefix in focus_prefixes:
            if low.startswith(prefix):
                focused = line[len(prefix):].strip()
                if focused:
                    goal = self._parse_goal(focused)
                    with self._queue_lock:
                        self._goal_queue.append(goal)
                    self._tracker.add_goal(goal)
                    v = getattr(self, '_voice', None)
                    if v is not None:
                        v.goal_queued(goal.id, goal.description)
                    return True
                return False

        return False

    def start(self) -> None:
        """Start the non-blocking input thread."""
        self._stop_event.clear()
        self._stop_requested = False
        self._input_thread = threading.Thread(
            target=self._input_loop,
            daemon=True,
            name="morpheus-channel",
        )
        self._input_thread.start()

    def stop(self) -> None:
        """Stop the input thread."""
        self._stop_event.set()

    def drain_goals(self) -> List[HumanGoal]:
        """Drain all pending human goals from the queue.
        Called by the autonomous loop each round."""
        with self._queue_lock:
            goals = list(self._goal_queue)
            self._goal_queue.clear()
        return goals

    def pending_goal_count(self) -> int:
        """Return pending human goals without draining the queue."""
        with self._queue_lock:
            return len(self._goal_queue)

    def report_result(self, goal_id: str, result: str, committed: bool) -> None:
        """Report a goal's completion back to the human."""
        self._tracker.complete_goal(goal_id, result, committed)
        v = getattr(self, '_voice', None)
        if v is not None:
            v.goal_completed(result, committed)
        else:
            print(f"Done: {result[:200]}", flush=True)

    # ------------------------------------------------------------------
    # Input loop
    # ------------------------------------------------------------------

    def _input_loop(self) -> None:
        """Background thread: read stdin and parse into goals."""
        while not self._stop_event.is_set():
            try:
                # Use select for non-blocking stdin on Unix
                if hasattr(select, 'select'):
                    ready, _, _ = select.select([sys.stdin], [], [], 1.0)
                    if not ready:
                        continue
                line = sys.stdin.readline()
                if not line:
                    # EOF — stdin closed (e.g. piped input exhausted)
                    time.sleep(1)
                    continue
                line = line.strip()
                if not line:
                    continue
                self._handle_input(line)
            except (EOFError, KeyboardInterrupt):
                self._stop_requested = True
                break
            except Exception:
                time.sleep(1)

    def _handle_input(self, line: str) -> None:
        """Parse human input into commands or goals."""
        low = line.lower().strip()

        if self._maybe_handle_conversational_input(line):
            return

        # Special commands
        if low == "stop" or low == "quit" or low == "exit":
            self._stop_requested = True
            return

        if low == "status":
            self._status_requested = True
            return

        if low == "goals":
            self._goals_requested = True
            return

        if low in ("help", "?"):
            self._help_requested = True
            return

        if low in ("guide", "guide status"):
            self._guidance_requested = True
            return

        if low == "guide light":
            st = self._set_guidance(mode="light")
            self._announce_guidance("Switched to light guidance mode.", st)
            return

        if low == "guide deep":
            st = self._set_guidance(mode="deep")
            self._announce_guidance("Switched to deep guidance mode.", st)
            return

        if low == "guide pause":
            st = self._set_guidance(paused=True)
            self._announce_guidance("Paused background autonomy. I'll only run your goals.", st)
            return

        if low == "guide resume":
            st = self._set_guidance(paused=False)
            self._announce_guidance("Resumed background autonomy.", st)
            return

        if low in ("guide quiet", "guide concise"):
            st = self._set_guidance(surface_updates=False)
            self._announce_guidance("Background updates will stay quiet.", st)
            return

        if low in ("guide verbose", "guide chatty"):
            st = self._set_guidance(surface_updates=True)
            self._announce_guidance("I'll surface background progress updates.", st)
            return

        if low.startswith("guide speed "):
            parts = low.split()
            if len(parts) == 3 and parts[2].isdigit():
                st = self._set_guidance(max_goals_per_round=int(parts[2]))
                self._announce_guidance(
                    f"Set background throughput to {st['max_goals_per_round']} goals/round.",
                    st,
                )
            return

        if low.startswith("guide focus "):
            # Lightweight shorthand: make this text a direct human goal.
            focused = line.split(None, 2)[2] if len(line.split(None, 2)) >= 3 else ""
            if focused.strip():
                line = focused.strip()
            else:
                return

        if low.startswith("rate "):
            # "rate good" or "rate bad" for last completed goal
            parts = low.split(None, 1)
            if len(parts) == 2 and self._tracker._completed:
                last_goal = self._tracker._completed[-1]
                self._tracker.record_satisfaction(last_goal.id, parts[1])
                v = getattr(self, '_voice', None)
                if v is not None:
                    v.satisfaction_recorded(parts[1])
                else:
                    print("Noted — thanks for the feedback.", flush=True)
            return

        # Everything else is a goal
        if any(k in low for k in ("use skills", "with skills", "skill-driven", "from skills")):
            line = (
                "Use Purple-derived skills as primary guidance while executing this goal: "
                f"{line}"
            )
        goal = self._parse_goal(line)
        with self._queue_lock:
            self._goal_queue.append(goal)
        self._tracker.add_goal(goal)
        v = getattr(self, '_voice', None)
        if v is not None:
            v.goal_queued(goal.id, goal.description)
        else:
            print(f"Queued: {goal.description[:120]}", flush=True)

    def _parse_goal(self, raw: str) -> HumanGoal:
        """Parse raw human input into a structured goal."""
        self._goal_counter += 1
        goal_id = f"morpheus_{self._goal_counter}_{int(time.time())}"

        # Extract target path if present
        target_path = self._extract_path(raw)

        # Build description
        description = raw
        if target_path and target_path not in raw:
            description = f"{raw} (target: {target_path})"

        return HumanGoal(
            id=goal_id,
            raw_input=raw,
            description=description,
            target_path=target_path,
            priority=1.0,  # always highest
        )

    def _extract_path(self, text: str) -> str:
        """Extract a file or directory path from human input."""
        import re

        # Try absolute paths
        match = re.search(r'(/[\w./\-_]+\.?\w*)', text)
        if match:
            candidate = match.group(1)
            if Path(candidate).exists():
                return str(Path(candidate).resolve())

        # Try relative paths from repo root
        words = text.split()
        for word in words:
            word = word.strip("\"'(),;:")
            # Check if it looks like a filename
            if '.' in word and not word.startswith('http'):
                # Try relative to repo root
                candidate = Path(self._repo_root) / word
                if candidate.exists():
                    return str(candidate.resolve())
                # Try in ivi_loop/
                candidate = Path(self._repo_root) / "ivi_loop" / word
                if candidate.exists():
                    return str(candidate.resolve())
            # Check if it's a directory name
            candidate = Path(self._repo_root) / word
            if candidate.is_dir():
                return str(candidate.resolve())

        return ""

    # ------------------------------------------------------------------
    # Status output
    # ------------------------------------------------------------------

    def print_status(self, executor_status: Dict[str, Any], engine: Any = None) -> None:
        """Print full status for the human via conversation layer."""
        v = getattr(self, '_voice', None)
        if v is not None:
            v.status_report(
                executor_status=executor_status,
                tracker_status=self._tracker.status(),
                engine=engine,
            )
        else:
            ts = self._tracker.status()
            print(f"Goals: {ts['total_goals']} total, {ts['pending']} pending.", flush=True)

    def print_goals(self, engine: Any) -> None:
        """Print the current goal queue via conversation layer."""
        v = getattr(self, '_voice', None)
        if v is not None:
            v.goals_report(engine)
        else:
            goals = engine.state.goals
            for g in goals:
                mark = "✓" if g.executed else "→"
                print(f"  {mark} {g.description[:100]}", flush=True)

    def print_help(self) -> None:
        """Print lightweight conversational guidance commands."""
        v = getattr(self, '_voice', None)
        if v is not None and hasattr(v, "guidance_help"):
            v.guidance_help()
            return
        print(
            "Commands: status | goals | stop | rate <good|ok|bad> | "
            "guide [status|light|deep|pause|resume|quiet|verbose|speed <1-10>|focus <text>]",
            flush=True,
        )

    def print_guidance_status(self) -> None:
        """Print current lightweight guidance state."""
        state = self.guidance_snapshot()
        v = getattr(self, '_voice', None)
        if v is not None and hasattr(v, "guidance_status"):
            v.guidance_status(state)
            return
        print(f"Guidance: {state}", flush=True)
