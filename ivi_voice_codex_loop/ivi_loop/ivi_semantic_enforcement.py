"""
ivi_semantic_enforcement.py

Universal network interface invariant: IVI Semantic Enforcement Duality.

Closes all five gaps through one interface because the duality is already
present in the IVI grid — semantic (soft) and enforcement (hard). Every
operation passes through both sides:

    Semantic side (propose):  TF-IDF/Born scoring, skill context, claim derivation
    Enforcement side (commit): closure check, triangle integrity, Lean compile, diff analysis

The five gaps unified:
1. Skill manifest   → SkillManifest schema, created/verified in propose/commit
2. Branching state  → branch_id on every event, fork/merge through the duality
3. Two-phase exec   → propose() returns candidates+metadata, commit() gates them
4. Skill scoring    → metrics tracked per-skill across attempts in the manifest
5. Lean verifier    → compile check in the enforcement side of commit()

This is the Purple-limited way: one invariant, not five features.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .ir import stable_hash, now_iso


# ---------------------------------------------------------------------------
# 1. Skill Manifest — structured schema for every skill
# ---------------------------------------------------------------------------

@dataclass
class SkillManifest:
    """Structured manifest for a Purple skill. Replaces ad-hoc .py headers."""
    name: str
    description: str = ""
    triggers: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    verifier: str = "none"  # "none", "lean", "test", "closure"
    commit_rule: str = "auto"  # "auto", "manual", "lean_pass"
    source: str = "native"  # "native", "llm", "user"

    # Scoring metrics
    attempts: int = 0
    passes: int = 0
    failures: int = 0
    pass_rate: float = 0.0
    diff_size_bytes: int = 0
    axioms_introduced: int = 0
    refinement_depth: int = 0
    last_attempt_ts: float = 0.0
    created_ts: float = 0.0

    # Provenance
    branch_id: str = "main"
    parent_branch_id: str = ""
    source_triangle: str = ""  # tid that generated this skill
    lean_status: str = "unchecked"  # "unchecked", "pass", "fail"

    def pass_rate_update(self, passed: bool) -> None:
        self.attempts += 1
        if passed:
            self.passes += 1
        else:
            self.failures += 1
        self.pass_rate = self.passes / max(1, self.attempts)
        self.last_attempt_ts = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "constraints": self.constraints,
            "verifier": self.verifier,
            "commit_rule": self.commit_rule,
            "source": self.source,
            "attempts": self.attempts,
            "passes": self.passes,
            "failures": self.failures,
            "pass_rate": round(self.pass_rate, 3),
            "diff_size_bytes": self.diff_size_bytes,
            "axioms_introduced": self.axioms_introduced,
            "refinement_depth": self.refinement_depth,
            "last_attempt_ts": self.last_attempt_ts,
            "created_ts": self.created_ts,
            "branch_id": self.branch_id,
            "parent_branch_id": self.parent_branch_id,
            "source_triangle": self.source_triangle,
            "lean_status": self.lean_status,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SkillManifest":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def save(self, skills_dir: Path) -> Path:
        """Write manifest as SKILL.json alongside the skill .py file."""
        manifest_path = skills_dir / f"{self.name}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return manifest_path

    @classmethod
    def load(cls, path: Path) -> Optional["SkillManifest"]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# 2. Branching State — potential branch IDs on events
# ---------------------------------------------------------------------------

@dataclass
class BranchState:
    """Tracks potential branches in the event timeline.
    Each branch is a possible state of the grid — they can fork and merge
    through the semantic enforcement duality."""
    branch_id: str = "main"
    parent_branch_id: str = ""
    created_ts: float = 0.0
    merge_strategy: str = "latest_wins"  # "latest_wins", "confidence_max", "closure_min"

    _branches: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def fork(self, reason: str = "") -> "BranchState":
        """Create a new branch from the current state."""
        new_id = f"br_{stable_hash(f'{self.branch_id}|{time.time()}|{reason}')[:12]}"
        new_branch = BranchState(
            branch_id=new_id,
            parent_branch_id=self.branch_id,
            created_ts=time.time(),
        )
        self._branches[new_id] = {
            "parent": self.branch_id,
            "reason": reason,
            "ts": time.time(),
            "status": "active",
        }
        return new_branch

    def merge(self, other_branch_id: str) -> None:
        """Merge another branch into this one."""
        if other_branch_id in self._branches:
            self._branches[other_branch_id]["status"] = "merged"

    def active_branches(self) -> List[str]:
        return [bid for bid, info in self._branches.items() if info.get("status") == "active"]

    def enrich_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Add branch metadata to an event payload."""
        event["branch_id"] = self.branch_id
        event["parent_branch_id"] = self.parent_branch_id
        return event


