# OpenClaw + IVI External Orchestrator Spec (Order-1)

## 1) Purpose

Design an external orchestrator that:

1. Listens to microphone input in a controlled session.
2. Routes utterances through OpenClaw persona conditioning.
3. Sends conditioned utterances into the IVI Order-1 controller.
4. Optionally executes external app actions under explicit consent and sandbox controls.
5. Produces traceable artifacts for every operation.

This orchestrator treats:

- **OpenClaw** as persona/memory conditioning.
- **IVI** as the law-governed decision and integration engine.
- **Orchestrator** as runtime/permissions/app-bridge layer.

---

## 2) Existing capability anchors

The orchestrator must preserve behavior already present in this repo:

- OpenClaw persona extraction and memory profile merge (`soul.md` + memory corpus).
- OpenClaw conditioned utterance generation with personalization digest.
- IVI question/statement routing and walk/talk pathways.
- One-command retrain + run path (`/openclaw sync-run <repo_root> :: <utterance>`).

---

## 3) Non-goals

- No unconstrained autonomous app control.
- No silent background mutations to files/apps/network.
- No bypass of consent policy for high-risk actions.

---

## 4) High-level architecture

```text
Mic In -> ASR -> Session Router -> Consent/Policy Gate -> OpenClaw Conditioner
     -> IVI Controller -> Tool Planner -> Sandbox Executor -> Result Normalizer
     -> IVI Artifact Append -> TTS Out
```

### Components

1. **Audio I/O Service**
   - Wake/toggle, streaming ASR, optional TTS.
   - Emits transcript events.

2. **Session Router**
   - Determines utterance kind (`question`, `statement`, `insight`, command).
   - Maps to IVI path (`voice_turn`, walk/talk, sync-run).

3. **OpenClaw Conditioning Layer**
   - Loads active OpenClaw profile.
   - Applies persona transformation to utterance.
   - Emits `personalization_digest`.

4. **Consent/Policy Gate**
   - Resolves permission requirements for each planned tool action.
   - Requests approval when required.

5. **Tool Planner + Sandbox Executor**
   - Converts IVI output/request into tool actions.
   - Executes inside constrained worker runtime.

6. **Audit + Artifact Bridge**
   - Captures request/action/result digests.
   - Writes trace-compatible records back into IVI artifact stream.

---

## 5) Trust boundaries

1. **Boundary A: Mic/ASR -> Orchestrator**
   - Raw audio and transcript are sensitive.
   - Must be encrypted at rest and ephemeral by default.

2. **Boundary B: Orchestrator -> OpenClaw/IVI**
   - Only structured utterance payloads pass.
   - Include session + consent context.

3. **Boundary C: Orchestrator -> External Apps**
   - Strict permission checks.
   - Dedicated scoped credentials per app.

4. **Boundary D: Sandbox -> Host Filesystem/Network**
   - Least privilege mounts.
   - Egress controls and domain allowlist.

---

## 6) Permission model

### 6.1 Permission primitives

- `R_LOCAL` — read local files
- `W_LOCAL` — write local files
- `R_APP:<app>` — read external app data
- `W_APP:<app>` — write/update external app data
- `NET_OUTBOUND` — external HTTP requests
- `SYS_AUTOMATION` — OS/UI automation

### 6.2 Consent modes

- **Per-action required** (default for mutating actions)
- **Session grant** (time-bounded token)
- **Always deny** (policy lock)

### 6.3 Hard confirmation classes

Always require explicit confirmation for:

- Delete/overwrite
- External send/post/share
- Cross-app automation macros
- System-level automation

---

## 7) Sandboxing requirements

Each external action runs in a worker with:

- CPU/memory/time limits
- Read-only FS by default
- Explicit writable mount allowlist
- Network egress allowlist
- Secret redaction in logs
- Deterministic action/result digesting

---

## 8) API schemas

## 8.1 `VoiceSessionState`

```json
{
  "session_id": "string",
  "status": "on|off|idle|listening|executing",
  "voice_mode": "integrated|passthrough",
  "openclaw_attached": true,
  "openclaw_profile_digest": "string",
  "consent_policy_version": "string",
  "active_grants": ["R_LOCAL", "R_APP:calendar"],
  "started_at": "ISO8601",
  "last_event_at": "ISO8601"
}
```

## 8.2 `ConsentDecision`

