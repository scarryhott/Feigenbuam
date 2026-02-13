from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from .config import Settings
from .storage import ensure_dirs, append_event, rebuild_state
from .ir import Provenance, make_note
from .ingest import ingest_chatgpt_export_json, ingest_dir_of_texts, ingest_text_message
from .loop import process_utterance
from .report import format_status
from .lean_gen import generate_lean_phase1
from .analyze import analyze_state
from .ask import ask_repo


def cmd_init(settings: Settings) -> int:
    ensure_dirs(settings)
    rebuild_state(settings)
    return 0


def cmd_say(settings: Settings, text: str) -> int:
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
