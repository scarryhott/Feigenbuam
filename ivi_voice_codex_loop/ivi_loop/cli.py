from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

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

    return 2