```json
{
  "decision_id": "string",
  "session_id": "string",
  "action_digest": "string",
  "required_permissions": ["W_APP:calendar"],
  "decision": "approved|denied|expired",
  "scope": "single_action|session",
  "expires_at": "ISO8601",
  "requested_by": "orchestrator_policy_gate",
  "reason": "string"
}
```

## 8.3 `ToolAction`

```json
{
  "action_id": "string",
  "session_id": "string",
  "source": "ivi_orchestrator",
  "app": "calendar|notes|browser|filesystem|shell",
  "operation": "read|create|update|delete|query|execute",
  "payload": {},
  "required_permissions": ["R_APP:calendar"],
  "risk_level": "low|medium|high",
  "dry_run": false,
  "action_digest": "string"
}
```

## 8.4 `SandboxExecutionResult`

```json
{
  "action_id": "string",
  "status": "ok|error|blocked|timeout",
  "started_at": "ISO8601",
  "ended_at": "ISO8601",
  "stdout": "string",
  "stderr": "string",
  "result_payload": {},
  "policy_applied": {
    "network": "allowlist",
    "fs_mode": "ro|rw_scoped",
    "timeout_ms": 15000
  },
  "result_digest": "string"
}
```

## 8.5 `OrchestratorTurnEnvelope`

```json
{
  "session_id": "string",
  "raw_utterance": "string",
  "utterance_kind": "question|statement|insight|command",
  "openclaw_personalization": {
    "enabled": true,
    "personalization_digest": "string",
    "voice_profile": {},
    "memory_profile": {}
  },
  "ivi_route": "voice_turn|walktalk|sync_run",
  "ivi_result": {},
  "tool_actions": [],
  "tool_results": [],
  "trace_digest": "string"
}
```

---

## 9) Orchestrator runtime flows

## 9.1 Basic question flow

1. Mic transcript arrives.
2. Router classifies as question.
3. OpenClaw conditions utterance.
4. Send to `voice_turn` question route.
5. Return answer + references via TTS.
6. Log envelope and digests.

## 9.2 Statement with external action

1. Mic transcript arrives.
2. Router classifies statement.
3. OpenClaw conditions utterance.
4. IVI evaluates and proposes external action.
5. Policy gate checks required permissions.
6. If approved, sandbox executes action.
7. Result returned to IVI and attached to artifacts.
8. Narrate completion back to user.

## 9.3 One-command retrain + execute

`sync_run(repo_root, utterance)`:

1. Rebuild OpenClaw profile from soul + memory corpus.
2. Refresh active persona digest in session state.
3. Execute walk/talk route with fresh profile.

---

## 10) Command UX (external orchestrator)

- `voice on`
- `voice off`
- `voice status`
- `voice grant <permission> [session|once]`
- `voice revoke <permission|all>`
- `voice sync-run <repo_root> :: <utterance>`

Natural-language equivalents should map to same control API.

---

## 11) Security and auditing requirements

1. All action requests/results are digest-stamped.
2. Consent decisions are immutable log entries.
3. High-risk actions require interactive confirmation.
4. Session grants auto-expire.
5. Redact secrets from transcripts and logs.
6. Provide a user-facing “why this action” explanation for every mutation.

---

## 12) Rollout plan

## Phase A — Safe bring-up

- Mic/ASR + OpenClaw conditioning + IVI routing only.
- No mutating external tools.

## Phase B — Read-only integrations

- Enable read/list/query tool adapters.
- Full audit pipeline.

## Phase C — Write integrations with consent

- Enable mutating adapters under strict policy gate.
- Session grant UX + revocation.

## Phase D — Bounded autonomy

- Add scheduled routines and multi-step plans.
- Keep policy gate + sandbox mandatory.

---

## 12.1 IVI Order-mode mapping (Phase A-D)

Treat rollout phases as runtime order modes selected by IVI internal state:

| IVI Order | Rollout Phase | Runtime label | Allowed capability class |
|---|---|---|---|
| Order-1 | Phase A | `order_1_projection_safe` | mic/asr + OpenClaw conditioning + IVI routing only |
| Order-2 | Phase B | `order_2_read_context` | Order-1 + read-only integrations (`search/read/list`) |
| Order-3 | Phase C | `order_3_constrained_write` | Order-2 + explicit-consent write actions |
| Order-4 | Phase D | `order_4_bounded_autonomy` | Order-3 + scheduled routines bounded by tokens + kill switch |

### Mode permission matrix

