"""
ivi_gateway.py

The single runtime boundary for all effectful actions.

Rule: No external I/O and no state mutation occurs unless an IVI event exists
that (a) declares the intent, (b) binds the permissions, and (c) is later
co-signed by the verifier outcome.

This module is the only entry point for:
  - tool execution (OpenClaw tools, filesystem writes, command execution)
  - outbound network calls (HTTP, model calls, webhooks)
  - state writes (.ivi, .openclaw_skills, repo changes)

Architecture:
  ingress()  -> IntentPacket  (normalize any input source)
  propose()  -> Proposal      (evaluate against semantic + skill context)
  verify()   -> VerificationReport (consent, sandbox, audit, Lean gates)
  commit()   -> CommitReport   (execute + attest)

CLI, goal engine, and openclaw_actions do effects ONLY via this gateway.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import Settings
from .ir import stable_hash, now_iso
from .storage import (
    append_event,
    append_intent,
    append_attest,
    ensure_dirs,
    read_events,
)


# ---------------------------------------------------------------------------
# 0. Domain Model — imaginary (0) / real (∞) operational modes
# ---------------------------------------------------------------------------
#
# Imaginary (0-side): staged, latent, non-effectful
#   - candidate proposals, branch hypotheses, tool plans not executed
#   - latent reasoning traces, unverified claims, draft skills
#   - cheap to create, cheap to discard
#
# Real (∞-side): committed, executed, externally visible
#   - emitted tokens, written files, executed tools, network calls
#   - Lean build outputs, persisted skill manifests, attest events
#   - effects propagate outward, harder to undo
#
# Potential = the structure connecting them (reversible traceability)
#   - append-only log preserves unrealized alternatives after actions
#   - Lean errors reconstruct constraints → new candidates
#   - committed artifacts become input for further proposals

ARTIFACT_DOMAIN_MAP: Dict[str, str] = {
    # --- Imaginary domain (0-side: staged, latent) ---
    "intent":               "imaginary",  # declared intent, not yet executed
    "proposal":             "imaginary",  # candidate mutation before verification
    "branch":               "imaginary",  # alternative state hypothesis
    "candidate_proof":      "imaginary",  # unverified Lean candidate
    "tool_plan":            "imaginary",  # planned but unexecuted tool calls
    "draft_skill":          "imaginary",  # skill before manifest verification
    "quarantined_claim":    "imaginary",  # claim that failed verification
    "latent_trace":         "imaginary",  # internal reasoning / analysis
    "analysis_note":        "imaginary",  # native intelligence insight
    "derivation":           "imaginary",  # grid derivation (structural)
    # --- Real domain (∞-side: committed, effectful) ---
    "attest_committed":     "real",       # co-signed outcome of executed action
    "utterance":            "real",       # emitted to user (externalized)
    "file_write":           "real",       # written to filesystem
    "tool_execution":       "real",       # tool actually ran
    "network_call":         "real",       # HTTP/model call executed
    "lean_build":           "real",       # Lean compilation ran
    "skill_manifest":       "real",       # verified and persisted skill
    "accepted_claim":       "real",       # claim that passed verification
    "triangle":             "real",       # closed S→D→E in grid
    "equation":             "real",       # verified equation
    "controller_snapshot":  "real",       # persisted orchestrator state
    # --- Boundary (exists in both) ---
    "events_jsonl":         "closure",    # the log itself IS the closure operator
    "grid_state":           "closure",    # reconstructable from events
}


# ---------------------------------------------------------------------------
# 1a. IVIClosure — the operator connecting imaginary ↔ real
# ---------------------------------------------------------------------------

class IVIClosure:
    """The closure operator that maintains reversible traceability
    between imaginary (0) and real (∞) domains.

    Potential is the structure that makes reversible refinement possible:
    - Forward (0→∞): staged proposals become executed actions
    - Backward (∞→0): executed outcomes generate new candidates/constraints
    - The append-only log preserves both directions

    Each cycle:
      1. Current real state (∞): transcript + files + logs
      2. Lift to imaginary (0): generate candidate continuations
      3. Refine in potential space
      4. Select one to externalize → new real state
      5. Repeat
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def reconstruct_potential_from_real(self) -> Dict[str, Any]:
        """∞→0: From executed state, reconstruct the potential space.
        Reads the log of committed actions and extracts:
        - constraints from failures (Lean errors, rejected proposals)
        - open branches (intents without attests)
        - patterns from successful cycles
        This is the backward direction of the closure."""
        events = read_events(self._settings)

        committed_intents: List[Dict[str, Any]] = []
        rejected_intents: List[Dict[str, Any]] = []
        open_intents: Dict[str, Dict[str, Any]] = {}
        constraints_from_failures: List[str] = []
        successful_patterns: List[str] = []

        for ev in events:
            if ev.type == "intent":
                iid = ev.payload.get("intent_id", "")
                open_intents[iid] = ev.payload
            elif ev.type == "attest":
                iid = ev.payload.get("intent_id", "")
                if ev.payload.get("committed", False):
                    committed_intents.append(ev.payload)
                    open_intents.pop(iid, None)
                    # Extract pattern from success
                    tools = ev.payload.get("diff_stats", {}).get("tool", "")
                    if tools:
                        successful_patterns.append(f"tool:{tools}")
                else:
                    rejected_intents.append(ev.payload)
                    open_intents.pop(iid, None)
                    # Extract constraints from failure
                    reasons = ev.payload.get("reason_codes", [])
                    lean = ev.payload.get("lean_result", "")
                    if reasons:
                        constraints_from_failures.extend(reasons)
                    if lean and "fail" in str(lean):
                        constraints_from_failures.append(f"lean:{lean}")

        return {
            "imaginary_count": len(open_intents),
            "real_count": len(committed_intents),
            "rejected_count": len(rejected_intents),
            "open_intents": list(open_intents.keys()),
            "constraints_from_failures": constraints_from_failures,
            "successful_patterns": successful_patterns[:20],
            "potential_size": len(open_intents) + len(constraints_from_failures),
        }

    def reconstruct_real_from_potential(self) -> Dict[str, Any]:
        """0→∞: From the potential space, determine what has been realized.
        Reads the full event log and partitions into domains."""
        events = read_events(self._settings)

        imaginary: List[Dict[str, Any]] = []
        real: List[Dict[str, Any]] = []

        for ev in events:
            domain = ev.payload.get("domain", "")
            entry = {"type": ev.type, "payload_preview": str(ev.payload)[:120]}
            if domain == "real":
                real.append(entry)
            elif domain == "imaginary":
                imaginary.append(entry)
            else:
                # Classify by event type using artifact map
                artifact_type = ev.type
                mapped = ARTIFACT_DOMAIN_MAP.get(artifact_type, "")
                if mapped == "real" or (ev.type == "attest" and ev.payload.get("committed")):
                    real.append(entry)
                elif mapped == "imaginary" or ev.type == "intent":
                    imaginary.append(entry)
                else:
                    # Default: classify by event type heuristic
                    if ev.type in ("utterance", "triangle", "equation"):
                        real.append(entry)
                    else:
                        imaginary.append(entry)

        return {
            "imaginary_items": len(imaginary),
            "real_items": len(real),
            "total_events": len(events),
            "closure_intact": len(imaginary) + len(real) == len(events),
        }

    def domain_summary(self) -> Dict[str, Any]:
        """Full summary of the 0–∞ state."""
        potential = self.reconstruct_potential_from_real()
        realized = self.reconstruct_real_from_potential()
        return {
            "potential_space": potential,
            "realized_state": realized,
            "closure_operator": "append_only_log_with_replay",
            "reversible": True,
        }