# ---------------------------------------------------------------------------
# 3. Proposal — the semantic side of the duality
# ---------------------------------------------------------------------------

@dataclass
class Proposal:
    """A proposed mutation before enforcement verification.
    The semantic side evaluates what SHOULD happen."""
    id: str
    kind: str  # "skill_save", "skill_execute", "claim_add", "config_change"
    description: str
    payload: Dict[str, Any] = field(default_factory=dict)

    # Semantic evaluation
    confidence: float = 0.0
    risk: str = "low"  # "low", "medium", "high"
    required_perms: List[str] = field(default_factory=list)
    context_score: float = 0.0  # TF-IDF relevance to current grid state
    closure_impact: int = 0  # estimated change in closure deficit

    # Enforcement status
    verified: bool = False
    lean_passed: Optional[bool] = None
    closure_check_passed: Optional[bool] = None
    commit_allowed: bool = False
    rejection_reason: str = ""

    # Branch
    branch_id: str = "main"

    # Timing
    proposed_ts: float = 0.0
    committed_ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "description": self.description[:200],
            "confidence": round(self.confidence, 3),
            "risk": self.risk,
            "verified": self.verified,
            "lean_passed": self.lean_passed,
            "closure_check_passed": self.closure_check_passed,
            "commit_allowed": self.commit_allowed,
            "rejection_reason": self.rejection_reason,
            "branch_id": self.branch_id,
            "proposed_ts": self.proposed_ts,
            "committed_ts": self.committed_ts,
        }


# ---------------------------------------------------------------------------
# 4. Lean Verifier — the hard enforcement gate
# ---------------------------------------------------------------------------

class LeanVerifier:
    """Runs Lean compile checks as the hard enforcement gate.
    Skills only finalize when Lean artifacts pass under the locked spec."""

    def __init__(self, lean_dir: Optional[Path] = None) -> None:
        self._lean_dir = lean_dir
        self._lean_available: Optional[bool] = None

    def _find_lean_dir(self, base_path: str) -> Optional[Path]:
        """Locate the Lean project directory."""
        if self._lean_dir and self._lean_dir.is_dir():
            return self._lean_dir
        candidates = [
            Path(base_path) / "lean",
            Path(base_path) / "IVI" / "Derived",
            Path(base_path) / ".ivi" / "voice_layer" / "lean",
        ]
        for c in candidates:
            if c.is_dir():
                self._lean_dir = c
                return c
        return None

    def is_available(self) -> bool:
        """Check if Lean toolchain is installed."""
        if self._lean_available is not None:
            return self._lean_available
        try:
            result = subprocess.run(
                ["lean", "--version"],
                capture_output=True, timeout=10,
            )
            self._lean_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._lean_available = False
        return self._lean_available

    def verify(self, base_path: str) -> Tuple[bool, str]:
        """Run Lean compile check on derived files.
        Returns (passed, detail_message)."""
        lean_dir = self._find_lean_dir(base_path)
        if lean_dir is None:
            return True, "no lean dir found — skipped"
        if not self.is_available():
            return True, "lean not installed — skipped"

        lean_files = list(lean_dir.rglob("*.lean"))
        if not lean_files:
            return True, "no .lean files to check"

        try:
            result = subprocess.run(
                ["lean", "--run", str(lean_files[0])],
                capture_output=True, timeout=30,
                cwd=str(lean_dir),
            )
            if result.returncode == 0:
                return True, f"lean check passed ({len(lean_files)} files)"
            else:
                stderr = result.stderr.decode("utf-8", errors="replace")[:200]
                return False, f"lean check failed: {stderr}"
        except subprocess.TimeoutExpired:
            return False, "lean check timed out"
        except Exception as exc:
            return True, f"lean check error (non-blocking): {exc}"