```json
{
  "order_1_projection_safe": {
    "permissions_allowed": ["R_LOCAL"],
    "app_ops_allowed": ["read", "query"],
    "mutations_allowed": false,
    "autonomy_allowed": false
  },
  "order_2_read_context": {
    "permissions_allowed": ["R_LOCAL", "R_APP:*", "NET_OUTBOUND"],
    "app_ops_allowed": ["read", "query", "list", "search"],
    "mutations_allowed": false,
    "autonomy_allowed": false
  },
  "order_3_constrained_write": {
    "permissions_allowed": ["R_LOCAL", "W_LOCAL", "R_APP:*", "W_APP:*", "NET_OUTBOUND"],
    "app_ops_allowed": ["read", "query", "list", "search", "create", "update", "delete"],
    "mutations_allowed": true,
    "consent_required": true,
    "autonomy_allowed": false
  },
  "order_4_bounded_autonomy": {
    "permissions_allowed": ["R_LOCAL", "W_LOCAL", "R_APP:*", "W_APP:*", "NET_OUTBOUND", "SYS_AUTOMATION"],
    "app_ops_allowed": ["read", "query", "list", "search", "create", "update", "delete", "execute"],
    "mutations_allowed": true,
    "consent_required": true,
    "autonomy_allowed": true,
    "schedule_required": true,
    "kill_switch_required": true
  }
}
```

---

## 12.2 IVI-driven mode selector (internal operating structure)

Add to `VoiceSessionState`:

```json
{
  "active_order_mode": "order_1_projection_safe|order_2_read_context|order_3_constrained_write|order_4_bounded_autonomy",
  "max_order_mode": "order_1_projection_safe|order_2_read_context|order_3_constrained_write|order_4_bounded_autonomy"
}
```

### Selector pseudocode

```python
def select_order_mode(trace, state_checks, permissions, policy_state, current_mode, max_mode):
    # safety first: hard downgrade triggers
    if policy_state.kill_switch:
        return "order_1_projection_safe"

    if state_checks.get("ivi_invariant_dynamics_law", {}).get("enabled", False):
        if not state_checks.get("ivi_invariant_dynamics_law", {}).get("passed", False):
            return "order_1_projection_safe"

    if policy_state.recent_sandbox_failures >= 3:
        return "order_2_read_context" if max_mode != "order_1_projection_safe" else "order_1_projection_safe"

    # candidate upward mode by readiness
    candidate = "order_1_projection_safe"
    if readiness_for_order_2(trace, state_checks):
        candidate = "order_2_read_context"
    if readiness_for_order_3(trace, state_checks, permissions):
        candidate = "order_3_constrained_write"
    if readiness_for_order_4(trace, state_checks, permissions, policy_state):
        candidate = "order_4_bounded_autonomy"

    # enforce user/policy ceiling
    candidate = min_mode(candidate, max_mode)

    # sticky downgrade window
    if policy_state.downgrade_lock_until and now() < policy_state.downgrade_lock_until:
        return min_mode(current_mode, candidate)

    return candidate
```

### Readiness functions (minimum)

- `readiness_for_order_2`: all critical checks pass; no high-severity gaps.
- `readiness_for_order_3`: order-2 readiness + valid consent token(s) for requested write scope.
- `readiness_for_order_4`: order-3 readiness + scheduler enabled + explicit autonomy grant + kill switch armed.

### Escalation / de-escalation rules

1. **Escalate one step at a time** (O1→O2→O3→O4), never jump.
2. **Immediate de-escalation to O1** on invariant-law failure, kill-switch activation, or policy block on critical action.
3. **Sticky de-escalation**: after severe failure, lock at O1/O2 for cooldown window.
4. **Action-level fallback**: if mode permits but specific permission missing, deny action and continue turn in same mode.

---

## 13) Integration acceptance criteria

1. Persona profile includes soul + memory digests and source count.
2. Every turn has an `OrchestratorTurnEnvelope` with trace digest.
3. Any external mutation without consent is blocked.
4. User can inspect active grants and revoke instantly.
5. System can be disabled immediately (`voice off`) and halts tool execution.

---

## 14) Open questions (to finalize before implementation)

1. Which external apps are in MVP scope?
2. Should session grants persist across restarts?
3. What is maximum tolerated latency per turn?
4. Do we require local-only ASR/TTS for privacy mode?
5. What retention policy applies to raw transcripts?