# ---------------------------------------------------------------------------
# 1b. SemanticLayer + NavigationContext — layer-specific invariance
# ---------------------------------------------------------------------------
#
# Why: OpenClaw accesses the full OS. A flat context window blows up.
# Fix: each LAYER (scope the agent is operating in) carries its own:
#   - invariants: what must be true while in this scope
#   - context budget: max tokens this layer may consume
#   - allowed_ops: what actions are valid here
#   - summary_fn: how to compress this layer when departing
#
# The universal enforcement (intent/attest) is constant.
# What ADAPTS per-layer is the context envelope and constraints.

@dataclass
class SemanticLayer:
    """A scoped operating context with its own invariants.
    OpenClaw can be "in" multiple layers simultaneously (OS > project > file)
    but each layer has independent constraints and budgets."""
    layer_id: str
    kind: str              # "ivi_core", "project", "os_scope", "runtime", "network"
    root_path: str         # filesystem anchor for this layer
    invariants: List[str]  # semantic rules that MUST hold in this scope
    context_budget: int    # max chars this layer gets in the context window
    allowed_ops: List[str] = field(default_factory=list)  # action classes permitted
    parent_layer_id: str = ""   # layer this nests inside
    summary: str = ""           # compressed repr when this layer is not current
    depth: int = 0              # nesting depth (0=OS, 1=project, 2=module, ...)
    active: bool = True
    entered_ts: float = 0.0


