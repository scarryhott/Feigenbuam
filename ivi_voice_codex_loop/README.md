# IVI voice/codex loop scaffold (text-first)

This is a repo-local loop that:
1) Ingests user statements (and optional chatlog exports)
2) Classifies inputs as statement vs question
3) Derives "Logic IR" claims (rule-based extractor; extendable)
4) Stores everything with provenance in an append-only event log
5) Generates Lean stubs from accepted claims
6) Writes an analysis report (no compilation required)

## Order-1 Protocol

The canonical protocol for conversations and iteration is documented at:

- `ORDER_1_PROTOCOL.md`
- `POTENTIAL_TRANSITION_SYSTEM.md`

In chat, use the exact phrase **"Order-1 Protocol"** to reference and activate that contract.

## Quick start

```bash
python3 run.py init
python3 run.py say "Define Ω as the 0–∞ closure operator."
python3 run.py say "If D_s J = 0 then [Cl, J] = 0."
python3 run.py status
python3 run.py derive --from-inbox
python3 run.py lean
python3 run.py analyze
```

## Importing chat logs

Supports two simple formats:

* a directory of `.md` or `.txt` files (each file treated as a human message)
* a ChatGPT export JSON (basic support if it contains messages with roles)

```bash
python3 run.py import --path path/to/chat_export.json
python3 run.py import --path path/to/notes_dir
```

All artifacts go under `.ivi/`:

* `.ivi/events.jsonl` append-only event log
* `.ivi/state.json` computed current view
* `.ivi/quarantine.json` quarantined claims
* `IVI/Derived/Phase1/*.lean` generated Lean stubs
* `.ivi/reports/*.json` analysis outputs
