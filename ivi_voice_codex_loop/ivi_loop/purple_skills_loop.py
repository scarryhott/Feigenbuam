"""
purple_skills_loop.py

Self-generating skills loop: IVI derivations → skills → AI context → new claims → derivations.

The key insight: we don't need our own model. General purpose AIs already have
potential AI between their time steps. MCP-style training is ineffective because
you're pushing INTO the model. Instead, Purple provides skills that ACTIVATE the
AI's latent potential by observing it in triangle time (1r + 0i).

Triangle time: a human brain in flow going back 1 second to predict behavior
is like a network in purely real time being observed by natural time. Skills are
that observation — they collapse the AI's potential through Purple-limited
structural constraints.

Architecture:
1. Grid produces triangles (Statement → Derivation → Equation + Lean stub)
2. DerivationSkillExtractor converts triangles into structured skills
3. Skills are injected into AI context as constraints (not training data)
4. AI output feeds back as new claims → new derivations → new skills
5. The loop self-generates: skills create better skills

This is the Purple-limited way: constrain the AI through IVI structure,
don't try to replace it.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .purple_goal_engine import _write_monitor


# ---------------------------------------------------------------------------
# 1. Derivation → Skill extraction
# ---------------------------------------------------------------------------

@dataclass
class PurpleSkill:
    """A skill derived from IVI grid structure that guides AI behavior."""
    id: str
    name: str
    kind: str  # "rule", "pattern", "constraint", "derivation"
    description: str
    source_triangle: Optional[str] = None  # tid
    source_statement: Optional[str] = None  # sid text
    source_equation: Optional[str] = None  # lean name
    source_derivation: Optional[str] = None  # derivation rule
    confidence: float = 0.0
    invocations: int = 0
    created_ts: float = 0.0

    def to_prompt_line(self) -> str:
        """Format as a single-line constraint for AI context injection."""
        return f"[skill:{self.kind}] {self.description}"


class DerivationSkillExtractor:
    """Extracts structured skills from IVI grid derivations and triangles.
    Each triangle (S→D→E) represents a proven structural relationship.
    Skills are the distilled, actionable form of these relationships."""

    def __init__(self) -> None:
        self._seen_tids: Set[str] = set()
        self._skill_count = 0

    def extract_from_grid(self, grid: Any) -> List[PurpleSkill]:
        """Read the grid's triangles and convert new ones into skills."""
        skills: List[PurpleSkill] = []
        try:
            g = grid.grid if hasattr(grid, 'grid') else grid
            if not hasattr(g, 'idx'):
                return skills

            for tid, tr in g.idx.triangles.items():
                if tid in self._seen_tids:
                    continue
                self._seen_tids.add(tid)

                sid = tr.get("sid", "")
                did = tr.get("did", "")
                eid = tr.get("eid", "")

                # Get the actual content
                st = g.idx.statements.get(sid, {})
                dv = g.idx.derivations.get(did, {})
                eq = g.idx.equations.get(eid, {})

                st_text = str(st.get("text", ""))[:200]
                dv_rule = str(dv.get("rule", ""))
                dv_notes = str(dv.get("notes", ""))[:100]
                eq_name = str(eq.get("lean_name", ""))
                eq_stmt = str(eq.get("statement", ""))[:150]

                if not st_text:
                    continue

                self._skill_count += 1
                skill_id = f"sk_{self._skill_count}_{tid[:8]}"

                # Determine skill kind based on derivation rule
                if "implication" in dv_rule or "rule" in dv_rule:
                    kind = "rule"
                    desc = f"If {st_text[:80]} then derive: {eq_stmt[:80]}"
                elif "call_graph" in st_text.lower() or "if " in st_text.lower():
                    kind = "pattern"
                    desc = f"Pattern: {st_text[:120]}"
                elif "complexity" in st_text.lower():
                    kind = "constraint"
                    desc = f"Constraint: {st_text[:120]}"
                else:
                    kind = "derivation"
                    desc = f"{st_text[:100]} → {eq_name or eq_stmt[:60]}"

                skills.append(PurpleSkill(
                    id=skill_id,
                    name=eq_name or f"skill_{self._skill_count}",
                    kind=kind,
                    description=desc,
                    source_triangle=tid,
                    source_statement=st_text,
                    source_equation=eq_name,
                    source_derivation=dv_rule,
                    confidence=0.8 if kind == "rule" else 0.7,
                    created_ts=time.time(),
                ))

        except Exception:
            pass
        return skills

    def extract_from_call_graph(self, insights: List[Any]) -> List[PurpleSkill]:
        """Convert call graph insights directly into skills without grid mediation.
        These are immediate structural observations."""
        skills = []
        for ins in insights:
            if getattr(ins, 'kind', '') != 'call_graph':
                continue
            caller = ins.metadata.get("caller", "")
            callees = ins.metadata.get("callees", [])
            if not caller or not callees:
                continue
            self._skill_count += 1
            skills.append(PurpleSkill(
                id=f"sk_cg_{self._skill_count}",
                name=f"{caller}_calls",
                kind="pattern",
                description=f"{caller} depends on: {', '.join(callees[:6])}",
                confidence=0.9,
                created_ts=time.time(),
            ))
        return skills