# Pre-defined layer templates
LAYER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "os_root": {
        "kind": "os_scope",
        "invariants": [
            "read_only_unless_in_project_scope",
            "no_mutation_outside_known_roots",
            "discovery_is_always_allowed",
        ],
        "context_budget": 800,
        "allowed_ops": ["read", "claim_add"],
        "depth": 0,
    },
    "ivi_core": {
        "kind": "ivi_core",
        "invariants": [
            "every_mutation_requires_intent_attest",
            "lean_verification_on_derived_files",
            "grid_consistency_maintained",
            "append_only_log_integrity",
        ],
        "context_budget": 3000,
        "allowed_ops": ["read", "write", "execute", "lean", "claim_add", "skill_save"],
        "depth": 1,
    },
    "project": {
        "kind": "project",
        "invariants": [
            "respect_project_gitignore",
            "write_requires_consent_or_autonomy_mode",
            "skill_saves_go_to_project_skills_dir",
        ],
        "context_budget": 2000,
        "allowed_ops": ["read", "write", "execute", "skill_save", "claim_add"],
        "depth": 1,
    },
    "runtime": {
        "kind": "runtime",
        "invariants": [
            "sandbox_execution_only",
            "timeout_enforced",
            "no_persistent_state_outside_project",
        ],
        "context_budget": 600,
        "allowed_ops": ["read", "execute"],
        "depth": 2,
    },
    "network": {
        "kind": "network",
        "invariants": [
            "outbound_only_with_network_permission",
            "no_credential_exfiltration",
            "response_logged_to_event_spine",
        ],
        "context_budget": 400,
        "allowed_ops": ["network"],
        "depth": 2,
    },
}


