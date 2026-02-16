from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Settings
from .storage import ensure_dirs, append_event, rebuild_state
from .ir import Provenance, make_note
from .ingest import ingest_chatgpt_export_json, ingest_dir_of_texts, ingest_text_message
from .loop import process_utterance
from .report import format_status
from .lean_gen import generate_lean_phase1
from .analyze import analyze_state
from .ask import ask_repo
from .ivi_simplicial_grid import IVILoopController, IVISimplicialGrid
from .ivi_gateway import IVIGateway
from .voice_audio import VoiceAudioInterface


VOICE_LAYER_DIRNAME = ".ivi_voice_layer"
VOICE_STATE_FILENAME = "voice_state.json"


def cmd_init(settings: Settings) -> int:
    ensure_dirs(settings)
    rebuild_state(settings)
    return 0


def cmd_say(settings: Settings, text: str) -> int:
    stripped = text.strip()
    if stripped.startswith("/"):
        try:
            result = run_voice_cli_turn(settings, stripped)
        except Exception as exc:
            detail = str(exc)
            hint = ""
            if stripped.startswith("/openclaw attach"):
                hint = (
                    "Use a real local path that contains soul.md. "
                    "Example: /openclaw attach /Users/<you>/path/to/openclaw_repo"
                )
                if "<" in stripped or ">" in stripped:
                    hint = (
                        "Detected placeholder path. Replace it with your real OpenClaw repo path containing soul.md."
                    )
            print(
                json.dumps(
                    {
                        "kind": "voice_command_error",
                        "command": stripped,
                        "error": detail,
                        "hint": hint,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    utt = ingest_text_message(text, source_type="text", source_id="cli:say")
    res = process_utterance(settings, utt)
    if res.skipped:
        print("Recorded question (no derivation loop).")
    else:
        print(f"Derived: accepted={len(res.accepted)} quarantined={len(res.quarantined)}")
    return 0


def cmd_import(settings: Settings, path: Path) -> int:
    if path.is_dir():
        utterances = ingest_dir_of_texts(path)
    else:
        if path.suffix.lower() == ".json":
            utterances = ingest_chatgpt_export_json(path)
        else:
            txt = path.read_text(encoding="utf-8", errors="ignore")
            utterances = [ingest_text_message(txt, source_type="import", source_id=str(path))]

    n = 0
    for u in utterances:
        process_utterance(settings, u)
        n += 1
    print(f"Imported {n} human messages.")
    return 0


def cmd_derive_from_inbox(settings: Settings) -> int:
    print("No separate inbox in this scaffold. Use: say / import.")
    return 0


def cmd_lean(settings: Settings) -> int:
    out = generate_lean_phase1(settings)
    print(f"Wrote Lean: {out}")
    return 0


def cmd_analyze(settings: Settings) -> int:
    rep = analyze_state(settings)
    print("Wrote analysis report: .ivi/reports/analysis_phase1_report.json")
    print(f"counts: {rep['counts']}")
    return 0


def cmd_note(settings: Settings, title: str, body: str) -> int:
    note = make_note(title=title, body=body, prov=Provenance(source_type="text", source_id="cli:note"))
    append_event(settings, {"type": "analysis_note", "payload": note.to_dict()})
    rebuild_state(settings)
    print("Recorded analysis note.")
    return 0


def cmd_status(settings: Settings) -> int:
    print(format_status(settings))
    return 0


def cmd_ask(settings: Settings, query: str, max_hits: int, context: int, glob: str | None) -> int:
    report = ask_repo(root=settings.root, query=query, max_hits=max_hits, context=context, glob=glob)
    print(report)
    return 0


def _voice_state_path(settings: Settings) -> Path:
    ensure_dirs(settings)
    return settings.ivi_dir / VOICE_STATE_FILENAME


def _voice_layer_dir(settings: Settings) -> Path:
    path = settings.root / VOICE_LAYER_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_voice_state(settings: Settings) -> Dict[str, Any]:
    path = _voice_state_path(settings)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_voice_state(settings: Settings, state: Dict[str, Any]) -> None:
    path = _voice_state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _restore_voice_controller_state(loop: IVILoopController, state: Dict[str, Any]) -> None:
    repo_root = state.get("openclaw_repo_root")
    if repo_root:
        loop.attach_openclaw_microcosm(repo_root)

    loop._orchestrator_set_full_access(bool(state.get("orchestrator_full_access", False)))
    loop._orchestrator_set_proactive(bool(state.get("orchestrator_proactive_enabled", False)))
    loop._orchestrator_set_continuous(bool(state.get("orchestrator_continuous_enabled", False)))
    loop._orchestrator_set_eternal(bool(state.get("orchestrator_proactive_enabled", False) and state.get("orchestrator_continuous_enabled", False)))
    loop._orchestrator_set_daemon(False)
    if state.get("orchestrator_daemon_enabled", False):
        loop._orchestrator_set_daemon(
            True,
            interval_seconds=state.get("orchestrator_daemon_interval_seconds"),
        )


def _snapshot_voice_controller_state(loop: IVILoopController) -> Dict[str, Any]:
    openclaw_summary = loop._openclaw.summary() if loop._openclaw is not None else None
    return {
        "openclaw_repo_root": openclaw_summary.get("repo_root") if isinstance(openclaw_summary, dict) else None,
        "orchestrator_full_access": bool(loop._orchestrator_full_access),
        "orchestrator_proactive_enabled": bool(loop._orchestrator_proactive_enabled),
        "orchestrator_continuous_enabled": bool(loop._orchestrator_continuous_enabled),
        "orchestrator_daemon_enabled": bool(loop._orchestrator_daemon_enabled),
        "orchestrator_daemon_interval_seconds": float(loop._orchestrator_daemon_interval_seconds),
    }


def run_voice_cli_turn(settings: Settings, text: str) -> Dict[str, Any]:
    state = _load_voice_state(settings)
    base_dir = _voice_layer_dir(settings)
    grid = IVISimplicialGrid(base_dir=str(base_dir))
    loop = IVILoopController(grid)
    _restore_voice_controller_state(loop, state)
    result = loop.voice_turn(text, source="cli_voice")
    _save_voice_state(settings, _snapshot_voice_controller_state(loop))
    return result


def _extract_conversation_text(payload: Dict[str, Any]) -> str:
    def _sanitize(text: str) -> str:
        out = str(text)
        if "[openclaw.voice_persona" in out:
            out = out.split("[openclaw.voice_persona", 1)[0]
        out = out.replace("[openclaw.walktalk]", " ")
        return " ".join(out.split()).strip()

    if not isinstance(payload, dict):
        return ""
    for key in ("answer", "summary", "detail", "insight"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return _sanitize(val)
    refs = payload.get("suggested_refs", [])
    if isinstance(refs, list) and refs:
        names = [str(x.get("lean_name", "")).strip() for x in refs if isinstance(x, dict) and x.get("lean_name")]
        names = [x for x in names if x]
        if names:
            return _sanitize("Top references: " + ", ".join(names[:3]))
    return ""


def _render_conversational_response(result: Dict[str, Any]) -> str:
    kind = str(result.get("kind", "response")).strip() if isinstance(result, dict) else "response"
    if kind == "walktalk":
        route = str(result.get("route", "")).strip()
        inner = result.get("result", {}) if isinstance(result.get("result", {}), dict) else {}
        inner_kind = str(inner.get("kind", "")).strip()
        text = _extract_conversation_text(inner)
        if text:
            return text
        if route or inner_kind:
            return "I routed that through OpenClaw walktalk and updated the loop state."
        return "I processed that through OpenClaw."
    if kind in {"question", "statement", "insight"}:
        text = _extract_conversation_text(result)
        if not text and kind == "statement":
            text = str(result.get("autonomy_prompt", "")).strip()
        if not text and kind == "question":
            text = "I processed your question and updated the active reasoning trace."
        return text.strip()
    if kind == "help":
        commands = result.get("commands", []) if isinstance(result.get("commands", []), list) else []
        preview = ", ".join([str(x) for x in commands[:8]])
        return f"Available commands include: {preview}".strip()
    if kind == "semantic_map":
        return "OpenClaw voice priority with Purple semantic foundation is active."
    if kind == "openclaw_attached":
        root = result.get("openclaw", {}).get("repo_root", "") if isinstance(result.get("openclaw", {}), dict) else ""
        return f"OpenClaw attached at {root}".strip()
    if kind == "openclaw_profile":
        profile = result.get("profile", {}) if isinstance(result.get("profile", {}), dict) else {}
        mode = profile.get("voice_mode", "")
        return f"OpenClaw profile loaded (mode={mode})"
    if kind == "orchestrator_status":
        active = result.get("active_order_mode", "")
        return f"Current orchestrator mode is {active}"
    detail = str(result.get("detail", "")).strip() if isinstance(result, dict) else ""
    return detail if detail else "Done."


def _auto_attach_openclaw_for_voice(loop: IVILoopController, settings: Settings) -> str:
    if loop._openclaw is not None:
        summary = loop._openclaw.summary()
        root = summary.get("repo_root", "") if isinstance(summary, dict) else ""
        return f"OpenClaw attached: {root}".strip()

    default_soul = settings.root / "soul.md"
    if default_soul.exists() and default_soul.is_file():
        attached = loop.attach_openclaw_microcosm(str(settings.root))
        openclaw = attached.get("openclaw", {}) if isinstance(attached.get("openclaw", {}), dict) else {}
        return f"OpenClaw attached: {openclaw.get('repo_root', settings.root)}"

    return "OpenClaw not attached. Run: /openclaw attach <repo_root>"


def _enable_full_loop_for_voice(loop: IVILoopController) -> None:
    loop._orchestrator_set_full_access(True)
    loop._orchestrator_set_proactive(False)
    loop._orchestrator_set_continuous(False)
    loop._orchestrator_set_daemon(False)


def _purple_background_tick(loop: IVILoopController, source: str) -> None:
    """Derive goals and run an autonomous self-improvement cycle after each turn."""
    try:
        engine = getattr(loop, "_purple_goal_engine", None)
        microcosm = getattr(loop, "_openclaw", None)
        if engine is None or microcosm is None:
            return
        engine.derive_all(
            loop_controller=loop,
            conversation_history=getattr(microcosm, "conversation_history", []),
            known_projects=getattr(microcosm, "known_projects", []),
            environment=getattr(microcosm, "environment", {}),
        )
        result = engine.run_autonomous_cycle(microcosm)
        if result:
            import sys
            print(f"\n[auto] {result}", file=sys.stderr, flush=True)
    except Exception:
        pass


def _dispatch_turn(loop: IVILoopController, cmd: str, source: str) -> Dict[str, Any]:
    text = str(cmd).strip()
    gateway: Optional[IVIGateway] = getattr(loop, "_ivi_gateway", None)

    # Classify for gateway
    action_class = "read"
    if text.startswith("/"):
        lower = text.lower()
        if any(w in lower for w in ("write", "save", "set", "enable", "disable", "attach")):
            action_class = "write"
        elif any(w in lower for w in ("run", "exec", "lean")):
            action_class = "execute"

    if gateway is not None:
        packet = gateway.ingress(
            raw_input=text,
            channel=source,
            actor="user",
            order1_classification="command" if text.startswith("/") else "question",
            requested_action_class=action_class,
            order_mode=getattr(loop, "_active_order_mode", "order_3_constrained_write"),
        )
        gateway.propose(packet)
        report = gateway.verify(packet)
        if not report.passed:
            return {"kind": "gateway_blocked", "reason_codes": report.reason_codes,
                    "detail": f"Action blocked: {', '.join(report.reason_codes)}"}

    if text.startswith("/"):
        result = loop.voice_turn(text, source=source)
    else:
        result = loop.voice_turn(f"/walktalk question: {text}", source=source)

    # Attest after execution
    if gateway is not None:
        from .storage import append_attest
        append_attest(
            gateway._settings,
            intent_id=packet.intent_id,
            verifier_results=report.verifier_details if report else {},
            committed=True,
        )

    return result


def _run_conversational_voice_session(loop: IVILoopController, source: str, full_output: bool) -> None:
    if full_output:
        print("OpenClaw voice session active. Type /quit to exit.")
    prompt = "ivi> " if full_output else ""
    while True:
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            break

        cmd = str(line).strip()
        if not cmd:
            continue
        if cmd in {"/quit", "/exit"}:
            break

        try:
            result = _dispatch_turn(loop, cmd, source)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"error: {exc}")
            continue

        if full_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(_render_conversational_response(result), flush=True)

        _purple_background_tick(loop, source)

        engine = getattr(loop, "_purple_goal_engine", None)
        if engine is not None:
            proactive_prompt = engine.check_proactive()
            if proactive_prompt:
                try:
                    proactive_result = _dispatch_turn(loop, proactive_prompt, source=f"{source}_proactive")
                    rendered = _render_conversational_response(proactive_result)
                    if rendered and rendered.strip():
                        print(f"\n{rendered}", flush=True)
                except Exception:
                    pass


def _run_audio_voice_session(loop: IVILoopController, source: str, full_output: bool, audio: VoiceAudioInterface) -> None:
    if full_output:
        print("OpenClaw audio session active. Say 'quit' to exit.")
    exit_phrases = {"/quit", "/exit", "quit", "exit", "quit voice mode", "exit voice mode", "stop listening"}

    while True:
        try:
            cmd = str(audio.listen_once()).strip()
        except KeyboardInterrupt:
            break
        if not cmd:
            continue

        if full_output:
            print(f"you> {cmd}")
        if cmd.lower() in exit_phrases:
            break

        try:
            result = _dispatch_turn(loop, cmd, source)
        except Exception as exc:
            message = f"error: {exc}"
            print(message)
            audio.speak(message)
            continue

        if full_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            audio.speak(_render_conversational_response(result))
        else:
            rendered = _render_conversational_response(result)
            print(rendered)
            audio.speak(rendered)

        _purple_background_tick(loop, source)


def _run_autonomous_loop(loop: IVILoopController, source: str) -> None:
    """Run continuous self-improvement cycles without user input.
    The heartbeat handles the 45s interval; this just keeps the process alive
    and prints autonomous results as they happen.

    Three feedback closures are active:
    1. AI output → grid: every cycle's summary is fed back as claims
    2. OS discovery: targets span the full OS, not just core files
    3. Behavioral observation: skills that were active get confidence boosts
    """
    import time as _time
    import signal
    _stop = False

    def _handle_sig(*_a: Any) -> None:
        nonlocal _stop
        _stop = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    engine = getattr(loop, "_purple_goal_engine", None)
    microcosm = getattr(loop, "_openclaw", None)
    if engine is None or microcosm is None:
        print("[autonomous] No goal engine or microcosm — cannot run.", flush=True)
        return

    # Import native intelligence, skills loop, and OS discovery
    from .purple_native_intelligence import NativeAutonomousCycle, OSRuntimeDiscovery
    from .purple_skills_loop import SelfGeneratingSkillsLoop
    native = NativeAutonomousCycle()
    skills_loop = SelfGeneratingSkillsLoop()
    discovery = OSRuntimeDiscovery()

    # Wire skills + grid ref into microcosm so contextual_response feedback works
    microcosm._skills_loop = skills_loop
    microcosm._loop_controller = loop

    # Access the IVI Gateway for intent/attest co-signing
    gateway: Optional[IVIGateway] = getattr(loop, "_ivi_gateway", None)

    # --- OS/runtime discovery at startup ---
    discovery.discover_from_environment()
    disc_info = discovery.full_discovery()
    print(
        f"[autonomous] OS discovery: {disc_info['python_files']} Python files across "
        f"{len(disc_info['scan_roots'])} roots, "
        f"{len(disc_info['runtimes'])} runtimes, "
        f"{disc_info['running_python_processes']} Python processes.",
        file=sys.stderr, flush=True,
    )

    # Share discovery with the goal engine so it generates broader goals
    engine._os_discovery = discovery

    # Register discovered scan roots as navigation layers in the gateway
    if gateway is not None:
        for scan_root in disc_info.get("scan_roots", []):
            kind = gateway.navigation.classify_path(scan_root)
            lid = f"disc_{Path(scan_root).name}"
            if lid not in gateway.navigation._layers:
                gateway.navigation.enter_layer(
                    layer_id=lid,
                    kind=kind,
                    root_path=scan_root,
                    template=kind,
                )
        # Register discovered runtimes as runtime layers
        for rt in disc_info.get("runtimes", []):
            rt_name = rt.get("name", "")
            rt_path = rt.get("path", "")
            if rt_name and rt_path:
                lid = f"rt_{rt_name}"
                if lid not in gateway.navigation._layers:
                    gateway.navigation.enter_layer(
                        layer_id=lid,
                        kind="runtime",
                        root_path=str(Path(rt_path).parent),
                        template="runtime",
                    )
        nav = gateway.navigation.status()
        print(
            f"[autonomous] Navigation: {len(nav['stack'])} layers, "
            f"ops={','.join(nav['active_ops'][:4])}, "
            f"{len(nav['active_invariants'])} invariants active.",
            file=sys.stderr, flush=True,
        )

    print("[autonomous] Self-improvement loop started (native + skills + OS discovery). Ctrl+C to stop.", file=sys.stderr, flush=True)
    cycle = 0
    while not _stop:
        try:
            engine.derive_all(
                loop_controller=loop,
                conversation_history=getattr(microcosm, "conversation_history", []),
                known_projects=getattr(microcosm, "known_projects", []),
                environment=getattr(microcosm, "environment", {}),
            )

            # Run native cycles directly — no LLM, no 45s wait
            ran_this_round = 0
            candidates = [g for g in engine.state.goals if g.actionable and not g.executed]
            for goal in candidates[:3]:
                if _stop:
                    break
                # Extract file path from goal
                target = engine._extract_target_file(goal.description)
                if not target:
                    continue
                # --- Gateway intent before native cycle ---
                if gateway is not None:
                    gw_packet = gateway.ingress(
                        raw_input=goal.description[:200],
                        channel="autonomous",
                        actor="purple_goal_engine",
                        order1_classification="action",
                        requested_action_class="read",
                        requested_paths=[target],
                        order_mode="order_4_bounded_autonomy",
                    )
                    gateway.propose(gw_packet)
                    gw_report = gateway.verify(gw_packet)
                    if not gw_report.passed:
                        print(f"  [gateway] blocked: {', '.join(gw_report.reason_codes)}", file=sys.stderr, flush=True)
                        continue

                result_dict = native.run_native_cycle(target, grid=loop)
                if result_dict is None:
                    continue

                goal.executed = True
                engine.state.autonomous_cycles_run += 1
                ran_this_round += 1
                cycle += 1

                fname = os.path.basename(target)
                fns = result_dict.get("functions", 0)
                cls = result_dict.get("classes", 0)
                claims = result_dict.get("claims_added_to_grid", 0)
                hi_cc = result_dict.get("high_complexity", [])
                elapsed = result_dict.get("elapsed_s", 0)

                # Tick the skills loop — extract skills from grid derivations
                sk_result = skills_loop.tick(loop)
                sk_new = sk_result.get("new_skills", 0)
                sk_total = sk_result.get("total_skills", 0)

                summary = f"Native: {fname} — {fns} functions, {cls} classes"
                if hi_cc:
                    summary += f", high complexity: {hi_cc[0]['name']}(cc={hi_cc[0]['complexity']})"
                if claims:
                    summary += f", {claims} claims → grid"
                if sk_new:
                    summary += f", +{sk_new} skills ({sk_total} total)"
                summary += f" ({elapsed}s)"
                print(f"[auto #{cycle}] {summary}", flush=True)
                engine._log_to_purple(loop, summary)

                # --- Gateway attest after native cycle ---
                if gateway is not None:
                    from .storage import append_attest as _append_attest
                    _append_attest(
                        gateway._settings,
                        intent_id=gw_packet.intent_id,
                        diff_stats={"claims": claims, "functions": fns, "classes": cls},
                        committed=True,
                    )

                # --- Feedback closure 1: feed cycle summary back as grid claims ---
                try:
                    fb = skills_loop.observe_ai_output(summary, loop)
                    fb_claims = fb.get("claims_fed", 0)
                    fb_skills = fb.get("new_skills", 0)
                    if fb_claims or fb_skills:
                        print(f"  → feedback: {fb_claims} claims, +{fb_skills} skills", flush=True)
                except Exception:
                    pass

                # --- Feedback closure 3: record skill activation ---
                try:
                    boosted = skills_loop.record_activation_from_output(summary)
                    if boosted:
                        pass  # silent — confidence adjustments are internal
                except Exception:
                    pass

            if ran_this_round == 0:
                print("[autonomous] No actionable goals — waiting.", file=sys.stderr, flush=True)

        except Exception as exc:
            print(f"[autonomous] error: {exc}", file=sys.stderr, flush=True)

        # Only sleep between derive rounds, not between native cycles
        for _ in range(45):
            if _stop:
                break
            _time.sleep(1)

    ni_status = native.status()
    sk_status = skills_loop.status()
    disc_final = len(discovery.discover_python_files())
    print(
        f"[autonomous] Stopped after {cycle} cycles. "
        f"Native ratio: {ni_status['native_ratio']:.0%}. "
        f"Skills: {sk_status['skills_active']}. "
        f"OS files discovered: {disc_final}.",
        file=sys.stderr, flush=True,
    )


def cmd_voice(
    settings: Settings,
    source: str = "voice",
    full_output: bool = False,
    audio_enabled: bool = False,
    asr_engine: str = "auto",
    disable_tts: bool = False,
    tts_voice: Optional[str] = None,
    listen_timeout: float = 8.0,
    phrase_time_limit: float = 18.0,
    autonomous: bool = False,
) -> int:
    state = _load_voice_state(settings)
    base_dir = _voice_layer_dir(settings)
    grid = IVISimplicialGrid(base_dir=str(base_dir))
    loop = IVILoopController(grid)
    _restore_voice_controller_state(loop, state)
    attach_message = _auto_attach_openclaw_for_voice(loop, settings)
    _enable_full_loop_for_voice(loop)

    from .purple_goal_engine import PurpleGoalEngine
    goal_engine = PurpleGoalEngine()
    loop._purple_goal_engine = goal_engine

    # Create the IVI Gateway — single runtime boundary for all effects
    gateway = IVIGateway(
        settings=settings,
        orchestrator_state={
            "full_access": True,
            "consent_token_valid": True,
            "active_order_mode": "order_3_constrained_write",
            "max_order_mode": "order_4_bounded_autonomy" if autonomous else "order_3_constrained_write",
        },
        allowed_roots=[str(settings.root), str(base_dir), str(Path.home() / "Purple")],
    )
    loop._ivi_gateway = gateway

    microcosm = getattr(loop, "_openclaw", None)
    if microcosm is not None:
        microcosm.goal_engine = goal_engine
        microcosm._loop_controller = loop  # for native intelligence grid access
        goal_engine.derive_all(
            loop_controller=loop,
            conversation_history=microcosm.conversation_history,
            known_projects=microcosm.known_projects,
            environment=microcosm.environment,
        )
        if autonomous:
            goal_engine._autonomous_mode = True
        else:
            goal_engine.start_heartbeat(loop, microcosm, interval=45.0)
    if full_output:
        print(attach_message)
    if audio_enabled:
        audio = VoiceAudioInterface(
            enabled=True,
            asr_engine=asr_engine,
            enable_tts=not bool(disable_tts),
            tts_voice=tts_voice,
            listen_timeout=listen_timeout,
            phrase_time_limit=phrase_time_limit,
        )
        diag = audio.diagnostics().to_dict()
        if full_output:
            print("Audio diagnostics:", json.dumps(diag, ensure_ascii=False))
        if not diag.get("asr_available", False):
            if full_output:
                print("Audio ASR backend unavailable; falling back to text conversational mode.")
            _run_conversational_voice_session(loop=loop, source=source, full_output=bool(full_output))
        else:
            _run_audio_voice_session(loop=loop, source=source, full_output=bool(full_output), audio=audio)
    elif autonomous:
        _run_autonomous_loop(loop=loop, source=source)
    else:
        _run_conversational_voice_session(loop=loop, source=source, full_output=bool(full_output))
    goal_engine = getattr(loop, "_purple_goal_engine", None)
    if goal_engine is not None:
        goal_engine.stop_heartbeat()
    _save_voice_state(settings, _snapshot_voice_controller_state(loop))
    return 0


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ivi-loop", description="IVI derivation/Lean loop scaffold")
    p.add_argument("--root", type=str, default=".", help="repo root (default: .)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    sp_say = sub.add_parser("say")
    sp_say.add_argument("text", type=str)

    sp_imp = sub.add_parser("import")
    sp_imp.add_argument("--path", type=str, required=True)

    sub.add_parser("derive")
    sub.add_parser("lean")
    sub.add_parser("analyze")

    sp_note = sub.add_parser("note")
    sp_note.add_argument("--title", type=str, required=True)
    sp_note.add_argument("--body", type=str, required=True)

    sub.add_parser("status")

    sp_ask = sub.add_parser("ask")
    sp_ask.add_argument("query", type=str)
    sp_ask.add_argument("--max-hits", type=int, default=50)
    sp_ask.add_argument("--context", type=int, default=2)
    sp_ask.add_argument("--glob", type=str, default=None, help='rg --glob pattern, e.g. "*.py"')

    sp_voice = sub.add_parser("voice")
    sp_voice.add_argument("--source", type=str, default="voice", help="source tag for interactive session")
    sp_voice.add_argument("--full-output", action="store_true", help="print full JSON responses instead of concise conversational output")
    sp_voice.add_argument("--audio", action="store_true", help="enable live microphone/speaker voice interface")
    sp_voice.add_argument(
        "--asr-engine",
        type=str,
        default="auto",
        choices=["auto", "whisper", "sphinx", "google"],
        help="speech recognition engine preference",
    )
    sp_voice.add_argument("--no-tts", action="store_true", help="disable spoken playback responses")
    sp_voice.add_argument("--tts-voice", type=str, default=None, help="optional TTS voice identifier")
    sp_voice.add_argument("--listen-timeout", type=float, default=8.0, help="seconds to wait for speech start")
    sp_voice.add_argument("--phrase-time-limit", type=float, default=18.0, help="max seconds per utterance")
    sp_voice.add_argument("--autonomous", action="store_true", help="run self-improvement loop without user input")

    args = p.parse_args(argv)
    settings = Settings.load(root=Path(args.root))

    if args.cmd == "init":
        return cmd_init(settings)
    if args.cmd == "say":
        return cmd_say(settings, args.text)
    if args.cmd == "import":
        return cmd_import(settings, Path(args.path))
    if args.cmd == "derive":
        return cmd_derive_from_inbox(settings)
    if args.cmd == "lean":
        return cmd_lean(settings)
    if args.cmd == "analyze":
        return cmd_analyze(settings)
    if args.cmd == "note":
        return cmd_note(settings, args.title, args.body)
    if args.cmd == "status":
        return cmd_status(settings)
    if args.cmd == "ask":
        return cmd_ask(settings, args.query, args.max_hits, args.context, args.glob)
    if args.cmd == "voice":
        return cmd_voice(
            settings,
            source=args.source,
            full_output=bool(args.full_output),
            audio_enabled=bool(args.audio),
            asr_engine=str(args.asr_engine),
            disable_tts=bool(args.no_tts),
            tts_voice=args.tts_voice,
            listen_timeout=float(args.listen_timeout),
            phrase_time_limit=float(args.phrase_time_limit),
            autonomous=bool(args.autonomous),
        )

    return 2
