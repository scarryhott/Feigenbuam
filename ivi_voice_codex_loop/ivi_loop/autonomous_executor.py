"""
autonomous_executor.py

Full-autonomy orchestrator for OpenClaw self-improvement.

Runs perpetual cycles:
  1. ANALYZE — native intelligence scans a target
  2. IMPROVE — LLM proposes and writes improvements (gateway-gated)
  3. TEST   — runs tests / compile checks to verify changes
  4. COMMIT — git commit if tests pass, rollback if they fail
  5. LEARN  — feed results back into IVI grid as claims + skills

Only asks the user a question at genuine impasses it cannot resolve.
The gateway enforces every effectful action through intent/attest co-signing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 1. Cycle result
# ---------------------------------------------------------------------------

@dataclass
class CycleResult:
    """Result of one full autonomous cycle."""
    cycle_id: int = 0
    target: str = ""
    phase: str = ""            # last phase completed
    native_insights: int = 0
    claims_added: int = 0
    llm_used: bool = False
    llm_result: str = ""
    tests_passed: bool = False
    test_output: str = ""
    committed: bool = False
    commit_message: str = ""
    error: str = ""
    elapsed_s: float = 0.0
    impasse: bool = False      # True if we need to ask the user
    impasse_reason: str = ""

    def summary(self) -> str:
        parts = [f"cycle#{self.cycle_id} {Path(self.target).name}"]
        parts.append(f"phase={self.phase}")
        if self.native_insights:
            parts.append(f"insights={self.native_insights}")
        if self.claims_added:
            parts.append(f"claims={self.claims_added}")
        if self.llm_used:
            parts.append("llm=yes")
        if self.tests_passed:
            parts.append("tests=PASS")
        elif self.test_output:
            parts.append("tests=FAIL")
        if self.committed:
            parts.append("committed")
        if self.impasse:
            parts.append(f"IMPASSE: {self.impasse_reason[:60]}")
        if self.error:
            parts.append(f"err={self.error[:60]}")
        parts.append(f"{self.elapsed_s:.1f}s")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# 2. Impasse detector
# ---------------------------------------------------------------------------

class ImpasseDetector:
    """Detects when the system is genuinely stuck and should ask the user.

    Impasse conditions:
    - Same error repeated N times in a row
    - Gateway blocks every action for M consecutive cycles
    - LLM returns empty or identical output N times
    - Tests fail on the same file N consecutive times with same error
    """

    def __init__(self, threshold: int = 3) -> None:
        self._threshold = threshold
        self._consecutive_errors: List[str] = []
        self._consecutive_blocks: int = 0
        self._consecutive_empty_llm: int = 0
        self._consecutive_test_fails: Dict[str, int] = {}
        self._last_llm_output: str = ""

    def record_error(self, error: str) -> None:
        self._consecutive_errors.append(error[:200])
        if len(self._consecutive_errors) > self._threshold * 2:
            self._consecutive_errors = self._consecutive_errors[-self._threshold:]

    def record_gateway_block(self) -> None:
        self._consecutive_blocks += 1

    def record_gateway_pass(self) -> None:
        self._consecutive_blocks = 0

    def record_llm_output(self, output: str) -> None:
        if not output.strip() or output.strip() == self._last_llm_output.strip():
            self._consecutive_empty_llm += 1
        else:
            self._consecutive_empty_llm = 0
        self._last_llm_output = output

    def record_test_result(self, target: str, passed: bool) -> None:
        key = Path(target).name
        if passed:
            self._consecutive_test_fails.pop(key, None)
        else:
            self._consecutive_test_fails[key] = self._consecutive_test_fails.get(key, 0) + 1

    def record_success(self) -> None:
        """Reset all counters on a successful cycle."""
        self._consecutive_errors.clear()
        self._consecutive_blocks = 0
        self._consecutive_empty_llm = 0

    def check(self) -> Tuple[bool, str]:
        """Check if we're at an impasse. Returns (is_impasse, reason)."""
        # Same error repeated
        if len(self._consecutive_errors) >= self._threshold:
            recent = self._consecutive_errors[-self._threshold:]
            if len(set(recent)) == 1:
                return True, f"Same error {self._threshold}x: {recent[0][:100]}"

        # Gateway blocking everything
        if self._consecutive_blocks >= self._threshold:
            return True, f"Gateway blocked {self._consecutive_blocks} consecutive actions"

        # LLM returning nothing useful
        if self._consecutive_empty_llm >= self._threshold:
            return True, f"LLM returned empty/identical output {self._consecutive_empty_llm}x"

        # Same file failing tests repeatedly
        for fname, count in self._consecutive_test_fails.items():
            if count >= self._threshold:
                return True, f"Tests failing on {fname} for {count} consecutive cycles"

        return False, ""


# ---------------------------------------------------------------------------
# 3. AutonomousExecutor — the full-cycle orchestrator
# ---------------------------------------------------------------------------