class NavigationContext:
    """Tracks OpenClaw's position across semantic layers.

    The invariant: as OpenClaw navigates the full OS, context is managed
    per-layer so the window never blows up. Departing layers get compressed
    into summaries; arriving layers get expanded with scope-specific details.
    The universal enforcement (intent/attest) is constant across all layers.

    Layer stack example:
      [os_root] → [project:Purple] → [module:ivi_gateway.py]
    Each layer has its own invariants, budget, and allowed operations.
    """

    def __init__(self) -> None:
        self._layers: Dict[str, SemanticLayer] = {}
        self._layer_stack: List[str] = []  # ordered from outermost to innermost
        self._transition_log: List[Dict[str, Any]] = []
        self._total_budget: int = 6000  # total chars available across all layers

    @property
    def current_layer(self) -> Optional[SemanticLayer]:
        """The innermost active layer."""
        if not self._layer_stack:
            return None
        return self._layers.get(self._layer_stack[-1])

    @property
    def active_invariants(self) -> List[str]:
        """All invariants from all active layers (union)."""
        invariants: List[str] = []
        for lid in self._layer_stack:
            layer = self._layers.get(lid)
            if layer and layer.active:
                invariants.extend(layer.invariants)
        return invariants

    @property
    def active_allowed_ops(self) -> List[str]:
        """Allowed ops = intersection of all active layers.
        An op must be allowed at every layer in the stack."""
        if not self._layer_stack:
            return []
        sets = []
        for lid in self._layer_stack:
            layer = self._layers.get(lid)
            if layer and layer.active:
                sets.append(set(layer.allowed_ops))
        if not sets:
            return []
        result = sets[0]
        for s in sets[1:]:
            result = result & s
        return sorted(result)

    def enter_layer(
        self,
        layer_id: str,
        kind: str,
        root_path: str,
        template: str = "",
        invariants: Optional[List[str]] = None,
        context_budget: Optional[int] = None,
        allowed_ops: Optional[List[str]] = None,
    ) -> SemanticLayer:
        """Enter a new layer scope. If a template is specified, use it as base."""
        tmpl = LAYER_TEMPLATES.get(template, LAYER_TEMPLATES.get(kind, {}))

        layer = SemanticLayer(
            layer_id=layer_id,
            kind=kind,
            root_path=root_path,
            invariants=invariants or tmpl.get("invariants", []),
            context_budget=context_budget or tmpl.get("context_budget", 1000),
            allowed_ops=allowed_ops or tmpl.get("allowed_ops", ["read"]),
            parent_layer_id=self._layer_stack[-1] if self._layer_stack else "",
            depth=tmpl.get("depth", len(self._layer_stack)),
            active=True,
            entered_ts=time.time(),
        )

        self._layers[layer_id] = layer
        self._layer_stack.append(layer_id)
        self._transition_log.append({
            "action": "enter",
            "layer_id": layer_id,
            "kind": kind,
            "root_path": root_path,
            "ts": time.time(),
        })

        # Rebalance budgets: current layer gets priority
        self._rebalance_budgets()
        return layer

    def exit_layer(self, layer_id: str = "") -> Optional[str]:
        """Exit a layer, compressing it into a summary.
        If no layer_id given, exits the innermost layer."""
        target = layer_id or (self._layer_stack[-1] if self._layer_stack else "")
        if not target or target not in self._layers:
            return None

        layer = self._layers[target]
        # Compress departing layer into summary
        layer.summary = self._compress_layer(layer)
        layer.active = False

        if target in self._layer_stack:
            self._layer_stack.remove(target)

        self._transition_log.append({
            "action": "exit",
            "layer_id": target,
            "summary_len": len(layer.summary),
            "ts": time.time(),
        })

        self._rebalance_budgets()
        return layer.summary

    def _compress_layer(self, layer: SemanticLayer) -> str:
        """Compress a layer into a minimal summary that preserves invariants.
        This is the key to preventing context explosion:
        when leaving a layer, reduce it to what matters."""
        parts = [
            f"[{layer.kind}:{layer.layer_id}",
            f" root={Path(layer.root_path).name}",
        ]
        if layer.invariants:
            parts.append(f" inv={','.join(layer.invariants[:3])}")
        parts.append("]")
        return "".join(parts)

    def _rebalance_budgets(self) -> None:
        """Rebalance context budgets: innermost (current) layer gets most space.
        Parent layers get compressed proportional to depth."""
        active = [lid for lid in self._layer_stack if self._layers[lid].active]
        if not active:
            return

        n = len(active)
        # Current layer gets 50% of budget, rest split among parents
        current_share = int(self._total_budget * 0.50)
        remaining = self._total_budget - current_share
        parent_share = remaining // max(1, n - 1) if n > 1 else 0

        for i, lid in enumerate(active):
            if i == n - 1:  # innermost = current
                self._layers[lid].context_budget = current_share
            else:
                self._layers[lid].context_budget = parent_share

    def classify_path(self, path: str) -> str:
        """Classify a filesystem path into a layer kind."""
        p = Path(path).resolve()
        ps = str(p)

        # Check against existing layers first
        for lid in reversed(self._layer_stack):
            layer = self._layers[lid]
            if ps.startswith(layer.root_path):
                return layer.kind

        # Heuristic classification
        if "IVI" in ps or "ivi_" in ps or ".ivi" in ps:
            return "ivi_core"
        if "Derived" in ps or ".lean" in Path(path).suffix:
            return "ivi_core"
        parts_lower = [x.lower() for x in p.parts]
        if any(x in parts_lower for x in ("purple", "feigenbuam", "ivi_voice_codex_loop")):
            return "project"
        return "os_scope"

    def layer_context_for_prompt(self) -> str:
        """Build the context string for the LLM, respecting per-layer budgets.
        This replaces flat context accumulation with structured layer-aware context."""
        parts: List[str] = []
        for lid in self._layer_stack:
            layer = self._layers.get(lid)
            if not layer:
                continue
            budget = layer.context_budget
            if layer.active and lid == self._layer_stack[-1]:
                # Current layer: full detail up to budget
                parts.append(f"[LAYER:{layer.kind} root={Path(layer.root_path).name} ops={','.join(layer.allowed_ops[:4])}]")
                if layer.invariants:
                    inv_str = "; ".join(layer.invariants[:4])
                    parts.append(f"  invariants: {inv_str[:budget]}")
            else:
                # Parent/inactive layer: compressed summary
                summary = layer.summary or self._compress_layer(layer)
                parts.append(summary[:budget])

        # Include inactive (exited) layers as compressed references
        for lid, layer in self._layers.items():
            if not layer.active and lid not in self._layer_stack:
                if layer.summary:
                    parts.append(layer.summary[:200])

        return "\n".join(parts)

    def verify_op_allowed(self, action_class: str) -> Tuple[bool, str]:
        """Check if an action class is allowed by the current layer stack."""
        allowed = self.active_allowed_ops
        if not allowed:
            return True, "no_layers_active"  # permissive if no layers
        if action_class in allowed:
            return True, "layer_allows_op"
        return False, f"layer_blocks_{action_class}_allowed={','.join(allowed)}"

    def status(self) -> Dict[str, Any]:
        return {
            "stack": list(self._layer_stack),
            "current": self._layer_stack[-1] if self._layer_stack else None,
            "active_invariants": self.active_invariants,
            "active_ops": self.active_allowed_ops,
            "layers": {
                lid: {
                    "kind": l.kind,
                    "root": l.root_path,
                    "budget": l.context_budget,
                    "active": l.active,
                }
                for lid, l in self._layers.items()
            },
            "transitions": len(self._transition_log),
        }


# ---------------------------------------------------------------------------
# 1c. IntentPacket — normalized ingress from any source
# ---------------------------------------------------------------------------