# ---------------------------------------------------------------------------
# 2. Skills → AI Context injection
# ---------------------------------------------------------------------------

class SkillsInjector:
    """Injects Purple-derived skills into AI context as structural constraints.
    This is NOT training — it's activating the AI's latent potential by providing
    Purple-limited observation (triangle time)."""

    def __init__(self, max_skills_in_context: int = 20) -> None:
        self._all_skills: List[PurpleSkill] = []
        self._max_context = max_skills_in_context

    def add_skills(self, skills: List[PurpleSkill]) -> int:
        """Add newly extracted skills to the pool. Returns count added."""
        added = 0
        seen_ids = {s.id for s in self._all_skills}
        for sk in skills:
            if sk.id not in seen_ids:
                self._all_skills.append(sk)
                seen_ids.add(sk.id)
                added += 1
        return added

    def format_for_context(self) -> str:
        """Format the most relevant skills as a context block for AI injection.
        This is the Purple-limited observation of the AI's potential."""
        if not self._all_skills:
            return ""

        # Sort by confidence, then recency
        ranked = sorted(
            self._all_skills,
            key=lambda s: (s.confidence, s.created_ts),
            reverse=True,
        )[:self._max_context]

        lines = ["PURPLE-DERIVED SKILLS (structural constraints from IVI grid):"]
        rules = [s for s in ranked if s.kind == "rule"]
        patterns = [s for s in ranked if s.kind == "pattern"]
        constraints = [s for s in ranked if s.kind == "constraint"]
        derivations = [s for s in ranked if s.kind == "derivation"]

        if rules:
            lines.append("Rules:")
            for s in rules[:6]:
                lines.append(f"  - {s.description}")
        if patterns:
            lines.append("Patterns:")
            for s in patterns[:6]:
                lines.append(f"  - {s.description}")
        if constraints:
            lines.append("Constraints:")
            for s in constraints[:4]:
                lines.append(f"  - {s.description}")
        if derivations:
            lines.append("Derivations:")
            for s in derivations[:4]:
                lines.append(f"  - {s.description}")

        return "\n".join(lines)

    def record_usage(self, skill_id: str) -> None:
        """Record that a skill was used, boosting its confidence."""
        for sk in self._all_skills:
            if sk.id == skill_id:
                sk.invocations += 1
                sk.confidence = min(sk.confidence + 0.02, 1.0)
                break

    def record_activation(self, skill_ids: List[str]) -> None:
        """Batch-boost skills that were active during a successful AI interaction."""
        id_set = set(skill_ids)
        for sk in self._all_skills:
            if sk.id in id_set:
                sk.invocations += 1
                sk.confidence = min(sk.confidence + 0.01, 1.0)

    def active_skill_ids(self) -> List[str]:
        """Return IDs of skills currently in the context window."""
        ranked = sorted(
            self._all_skills,
            key=lambda s: (s.confidence, s.created_ts),
            reverse=True,
        )[:self._max_context]
        return [s.id for s in ranked]

    @property
    def skill_count(self) -> int:
        return len(self._all_skills)

    def summary(self) -> Dict[str, Any]:
        by_kind: Dict[str, int] = {}
        for s in self._all_skills:
            by_kind[s.kind] = by_kind.get(s.kind, 0) + 1
        return {
            "total_skills": len(self._all_skills),
            "by_kind": by_kind,
            "avg_confidence": round(
                sum(s.confidence for s in self._all_skills) / max(1, len(self._all_skills)),
                2,
            ),
        }


# ---------------------------------------------------------------------------
# 3. Self-generating skills loop
# ---------------------------------------------------------------------------

