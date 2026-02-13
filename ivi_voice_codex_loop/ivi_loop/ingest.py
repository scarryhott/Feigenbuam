from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .classify import is_question
from .ir import Provenance, Utterance, make_utterance


def ingest_text_message(text: str, source_type: str, source_id: str) -> Utterance:
    prov = Provenance(source_type=source_type, source_id=source_id)
    return make_utterance(role="human", text=text.strip(), is_question=is_question(text), prov=prov)


def ingest_dir_of_texts(path: Path) -> List[Utterance]:
    out: List[Utterance] = []
    for p in sorted(path.rglob("*")):
        if p.is_dir():
            continue
        if p.suffix.lower() not in {".txt", ".md"}:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        out.append(ingest_text_message(text, source_type="import", source_id=str(p)))
    return out


def ingest_chatgpt_export_json(path: Path) -> List[Utterance]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    out: List[Utterance] = []

    def add(role: str, content: str, span: str | None = None) -> None:
        if role not in ("user", "human"):
            return
        prov = Provenance(source_type="chatlog", source_id=str(path), span=span)
        out.append(make_utterance(role="human", text=content.strip(), is_question=is_question(content), prov=prov))

    if isinstance(data, list):
        for i, m in enumerate(data):
            if isinstance(m, dict) and "role" in m and "content" in m and isinstance(m["content"], str):
                add(m["role"], m["content"], span=f"idx:{i}")
        return out

    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        for i, m in enumerate(data["messages"]):
            if isinstance(m, dict) and isinstance(m.get("content"), str):
                add(m.get("role", ""), m["content"], span=f"messages[{i}]")
        return out

    if isinstance(data, dict) and isinstance(data.get("conversations"), list):
        for cidx, conv in enumerate(data["conversations"]):
            mapping = conv.get("mapping")
            if not isinstance(mapping, dict):
                continue
            for mid, node in mapping.items():
                msg = node.get("message") if isinstance(node, dict) else None
                if not isinstance(msg, dict):
                    continue
                author = msg.get("author", {})
                role = author.get("role", "")
                content = msg.get("content", {})
                parts = content.get("parts", [])
                if role == "user" and isinstance(parts, list) and parts:
                    text = "\n".join([p for p in parts if isinstance(p, str)]).strip()
                    if text:
                        add("user", text, span=f"conv[{cidx}] node:{mid}")
        return out

    return out