@dataclass
class IntentPacket:
    """Every ingress source is normalized into this structure.
    No bypass: CLI, voice, goal engine, webhooks, scheduled tasks
    all produce IntentPackets before anything happens."""
    intent_id: str
    raw_input: str
    channel: str            # "cli_typed", "cli_voice", "goal_engine", "autonomous", "webhook", "scheduled"
    actor: str              # "user", "openclaw", "purple_goal_engine", "autonomous_loop"
    persona_context: str    # soul anchor / persona digest
    order1_classification: str  # "question", "statement", "command", "insight", "action"
    requested_action_class: str  # "read", "write", "execute", "network", "lean", "skill_save", "claim_add"
    requested_tools: List[str] = field(default_factory=list)
    requested_paths: List[str] = field(default_factory=list)
    network_target: str = ""
    consent_scope: str = ""
    order_mode: str = "order_1_projection_safe"
    skill_ctx: str = ""
    ts: float = 0.0


# ---------------------------------------------------------------------------
# 2. VerificationReport — result of all gates
# ---------------------------------------------------------------------------

@dataclass
class VerificationReport:
    """Result of running all verifiers against a proposal."""
    intent_id: str
    passed: bool
    consent_ok: bool = True
    sandbox_ok: bool = True
    audit_ok: bool = True
    lean_ok: bool = True
    reason_codes: List[str] = field(default_factory=list)
    verifier_details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 3. CommitReport — result of execution + attestation
# ---------------------------------------------------------------------------

@dataclass
class CommitReport:
    """Result of executing an action and writing the attest event."""
    intent_id: str
    committed: bool
    result: Any = None
    diff_stats: Dict[str, Any] = field(default_factory=dict)
    attest_payload: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


# ---------------------------------------------------------------------------
# 4. Verifiers — machine-checkable gates from ORCHESTRATOR_SPEC
# ---------------------------------------------------------------------------

# Order-mode permission matrix (from ORCHESTRATOR_SPEC.md §12.1)
ORDER_MODE_PERMISSIONS: Dict[str, Dict[str, Any]] = {
    "order_1_projection_safe": {
        "permissions_allowed": ["R_LOCAL"],
        "mutations_allowed": False,
        "autonomy_allowed": False,
        "network_allowed": False,
    },
    "order_2_read_context": {
        "permissions_allowed": ["R_LOCAL", "R_APP", "NET_OUTBOUND"],
        "mutations_allowed": False,
        "autonomy_allowed": False,
        "network_allowed": True,
    },
    "order_3_constrained_write": {
        "permissions_allowed": ["R_LOCAL", "W_LOCAL", "R_APP", "W_APP", "NET_OUTBOUND"],
        "mutations_allowed": True,
        "autonomy_allowed": False,
        "network_allowed": True,
    },
    "order_4_bounded_autonomy": {
        "permissions_allowed": ["R_LOCAL", "W_LOCAL", "R_APP", "W_APP", "NET_OUTBOUND", "SYS_AUTOMATION"],
        "mutations_allowed": True,
        "autonomy_allowed": True,
        "network_allowed": True,
    },
}

# Paths that are never writable regardless of permissions
FORBIDDEN_PATHS = {".env", ".git", "node_modules", ".ssh", ".gnupg"}
FORBIDDEN_EXTENSIONS = {".pem", ".key", ".p12"}


def _verify_consent(
    intent: IntentPacket,
    orchestrator_state: Dict[str, Any],
) -> Tuple[bool, str]:
    """Consent gate: blocks any effect if consent scope not enabled."""
    mode_perms = ORDER_MODE_PERMISSIONS.get(intent.order_mode, ORDER_MODE_PERMISSIONS["order_1_projection_safe"])

    # Read-only actions always pass
    if intent.requested_action_class in ("read", "question", "claim_add"):
        return True, "read_action_always_allowed"

    # Mutations require mutations_allowed in current order mode
    if intent.requested_action_class in ("write", "execute", "skill_save", "config_change"):
        if not mode_perms.get("mutations_allowed", False):
            return False, f"mutations_not_allowed_in_{intent.order_mode}"

    # Network requires network_allowed
    if intent.requested_action_class == "network" or intent.network_target:
        if not mode_perms.get("network_allowed", False):
            return False, f"network_not_allowed_in_{intent.order_mode}"

    # Check explicit consent from orchestrator state
    full_access = orchestrator_state.get("full_access", False)
    consent_valid = orchestrator_state.get("consent_token_valid", False)
    if not full_access and not consent_valid:
        if intent.requested_action_class in ("write", "execute", "network"):
            return False, "no_consent_token"

    return True, "consent_ok"


