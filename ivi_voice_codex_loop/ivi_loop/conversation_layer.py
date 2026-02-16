"""
conversation_layer.py

Single communication channel for the autonomous loop.
Translates internal system events into natural conversational output.
No bracketed prefixes, no raw state dumps — just talk.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Optional


class ConversationLayer:
    """Translates system events into conversational messages.

    When an OpenClaw microcosm is provided, outputs are routed through the
    contextual_response pipeline so the dialogue stays dynamic. Otherwise this
    falls back to lightweight prints.
    """

    def __init__(self, quiet: bool = False, openclaw: Any | None = None) -> None:
        self._quiet = quiet
        self._history: List[str] = []
        self._last_said: float = 0.0
        self._suppressed: int = 0
        self._min_interval: float = 0.5  # don't talk faster than this
        self._openclaw = openclaw

    def say(self, message: str, utterance_kind: str = "status") -> None:
        """Say something to the human."""
        if self._quiet or not message.strip():
            return
        if self._openclaw_emit(message, utterance_kind):
            return
        # Deduplicate fallback prints
        if self._history and self._history[-1] == message:
            return
        self._history.append(message)
        if len(self._history) > 50:
            self._history = self._history[-25:]
        self._last_said = time.time()
        print(message, flush=True)

    def _openclaw_emit(self, message: str, utterance_kind: str) -> bool:
        oc = self._openclaw
        if oc is None or not hasattr(oc, "contextual_response"):
            return False
        prompt = (
            "Provide a concise conversational update for the human guiding you. "
            f"Treat this as a {utterance_kind} note: {message}"
        )
        try:
            reply = oc.contextual_response(prompt)
        except Exception:
            return False
        if not isinstance(reply, str) or not reply.strip():
            return False
        reply = reply.strip()
        try:
            oc.record_turn("assistant", reply)
        except Exception:
            pass
        print(reply, flush=True)
        return True

    def _quiet_note(self) -> None:
        """Track suppressed messages."""
        self._suppressed += 1

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def greeting(self) -> None:
        self.say(
            "I'm online. Tell me what you'd like me to work on, "
            "or I'll find improvements on my own.",
            utterance_kind="greeting",
        )

    def discovery_done(self, python_files: int, roots: int, runtimes: int) -> None:
        if python_files > 0:
            self.say(
                f"I can see {python_files} Python files across {roots} "
                f"project{'s' if roots != 1 else ''} on your system.",
                utterance_kind="discovery",
            )

    def navigation_ready(self, layers: int, ops: int) -> None:
        self._quiet_note()  # too internal to mention

    # ------------------------------------------------------------------
    # Human goals (Morpheus)
    # ------------------------------------------------------------------

    def goal_received(self, count: int) -> None:
        if count == 1:
            self.say("Got it — working on that now.", utterance_kind="goal_update")
        else:
            self.say(f"Got {count} goals — I'll handle them in order.", utterance_kind="goal_update")

    def goal_working(self, description: str) -> None:
        short = description[:120].rstrip(".")
        self.say(f"Working on: {short}", utterance_kind="goal_update")

    def goal_completed(self, result: str, committed: bool) -> None:
        short = result[:200].rstrip(".")
        if committed:
            self.say(f"Done and committed. {short}", utterance_kind="goal_update")
        else:
            self.say(f"Finished, but didn't commit. {short}", utterance_kind="goal_update")

    def goal_queued(self, goal_id: str, description: str) -> None:
        short = description[:120].rstrip(".")
        self.say(f"Queued: {short}", utterance_kind="goal_update")

    def guidance_changed(self, message: str, state: Dict[str, Any]) -> None:
        mode = state.get("mode", "light")
        paused = state.get("paused", False)
        max_goals = state.get("max_goals_per_round", 2)
        updates = "on" if state.get("surface_updates", False) else "off"
        self.say(
            f"{message}"
            f" Mode: {mode}, paused: {'yes' if paused else 'no'}, "
            f"background goals/round: {max_goals}, updates: {updates}."
        )

    def guidance_status(self, state: Dict[str, Any]) -> None:
        mode = state.get("mode", "light")
        paused = state.get("paused", False)
        max_goals = state.get("max_goals_per_round", 2)
        updates = "on" if state.get("surface_updates", False) else "off"
        self.say(
            f"Guidance is {mode}. "
            f"Background autonomy is {'paused' if paused else 'running'}. "
            f"Max background goals/round: {max_goals}. "
            f"Background updates: {updates}."
        )

    def guidance_help(self) -> None:
        self.say(
            "Guidance commands: 'guide status', 'guide light', 'guide deep', "
            "'guide pause', 'guide resume', 'guide quiet', 'guide verbose', "
            "'guide speed <1-10>', and 'guide focus <goal>'."
        )

    def satisfaction_recorded(self, rating: str) -> None:
        self.say(f"Noted — thanks for the feedback.", utterance_kind="goal_update")

    # ------------------------------------------------------------------
    # Impasse
    # ------------------------------------------------------------------

    def impasse_hit(self, question: str) -> None:
        self.say(f"I'm stuck — {question}\nWhat would you like me to do?", utterance_kind="impasse")

    def impasse_cleared(self) -> None:
        self.say("Thanks — that clears it up. Continuing.", utterance_kind="impasse")

    def impasse_skipped(self) -> None:
        self.say("No worries, I'll move on to something else.", utterance_kind="impasse")

    # ------------------------------------------------------------------
    # Cycle results
    # ------------------------------------------------------------------

    def cycle_result(self, summary: str, committed: bool, tests_passed: bool,
                     is_human_goal: bool) -> None:
        short = summary[:200].rstrip(".")
        if is_human_goal:
            if committed:
                self.say(f"Done — {short}", utterance_kind="goal_update")
            elif tests_passed:
                self.say(f"Improved but didn't commit: {short}", utterance_kind="goal_update")
            else:
                self.say(f"Tried but tests failed: {short}", utterance_kind="goal_update")
        else:
            # Self-improvement — be brief
            if committed:
                self.say(f"Self-improved: {short}", utterance_kind="goal_update")
            else:
                self._quiet_note()  # don't bother human with failed self-improvement

    # ------------------------------------------------------------------
    # Idle / triangle time
    # ------------------------------------------------------------------

    def idle(self, rounds: int, max_rounds: int) -> None:
        if rounds >= max_rounds:
            self.say("Nothing to do — scanning for new opportunities.", utterance_kind="status")
        # Otherwise stay quiet

    def anticipated(self, description: str) -> None:
        self.say(f"I think you might want me to {description.lower().rstrip('.')}", utterance_kind="status")

    def triangle_place_reached(self, closure: float) -> None:
        pct = int(closure * 100)
        self.say(f"Knowledge is {pct}% verified and stable. Waiting for something new.", utterance_kind="status")

    def new_triangles(self, count: int) -> None:
        if count >= 5:
            self.say(f"New knowledge forming — {count} new verifications.", utterance_kind="status")
        # Small ticks are silent

    def silence_generating(self) -> None:
        self._quiet_note()  # internal detail

    # ------------------------------------------------------------------
    # Status (when human asks)
    # ------------------------------------------------------------------

    def status_report(self, executor_status: Dict[str, Any],
                      tracker_status: Dict[str, Any],
                      tri_status: Optional[Dict[str, Any]] = None,
                      engine: Any = None) -> None:
        lines: List[str] = []

        cycles = executor_status.get("cycles", 0)
        commits = executor_status.get("commits", 0)
        tp = executor_status.get("tests_passed", 0)

        if cycles > 0:
            lines.append(f"I've run {cycles} cycle{'s' if cycles != 1 else ''}, "
                         f"committed {commits} change{'s' if commits != 1 else ''}, "
                         f"and passed {tp} test{'s' if tp != 1 else ''}.")

        total = tracker_status.get("total_goals", 0)
        pending = tracker_status.get("pending", 0)
        completion = tracker_status.get("completion_rate", 0)
        satisfaction = tracker_status.get("satisfaction_rate", 0)

        if total > 0:
            lines.append(f"You've given me {total} goal{'s' if total != 1 else ''} — "
                         f"{pending} still pending, "
                         f"{completion:.0%} completion rate"
                         + (f", {satisfaction:.0%} satisfaction." if satisfaction > 0 else "."))

        if tri_status:
            clock = tri_status.get("clock", {})
            space = tri_status.get("space", {})
            place = tri_status.get("place", {})
            tt = clock.get("triangle_time", 0)
            cl = space.get("closure", 0)
            in_place = place.get("in_place", False)
            if tt > 0:
                lines.append(f"Knowledge: {cl:.0%} verified across "
                             f"{space.get('regions', 0)} region{'s' if space.get('regions', 0) != 1 else ''}"
                             + (", stable." if in_place else ", still growing."))

        if engine is not None:
            goals = [g for g in engine.state.goals if not g.executed]
            if goals:
                lines.append(f"Next up ({len(goals)} queued):")
                for g in goals[:3]:
                    src = "your" if g.source == "morpheus" else "self"
                    lines.append(f"  — {g.description[:80]} ({src})")

        top_focus = tracker_status.get("top_focus", [])
        if top_focus:
            from pathlib import Path
            fnames = ", ".join(f"{Path(p).name}" for p, _ in top_focus[:3])
            lines.append(f"Your focus areas: {fnames}")

        anticipated = None
        if engine is not None:
            try:
                from .morpheus_channel import HumanGoalTracker
            except Exception:
                pass

        self.say("\n".join(lines) if lines else "All quiet — nothing to report.", utterance_kind="status")

    def goals_report(self, engine: Any) -> None:
        goals = engine.state.goals
        if not goals:
            self.say("No goals in the queue right now.", utterance_kind="status")
            return
        lines = ["Current goals:"]
        for g in goals:
            if g.executed:
                mark = "done"
            elif g.source == "morpheus":
                mark = "yours"
            else:
                mark = "self"
            lines.append(f"  {'✓' if g.executed else '→'} {g.description[:90]} ({mark})")
        self.say("\n".join(lines), utterance_kind="status")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown_report(self, cycle: int, exec_status: Dict[str, Any],
                        morph_status: Dict[str, Any],
                        tri_status: Optional[Dict[str, Any]] = None) -> None:
        parts: List[str] = []

        commits = exec_status.get("commits", 0)
        tp = exec_status.get("tests_passed", 0)
        parts.append(f"Shutting down after {cycle} cycle{'s' if cycle != 1 else ''}.")

        if commits:
            parts.append(f"Committed {commits} change{'s' if commits != 1 else ''}, "
                         f"passed {tp} test{'s' if tp != 1 else ''}.")

        total = morph_status.get("total_goals", 0)
        completed = morph_status.get("completed", 0)
        if total > 0:
            parts.append(f"Handled {completed}/{total} of your goals "
                         f"({morph_status.get('completion_rate', 0):.0%} completion).")

        if tri_status:
            cl = tri_status.get("space", {}).get("closure", 0)
            in_place = tri_status.get("place", {}).get("in_place", False)
            parts.append(f"Knowledge {cl:.0%} verified"
                         + (" and stable." if in_place else "."))

        self.say(" ".join(parts), utterance_kind="shutdown")

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------

    def error(self, message: str) -> None:
        self.say(f"Something went wrong: {message}", utterance_kind="error")