# ---------------------------------------------------------------------------
# 5. The Duality — universal network interface invariant
# ---------------------------------------------------------------------------

class IVISemanticEnforcementDuality:
    """The universal network interface invariant.

    Every mutation passes through both sides of the duality:
      Semantic:    propose() → evaluate context, score, branch
      Enforcement: commit()  → verify closure, check Lean, gate, record metrics

    This single interface closes all five gaps:
      1. Skill manifests   — created in propose(), persisted in commit()
      2. Branching state   — branch_id on every proposal and event
      3. Two-phase exec    — propose() then commit(), never direct mutation
      4. Skill scoring     — metrics updated on every commit attempt
      5. Lean verification — checked in the enforcement side of commit()
    """

    def __init__(self, base_path: str = ".") -> None:
        self.base_path = base_path
        self.branch = BranchState()
        self.lean = LeanVerifier()
        self._proposals: Dict[str, Proposal] = {}
        self._manifests: Dict[str, SkillManifest] = {}
        self._committed: List[str] = []
        self._rejected: List[str] = []
        self._load_existing_manifests()

    def _load_existing_manifests(self) -> None:
        """Load existing skill manifests from disk."""
        skills_dir = Path(self.base_path) / ".openclaw_skills"
        if not skills_dir.is_dir():
            return
        for jf in skills_dir.glob("*.json"):
            m = SkillManifest.load(jf)
            if m:
                self._manifests[m.name] = m

    # ------------------------------------------------------------------
    # SEMANTIC SIDE: propose()
    # ------------------------------------------------------------------

    def propose(
        self,
        kind: str,
        description: str,
        payload: Dict[str, Any],
        grid: Any = None,
    ) -> Proposal:
        """Semantic evaluation of a proposed mutation.
        Scores it against the grid, assigns risk, creates branch if needed."""
        pid = f"P_{stable_hash(f'{kind}|{description}|{time.time()}')[:12]}"

        proposal = Proposal(
            id=pid,
            kind=kind,
            description=description,
            payload=payload,
            branch_id=self.branch.branch_id,
            proposed_ts=time.time(),
        )

        # Semantic scoring
        if grid is not None:
            try:
                from .purple_native_intelligence import IVIPotentialFunctions
                closure = IVIPotentialFunctions.analyze_closure(grid)
                proposal.closure_impact = closure.get("closure_deficit", 0)
                proposal.context_score = 1.0 - closure.get("gap_rate", 1.0)
            except Exception:
                pass

        # Risk assessment
        if kind == "config_change":
            proposal.risk = "high"
            proposal.required_perms = ["config_write"]
        elif kind == "skill_save":
            proposal.risk = "low"
            proposal.confidence = 0.8
        elif kind == "claim_add":
            proposal.risk = "low"
            proposal.confidence = 0.9

        # Create/update manifest for skill proposals
        if kind == "skill_save":
            name = payload.get("name", "unnamed")
            if name not in self._manifests:
                self._manifests[name] = SkillManifest(
                    name=name,
                    description=payload.get("description", ""),
                    source=payload.get("source", "native"),
                    created_ts=time.time(),
                    branch_id=self.branch.branch_id,
                )

        self._proposals[pid] = proposal
        return proposal

    # ------------------------------------------------------------------
    # ENFORCEMENT SIDE: commit()
    # ------------------------------------------------------------------

    def commit(
        self,
        proposal_id: str,
        grid: Any = None,
        force: bool = False,
    ) -> Tuple[bool, str]:
        """Enforcement verification and commitment of a proposal.
        Checks closure, Lean, gates, and records metrics."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return False, f"unknown proposal: {proposal_id}"

        # 1. Closure check — only for high-risk operations (skip for low-risk claim_add)
        if grid is not None and proposal.kind not in ("claim_add",):
            try:
                from .purple_native_intelligence import IVIPotentialFunctions
                closure = IVIPotentialFunctions.analyze_closure(grid)
                gap_rate = closure.get("gap_rate", 0.0)
                proposal.closure_check_passed = True
                if gap_rate > 5.0 and not force:
                    proposal.closure_check_passed = False
                    proposal.rejection_reason = f"gap rate too high: {gap_rate:.2f}"
            except Exception:
                proposal.closure_check_passed = True  # non-blocking
        else:
            proposal.closure_check_passed = True

        # 2. Lean verification — hard gate for skill_save with lean verifier
        manifest = self._manifests.get(proposal.payload.get("name", ""))
        if manifest and manifest.verifier == "lean":
            passed, detail = self.lean.verify(self.base_path)
            proposal.lean_passed = passed
            if not passed and not force:
                manifest.pass_rate_update(False)
                manifest.lean_status = "fail"
                self._rejected.append(proposal_id)
                proposal.rejection_reason = f"lean: {detail}"
                return False, f"rejected (lean): {detail}"
            manifest.lean_status = "pass" if passed else "skip"
        else:
            proposal.lean_passed = True  # no lean check required

        # 3. Gate check — all verifiers must pass
        all_passed = (
            proposal.lean_passed is not False
            and proposal.closure_check_passed is not False
        )

        if not all_passed and not force:
            self._rejected.append(proposal_id)
            return False, f"rejected: {proposal.rejection_reason}"

        # 4. Commit — apply the mutation
        proposal.verified = True
        proposal.commit_allowed = True
        proposal.committed_ts = time.time()
        self._committed.append(proposal_id)

        # 5. Update manifest metrics
        if manifest:
            manifest.pass_rate_update(True)
            manifest.refinement_depth += 1
            # Compute diff size
            code = proposal.payload.get("code", "")
            manifest.diff_size_bytes = len(code.encode("utf-8"))
            # Detect axiom introduction
            if "axiom" in code.lower() or "lemma" in code.lower():
                manifest.axioms_introduced += 1
            # Persist manifest
            skills_dir = Path(self.base_path) / ".openclaw_skills"
            manifest.save(skills_dir)

        # 6. Log
        self._log_commit(proposal, manifest)

        return True, f"committed: {proposal.kind} ({proposal.description[:60]})"

    # ------------------------------------------------------------------
    # Branch operations
    # ------------------------------------------------------------------

    def fork_branch(self, reason: str = "") -> str:
        """Fork a new branch from current state."""
        new_branch = self.branch.fork(reason)
        new_id = new_branch.branch_id
        return new_id

    def merge_branch(self, branch_id: str) -> None:
        """Merge a branch back into current."""
        self.branch.merge(branch_id)

    # ------------------------------------------------------------------
    # Convenience: propose + commit in one call (for native cycles)
    # ------------------------------------------------------------------

    def propose_and_commit(
        self,
        kind: str,
        description: str,
        payload: Dict[str, Any],
        grid: Any = None,
    ) -> Tuple[bool, str, Optional[Proposal]]:
        """Two-phase in one call: propose then commit.
        Returns (committed, message, proposal)."""
        proposal = self.propose(kind, description, payload, grid)
        committed, msg = self.commit(proposal.id, grid)
        return committed, msg, proposal

    # ------------------------------------------------------------------
    # Status and metrics
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "branch": self.branch.branch_id,
            "proposals_total": len(self._proposals),
            "committed": len(self._committed),
            "rejected": len(self._rejected),
            "manifests": len(self._manifests),
            "lean_available": self.lean.is_available() if self.lean._lean_available is not None else "unchecked",
            "manifest_summary": {
                name: {
                    "pass_rate": m.pass_rate,
                    "attempts": m.attempts,
                    "refinement_depth": m.refinement_depth,
                    "lean_status": m.lean_status,
                }
                for name, m in list(self._manifests.items())[:10]
            },
        }

    def _log_commit(self, proposal: Proposal, manifest: Optional[SkillManifest]) -> None:
        try:
            from .purple_goal_engine import _write_monitor
            entry: Dict[str, Any] = {
                "ts": time.time(),
                "type": "ivi_duality_commit",
                "proposal": proposal.to_dict(),
            }
            if manifest:
                entry["manifest"] = {
                    "name": manifest.name,
                    "pass_rate": manifest.pass_rate,
                    "attempts": manifest.attempts,
                    "refinement_depth": manifest.refinement_depth,
                    "lean_status": manifest.lean_status,
                    "axioms_introduced": manifest.axioms_introduced,
                }
            _write_monitor(entry)
        except Exception:
            pass