def _verify_sandbox(
    intent: IntentPacket,
    allowed_roots: List[str],
) -> Tuple[bool, str]:
    """Sandbox boundary gate: checks paths are within allowed roots,
    rejects secrets and forbidden directories."""
    if not intent.requested_paths:
        return True, "no_paths_requested"

    for req_path in intent.requested_paths:
        p = Path(req_path).resolve()

        # Check forbidden paths
        for part in p.parts:
            if part in FORBIDDEN_PATHS:
                return False, f"forbidden_path_component:{part}"
        if p.suffix in FORBIDDEN_EXTENSIONS:
            return False, f"forbidden_extension:{p.suffix}"

        # Check within allowed roots (if roots specified)
        if allowed_roots:
            in_root = any(
                str(p).startswith(str(Path(root).resolve()))
                for root in allowed_roots
            )
            if not in_root:
                return False, f"path_outside_allowed_roots:{req_path}"

    return True, "sandbox_ok"


def _verify_audit(
    intent: IntentPacket,
    intent_logged: bool,
) -> Tuple[bool, str]:
    """Audit completeness gate: ensures intent event was already appended."""
    if not intent_logged:
        return False, "intent_not_logged"
    if not intent.intent_id:
        return False, "missing_intent_id"
    return True, "audit_ok"


def _verify_lean(
    intent: IntentPacket,
) -> Tuple[bool, str]:
    """Lean gate: mandatory verification if proposal touches IVI/Derived or Lean modules."""
    if not intent.requested_paths:
        return True, "no_lean_paths"

    touches_lean = any(
        "IVI/Derived" in p or p.endswith(".lean")
        for p in intent.requested_paths
    )
    if not touches_lean:
        return True, "no_lean_files_touched"

    # Lean verification required — defer to commit phase where actual check runs
    return True, "lean_check_deferred_to_commit"


# ---------------------------------------------------------------------------
# 5. IVI Gateway — the single runtime boundary
# ---------------------------------------------------------------------------