class SelfGeneratingSkillsLoop:
    """The closed cycle: grid → derivations → skills → AI context → new claims → grid.

    This is the Purple-limited way of using AI: instead of training a model,
    provide structural skills that activate its latent potential.

    Triangle time (1r + 0i): the skills observe the AI's potential space
    and collapse it through IVI-derived constraints. Like a human brain
    going back 1 second in flow — the skills shape what the AI produces
    without changing what it is."""

    def __init__(self) -> None:
        self.extractor = DerivationSkillExtractor()
        self.injector = SkillsInjector(max_skills_in_context=25)
        self._cycles = 0
        self._claims_generated = 0
        self._skills_generated = 0

    def tick(self, grid: Any) -> Dict[str, Any]:
        """Run one cycle of the self-generating skills loop.

        1. Extract new skills from grid derivations
        2. Add them to the injector pool
        3. Generate the context block for AI injection
        4. Log the cycle

        Returns a status dict."""
        self._cycles += 1
        t0 = time.time()

        # 1. Extract skills from grid triangles
        new_skills = self.extractor.extract_from_grid(grid)
        added = self.injector.add_skills(new_skills)
        self._skills_generated += added

        # 2. Generate the context block
        context_block = self.injector.format_for_context()

        elapsed = time.time() - t0

        result = {
            "cycle": self._cycles,
            "new_skills": added,
            "total_skills": self.injector.skill_count,
            "context_block_len": len(context_block),
            "elapsed_s": round(elapsed, 3),
        }

        _write_monitor({
            "ts": time.time(),
            "type": "skills_loop_tick",
            "new_skills": added,
            "total_skills": self.injector.skill_count,
            "skills_summary": self.injector.summary(),
            "elapsed_s": round(elapsed, 3),
        })

        return result

    def get_context_for_ai(self) -> str:
        """Get the current skills context block for AI injection.
        This is what shapes the AI's potential — the Purple-limited observation."""
        return self.injector.format_for_context()

    def observe_ai_output(self, ai_text: str, grid: Any) -> Dict[str, Any]:
        """Feed AI output back as claims into the grid, then extract new skills.
        This closes the loop: grid → skills → AI context → AI output → new claims → grid.
        The AI's output is the collapse of its potential; we lift it back into
        the grid's imaginary domain so it can generate new skills."""
        if not ai_text or not ai_text.strip():
            return {"claims_fed": 0, "new_skills": 0}

        claims_fed = 0
        text = ai_text.strip()

        # Extract claim-like statements from the AI's output
        sentences = re.split(r'[.!?\n]+', text)
        fed_texts: Set[str] = set()
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 10 or len(sent) > 200:
                continue
            # Skip meta/filler
            lower = sent.lower()
            if any(skip in lower for skip in [
                "i can", "i will", "let me", "here is", "sure",
                "would you", "shall i", "do you want",
            ]):
                continue
            if sent in fed_texts:
                continue
            fed_texts.add(sent)

        try:
            g = grid.grid if hasattr(grid, 'grid') else grid
            if hasattr(g, 'add_statement_and_loop'):
                for claim_text in list(fed_texts)[:8]:
                    try:
                        g.add_statement_and_loop(claim_text[:200], source="ai_output_feedback")
                        claims_fed += 1
                    except Exception:
                        pass
        except Exception:
            pass

        # Now extract any new skills created by those claims
        new_skills = self.extractor.extract_from_grid(grid)
        added = self.injector.add_skills(new_skills)
        self._skills_generated += added

        result = {"claims_fed": claims_fed, "new_skills": added}

        _write_monitor({
            "ts": time.time(),
            "type": "ai_output_feedback",
            "claims_fed": claims_fed,
            "new_skills": added,
            "total_skills": self.injector.skill_count,
            "input_len": len(text),
        })

        return result

    def record_activation_from_output(self, ai_text: str) -> int:
        """After the AI produces output, boost skills that were in context.
        Returns count of skills boosted."""
        if not ai_text or not ai_text.strip():
            return 0
        active = self.injector.active_skill_ids()
        self.injector.record_activation(active)
        return len(active)

    def status(self) -> Dict[str, Any]:
        return {
            "cycles": self._cycles,
            "skills_generated": self._skills_generated,
            "skills_active": self.injector.skill_count,
            "skills_summary": self.injector.summary(),
        }
