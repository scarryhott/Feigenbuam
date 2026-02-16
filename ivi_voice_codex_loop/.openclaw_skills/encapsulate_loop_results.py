"""
Skill: encapsulate_loop_results
A dataclass for encapsulating loop operation results, including accepted and quarantined logic claims, equations, derivations, triangles, and skip reason.
"""

from dataclasses import dataclass
from typing import List

@dataclass
class LoopResult:
    accepted: List['LogicClaim']
    quarantined: List['LogicClaim']
    equations: List['Equation']
    derivations: List['DerivationStep']
    triangles: List['Triangle']
    skipped: bool
    reason: str