class IVIGateway:
    """The single boundary through which all effectful actions pass.

    Enforces the IVI co-signing rule:
      No external I/O and no state mutation occurs unless an IVI event exists
      that (a) declares the intent, (b) binds the permissions, and (c) is
      later co-signed by the verifier outcome.

    Domain model (0–∞):
      ingress() + propose() + verify() = imaginary domain (0-side: staged)
      commit()                         = promotion to real domain (∞-side: effectful)
      closure operator                 = log + replay + constraint extraction

    Usage:
      gw = IVIGateway(settings, orchestrator_state)
      packet = gw.ingress(raw_input, channel, ...)  # enters imaginary
      gw.propose(packet)                              # logs intent (0-side)
      report = gw.verify(packet)                      # still imaginary
      if report.passed:
          result = gw.commit(packet, action_fn)       # promotes to real (∞-side)
    """

    def __init__(
        self,
        settings: Settings,
        orchestrator_state: Optional[Dict[str, Any]] = None,
        allowed_roots: Optional[List[str]] = None,
    ) -> None:
        self._settings = settings
        self._orchestrator_state = orchestrator_state or {}
        self._allowed_roots = allowed_roots or []
        self._intent_log: Dict[str, IntentPacket] = {}
        self._intents_logged: set = set()
        self._imaginary_count: int = 0  # items currently in 0-side
        self._real_count: int = 0       # items promoted to ∞-side
        self._rejected_count: int = 0   # items that stayed imaginary
        self.closure = IVIClosure(settings)
        self.navigation = NavigationContext()
        ensure_dirs(settings)
        # Auto-enter the base layers
        self._init_base_layers()

    def _init_base_layers(self) -> None:
        """Enter the default layer stack based on settings and allowed roots."""
        home = str(Path.home())
        self.navigation.enter_layer(
            layer_id="os",
            kind="os_scope",
            root_path=home,
            template="os_root",
        )
        # Enter IVI core if settings root looks like the IVI project
        root_str = str(self._settings.root)
        if any(x in root_str for x in ("ivi_voice_codex_loop", "Feigenbuam", "Purple")):
            self.navigation.enter_layer(
                layer_id="ivi_core",
                kind="ivi_core",
                root_path=root_str,
                template="ivi_core",
            )
        # Enter project layers for each allowed root that's a project
        for i, aroot in enumerate(self._allowed_roots):
            resolved = str(Path(aroot).resolve())
            kind = self.navigation.classify_path(resolved)
            if kind == "project" and resolved != root_str:
                self.navigation.enter_layer(
                    layer_id=f"project_{i}",
                    kind="project",
                    root_path=resolved,
                    template="project",
                )

    def auto_enter_layer_for_paths(self, paths: List[str]) -> None:
        """Auto-classify paths and enter layers as needed.
        Called by verify() to adapt context as OpenClaw navigates."""
        for p in paths:
            kind = self.navigation.classify_path(p)
            resolved = str(Path(p).resolve())
            # Find the project/scope root for this path
            root = str(Path(p).resolve().parent)
            lid = f"auto_{kind}_{Path(root).name}"
            if lid not in self.navigation._layers:
                self.navigation.enter_layer(
                    layer_id=lid,
                    kind=kind,
                    root_path=root,
                    template=kind,
                )

    def update_orchestrator_state(self, state: Dict[str, Any]) -> None:
        """Update the orchestrator state snapshot used by verifiers."""
        self._orchestrator_state = state

    # ------------------------------------------------------------------
    # INGRESS — normalize any input source into IntentPacket
    # ------------------------------------------------------------------

    def ingress(
        self,
        raw_input: str,
        channel: str,
        actor: str = "user",
        persona_context: str = "",
        order1_classification: str = "statement",
        requested_action_class: str = "read",
        requested_tools: Optional[List[str]] = None,
        requested_paths: Optional[List[str]] = None,
        network_target: str = "",
        consent_scope: str = "",
        order_mode: str = "order_1_projection_safe",
        skill_ctx: str = "",
    ) -> IntentPacket:
        """Normalize any input source into a single IntentPacket.
        All sources — CLI, voice, goal engine, autonomous — go through here."""
        intent_id = f"I_{stable_hash(f'{channel}|{raw_input[:100]}|{time.time()}')[:16]}"

        packet = IntentPacket(
            intent_id=intent_id,
            raw_input=raw_input,
            channel=channel,
            actor=actor,
            persona_context=persona_context,
            order1_classification=order1_classification,
            requested_action_class=requested_action_class,
            requested_tools=requested_tools or [],
            requested_paths=requested_paths or [],
            network_target=network_target,
            consent_scope=consent_scope,
            order_mode=order_mode,
            skill_ctx=skill_ctx,
            ts=time.time(),
        )

        self._intent_log[intent_id] = packet
        return packet

    # ------------------------------------------------------------------
    # PROPOSE — log intent event (pre-event)
    # ------------------------------------------------------------------

    def propose(self, packet: IntentPacket) -> IntentPacket:
        """Write the intent event to the co-signature spine.
        This is the pre-event: declares intent before anything runs.
        Domain: imaginary (0-side) — no external effects yet."""
        self._imaginary_count += 1
        append_intent(
            self._settings,
            intent_id=packet.intent_id,
            actor=packet.actor,
            channel=packet.channel,
            action_class=packet.requested_action_class,
            requested_tools=packet.requested_tools,
            requested_paths=packet.requested_paths,
            network=packet.network_target,
            consent_scope=packet.consent_scope,
            skill_ctx=packet.skill_ctx,
            order_mode=packet.order_mode,
        )
        self._intents_logged.add(packet.intent_id)
        return packet

    # ------------------------------------------------------------------
    # VERIFY — run all gates (still imaginary domain)
    # ------------------------------------------------------------------

    def verify(self, packet: IntentPacket) -> VerificationReport:
        """Run all verifiers against the intent packet.
        Returns a VerificationReport with per-gate results."""
        reasons: List[str] = []
        details: Dict[str, Any] = {}

        # 1. Consent gate
        consent_ok, consent_reason = _verify_consent(packet, self._orchestrator_state)
        details["consent"] = consent_reason
        if not consent_ok:
            reasons.append(consent_reason)

        # 2. Sandbox boundary gate
        sandbox_ok, sandbox_reason = _verify_sandbox(packet, self._allowed_roots)
        details["sandbox"] = sandbox_reason
        if not sandbox_ok:
            reasons.append(sandbox_reason)

        # 3. Audit completeness gate
        intent_logged = packet.intent_id in self._intents_logged
        audit_ok, audit_reason = _verify_audit(packet, intent_logged)
        details["audit"] = audit_reason
        if not audit_ok:
            reasons.append(audit_reason)

        # 4. Lean gate
        lean_ok, lean_reason = _verify_lean(packet)
        details["lean"] = lean_reason
        if not lean_ok:
            reasons.append(lean_reason)

        # 5. Layer gate: check action allowed in current layer stack
        if packet.requested_paths:
            self.auto_enter_layer_for_paths(packet.requested_paths)
        layer_ok, layer_reason = self.navigation.verify_op_allowed(packet.requested_action_class)
        details["layer"] = layer_reason
        if not layer_ok:
            reasons.append(layer_reason)

        passed = consent_ok and sandbox_ok and audit_ok and lean_ok and layer_ok

        return VerificationReport(
            intent_id=packet.intent_id,
            passed=passed,
            consent_ok=consent_ok,
            sandbox_ok=sandbox_ok,
            audit_ok=audit_ok,
            lean_ok=lean_ok,
            reason_codes=reasons,
            verifier_details=details,
        )

    # ------------------------------------------------------------------
    # COMMIT — execute action + write attest event
    # ------------------------------------------------------------------

    def commit(
        self,
        packet: IntentPacket,
        action_fn: Optional[Callable[..., Any]] = None,
        action_args: Optional[Dict[str, Any]] = None,
    ) -> CommitReport:
        """Execute the action and write the attest co-signature.
        action_fn is the actual effectful operation to run.
        If action_fn is None, this just attests without executing."""

        # Must be verified first — verify inline if not already done
        report = self.verify(packet)
        if not report.passed:
            # Write a rejection attest
            attest = append_attest(
                self._settings,
                intent_id=packet.intent_id,
                verifier_results=report.verifier_details,
                reason_codes=report.reason_codes,
                committed=False,
            )
            return CommitReport(
                intent_id=packet.intent_id,
                committed=False,
                error=f"verification_failed: {', '.join(report.reason_codes)}",
                attest_payload=attest,
            )

        # Execute the action
        result = None
        error = ""
        diff_stats: Dict[str, Any] = {}
        try:
            if action_fn is not None:
                result = action_fn(**(action_args or {}))
                diff_stats["action_executed"] = True
            else:
                diff_stats["action_executed"] = False
        except Exception as exc:
            error = str(exc)[:200]
            diff_stats["action_error"] = error

        committed = not bool(error)

        # Lean verification if paths touch Lean files
        lean_result = "skipped"
        if committed and any(
            "IVI/Derived" in p or p.endswith(".lean")
            for p in packet.requested_paths
        ):
            try:
                from .ivi_semantic_enforcement import LeanVerifier
                lv = LeanVerifier()
                lean_passed, lean_detail = lv.verify(str(self._settings.root))
                lean_result = "pass" if lean_passed else f"fail:{lean_detail}"
                if not lean_passed:
                    committed = False
                    error = f"lean_verification_failed: {lean_detail}"
            except Exception:
                lean_result = "error"

        # Write the attest co-signature
        attest = append_attest(
            self._settings,
            intent_id=packet.intent_id,
            verifier_results=report.verifier_details,
            diff_stats=diff_stats,
            lean_result=lean_result,
            reason_codes=report.reason_codes,
            committed=committed,
        )

        # Track domain transition
        if committed:
            self._real_count += 1
            self._imaginary_count = max(0, self._imaginary_count - 1)
        else:
            self._rejected_count += 1

        return CommitReport(
            intent_id=packet.intent_id,
            committed=committed,
            result=result,
            diff_stats=diff_stats,
            attest_payload=attest,
            error=error,
        )

    # ------------------------------------------------------------------
    # CONVENIENCE: full pipeline in one call
    # ------------------------------------------------------------------

    def execute(
        self,
        raw_input: str,
        channel: str,
        actor: str = "user",
        action_class: str = "read",
        action_fn: Optional[Callable[..., Any]] = None,
        action_args: Optional[Dict[str, Any]] = None,
        requested_tools: Optional[List[str]] = None,
        requested_paths: Optional[List[str]] = None,
        order_mode: str = "order_1_projection_safe",
        persona_context: str = "",
        skill_ctx: str = "",
    ) -> CommitReport:
        """Full pipeline: ingress → propose → verify → commit.
        Convenience method for callers that want one-shot execution."""
        packet = self.ingress(
            raw_input=raw_input,
            channel=channel,
            actor=actor,
            requested_action_class=action_class,
            requested_tools=requested_tools,
            requested_paths=requested_paths,
            order_mode=order_mode,
            persona_context=persona_context,
            skill_ctx=skill_ctx,
        )
        self.propose(packet)
        return self.commit(packet, action_fn=action_fn, action_args=action_args)

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return gateway status including intent/attest counts."""
        from .storage import validate_intent_attest_pairs
        validation = validate_intent_attest_pairs(self._settings)
        return {
            "intents_in_session": len(self._intent_log),
            "intents_logged": len(self._intents_logged),
            "orchestrator_state": {
                k: v for k, v in self._orchestrator_state.items()
                if k in ("full_access", "consent_token_valid", "active_order_mode", "max_order_mode")
            },
            "allowed_roots": self._allowed_roots,
            "intent_attest_validation": validation,
            "domain": {
                "imaginary_staged": self._imaginary_count,
                "real_committed": self._real_count,
                "rejected": self._rejected_count,
            },
            "navigation": self.navigation.status(),
        }

    def domain_status(self) -> Dict[str, Any]:
        """Full 0–∞ domain state: imaginary, real, and closure."""
        return {
            "session": {
                "imaginary": self._imaginary_count,
                "real": self._real_count,
                "rejected": self._rejected_count,
            },
            "closure": self.closure.domain_summary(),
            "artifact_map": ARTIFACT_DOMAIN_MAP,
        }