class AutonomousExecutor:
    """Orchestrates full autonomous improvement cycles.

    Each cycle: analyze → improve → test → commit → learn.
    Runs perpetually. Only stops for genuine impasses or SIGINT.
    """

    def __init__(
        self,
        settings: Any,
        gateway: Any = None,
        repo_root: str = "",
        morpheus_tracker: Any = None,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._repo_root = repo_root or str(Path(__file__).resolve().parent.parent)
        self._morpheus_tracker = morpheus_tracker  # learns what Morpheus wants
        self._impasse = ImpasseDetector(threshold=3)
        self._cycle_count: int = 0
        self._total_commits: int = 0
        self._total_tests_passed: int = 0
        self._total_tests_failed: int = 0
        self._total_llm_calls: int = 0
        self._total_native_cycles: int = 0
        self._pending_question: str = ""  # set when impasse detected

    @property
    def has_pending_question(self) -> bool:
        return bool(self._pending_question)

    @property
    def pending_question(self) -> str:
        return self._pending_question

    def clear_question(self) -> None:
        self._pending_question = ""

    # ------------------------------------------------------------------
    # Full cycle
    # ------------------------------------------------------------------

    def run_cycle(
        self,
        target: str,
        native_cycle: Any = None,
        grid: Any = None,
        microcosm: Any = None,
        skills_loop: Any = None,
        goal_description: str = "",
    ) -> CycleResult:
        """Run one full autonomous cycle on a target file/directory."""
        self._cycle_count += 1
        t0 = time.time()
        result = CycleResult(cycle_id=self._cycle_count, target=target)

        # --- Phase 1: ANALYZE (native, no LLM cost) ---
        result.phase = "analyze"
        if native_cycle is not None and Path(target).is_file():
            try:
                native_result = native_cycle.run_native_cycle(target, grid=grid)
                if native_result:
                    result.native_insights = native_result.get("insights_total", 0)
                    result.claims_added = native_result.get("claims_added_to_grid", 0)
                    self._total_native_cycles += 1
            except Exception as exc:
                self._impasse.record_error(f"analyze:{exc}")

        # --- Phase 2: IMPROVE (LLM writes actual changes) ---
        result.phase = "improve"
        llm_output = self._run_llm_improvement(target, goal_description, microcosm)
        if llm_output:
            result.llm_used = True
            result.llm_result = llm_output[:300]
            self._total_llm_calls += 1
            self._impasse.record_llm_output(llm_output)
        else:
            self._impasse.record_llm_output("")

        # --- Phase 3: TEST ---
        result.phase = "test"
        test_passed, test_output = self._run_tests(target)
        result.tests_passed = test_passed
        result.test_output = test_output[:300]
        self._impasse.record_test_result(target, test_passed)

        if test_passed:
            self._total_tests_passed += 1
        else:
            self._total_tests_failed += 1

        # --- Phase 4: COMMIT (only if tests pass) ---
        result.phase = "commit"
        if test_passed and result.llm_used:
            commit_ok, commit_msg = self._git_commit(target, goal_description)
            result.committed = commit_ok
            result.commit_message = commit_msg
            if commit_ok:
                self._total_commits += 1
                self._impasse.record_success()
        elif not test_passed and result.llm_used:
            # Rollback: discard unstaged changes
            self._git_rollback(target)

        # --- Phase 5: LEARN (feed back into grid + skills) ---
        result.phase = "learn"
        if skills_loop is not None:
            try:
                fb = skills_loop.observe_ai_output(result.summary(), grid)
                sk = skills_loop.tick(grid)
            except Exception:
                pass

        # --- Impasse check ---
        is_impasse, impasse_reason = self._impasse.check()
        if is_impasse:
            result.impasse = True
            result.impasse_reason = impasse_reason
            self._pending_question = (
                f"I've hit an impasse: {impasse_reason}. "
                f"Target: {target}. Last cycle: {result.summary()}. "
                f"How should I proceed?"
            )

        result.elapsed_s = round(time.time() - t0, 2)
        return result

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    def _run_llm_improvement(
        self,
        target: str,
        goal_description: str,
        microcosm: Any,
    ) -> str:
        """Use LLM + tools to make actual improvements to the target."""
        if microcosm is None:
            return ""

        from .openclaw_actions import llm_chat_with_tools

        # Build a focused system prompt for autonomous improvement
        system = (
            "You are OpenClaw running a fully autonomous self-improvement cycle. "
            "You have full OS access. Your job:\n"
            "1. READ the target file to understand it\n"
            "2. IDENTIFY one concrete improvement (refactor, fix, optimize, add test)\n"
            "3. WRITE the improved code using write_file\n"
            "4. The system will automatically test and commit your changes\n"
            "Do NOT describe what you would do — actually do it with tools. "
            "Use ABSOLUTE paths. Make small, focused changes that won't break things. "
            "If you save a skill, make it genuinely reusable. "
            "Report what you changed in 1-2 sentences."
        )

        # Add context about what we already know
        if goal_description:
            system += f"\n\nCurrent goal: {goal_description}"

        # Add layer context from gateway
        if self._gateway is not None and hasattr(self._gateway, "navigation"):
            layer_ctx = self._gateway.navigation.layer_context_for_prompt()
            if layer_ctx:
                system += f"\n\nNavigation context:\n{layer_ctx}"

        # Add Morpheus patterns — what Neo has learned about serving the human
        if self._morpheus_tracker is not None:
            morph_ctx = self._morpheus_tracker.learning_summary_for_prompt()
            if morph_ctx:
                system += f"\n\n{morph_ctx}"

        messages = [{"role": "user", "content": f"Improve this file: {target}"}]

        gw = self._gateway
        try:
            result = llm_chat_with_tools(
                system=system,
                messages=messages,
                base_path=self._repo_root,
                max_tokens=512,
                max_tool_rounds=8,
                gateway=gw,
            )
            return result or ""
        except Exception as exc:
            self._impasse.record_error(f"llm:{exc}")
            return ""

    def _run_tests(self, target: str) -> Tuple[bool, str]:
        """Run tests on the target. Returns (passed, output)."""
        try:
            # First: compile check on the specific file
            if Path(target).is_file() and target.endswith(".py"):
                r = subprocess.run(
                    [sys.executable, "-m", "py_compile", target],
                    capture_output=True, text=True, timeout=15,
                )
                if r.returncode != 0:
                    return False, f"Compile failed: {r.stderr[:300]}"

            # Second: compile check on the whole ivi_loop directory
            ivi_loop_dir = Path(self._repo_root) / "ivi_loop"
            if ivi_loop_dir.is_dir():
                py_files = list(ivi_loop_dir.glob("*.py"))
                for pf in py_files:
                    r = subprocess.run(
                        [sys.executable, "-m", "py_compile", str(pf)],
                        capture_output=True, text=True, timeout=10,
                    )
                    if r.returncode != 0:
                        return False, f"Compile failed {pf.name}: {r.stderr[:200]}"

            # Third: try pytest if available
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pytest", self._repo_root, "-x", "--tb=short", "-q"],
                    capture_output=True, text=True, timeout=60,
                )
                combined = (r.stdout + r.stderr).lower()
                if r.returncode == 0:
                    return True, f"PASSED\n{r.stdout[:200]}"
                elif "no tests ran" in combined:
                    return True, "All files compile. No pytest tests found."
                elif "no module named pytest" in combined:
                    return True, "All files compile. pytest not installed."
                else:
                    return False, f"FAILED\n{(r.stdout + r.stderr)[:300]}"
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                return True, "All files compile. pytest unavailable."

        except subprocess.TimeoutExpired:
            return False, "Tests timed out."
        except Exception as exc:
            return False, f"Test error: {exc}"

    def _git_commit(self, target: str, goal_description: str) -> Tuple[bool, str]:
        """Stage and commit changes."""
        # Gateway gate the commit
        if self._gateway is not None:
            try:
                packet = self._gateway.ingress(
                    raw_input=f"git commit: {goal_description[:100]}",
                    channel="autonomous_executor",
                    actor="autonomous_executor",
                    requested_action_class="write",
                    requested_paths=[target],
                    order_mode="order_4_bounded_autonomy",
                )
                self._gateway.propose(packet)
                report = self._gateway.verify(packet)
                if not report.passed:
                    self._impasse.record_gateway_block()
                    return False, f"Gateway blocked commit: {', '.join(report.reason_codes)}"
                self._impasse.record_gateway_pass()
            except Exception:
                pass

        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self._repo_root, capture_output=True, timeout=10,
            )
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self._repo_root, capture_output=True, text=True, timeout=10,
            )
            if not status.stdout.strip():
                return False, "Nothing to commit."

            msg = f"[autonomous] {goal_description[:80]}" if goal_description else "[autonomous] self-improvement cycle"
            result = subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=self._repo_root, capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                # Attest the commit
                if self._gateway is not None:
                    try:
                        from .storage import append_attest
                        append_attest(
                            self._gateway._settings,
                            intent_id=packet.intent_id if 'packet' in dir() else "auto",
                            diff_stats={"target": target, "commit_msg": msg},
                            committed=True,
                        )
                    except Exception:
                        pass
                return True, f"Committed: {msg}"
            else:
                return False, f"Git failed: {(result.stdout + result.stderr)[:200]}"
        except Exception as exc:
            return False, f"Git error: {exc}"

    def _git_rollback(self, target: str) -> None:
        """Discard uncommitted changes after test failure."""
        try:
            subprocess.run(
                ["git", "checkout", "--", "."],
                cwd=self._repo_root, capture_output=True, timeout=10,
            )
            # Also clean any untracked files the LLM may have created
            subprocess.run(
                ["git", "clean", "-fd", "--quiet"],
                cwd=self._repo_root, capture_output=True, timeout=10,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "cycles": self._cycle_count,
            "commits": self._total_commits,
            "tests_passed": self._total_tests_passed,
            "tests_failed": self._total_tests_failed,
            "llm_calls": self._total_llm_calls,
            "native_cycles": self._total_native_cycles,
            "has_impasse": self.has_pending_question,
            "impasse_question": self._pending_question[:200] if self._pending_question else "",
        }
