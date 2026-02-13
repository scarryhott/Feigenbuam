"""
ivi_simplicial_grid.py

Implements an "IVI 0–∞ grid" as a simplicial complex of:
  - Statements (S): phenomenal utterances
  - Derivations (D): triangulation/inference steps
  - Equations (E): Lean/math objects ("i" pole)
  - Triangles (T): 2-simplices linking (S, D, E)

Core operations:
  - add_statement(text)
  - derive(...)  -> creates derivation nodes + equation nodes + triangles
  - patch_lean(...) -> writes/updates Lean stubs
  - build_context(query, mode) -> constructs Ω_u = Λ(Π_u(G)) and samples triangles
  - reremember(...) -> anti-collapse sampling (novelty pressure)

This is a concrete minimal stack. Derivation and Lean synthesis are stubbed behind
interfaces so you can plug in Codex/LLM later.

Storage:
  - JSONL append-only logs for each node type
  - An index file (json) for fast adjacency + metrics
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

NodeType = Literal["S", "D", "E", "T"]


# =========================
# Utilities
# =========================


def _now_ts() -> float:
    return time.time()


def _stable_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def _jsonl_append(path: str, obj: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _json_read(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _json_write(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _tokenize(text: str) -> List[str]:
    # lightweight tokenizer: lowercase words/numbers, keep apostrophes inside words
    return re.findall(r"[a-z0-9']+", text.lower())


def _tf(text: str) -> Dict[str, float]:
    toks = _tokenize(text)
    if not toks:
        return {}
    d: Dict[str, float] = {}
    for t in toks:
        d[t] = d.get(t, 0.0) + 1.0
    inv = 1.0 / float(len(toks))
    for k in list(d.keys()):
        d[k] *= inv
    return d


def _cosine_sparse(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # dot
    dot = 0.0
    for k, va in a.items():
        vb = b.get(k)
        if vb is not None:
            dot += va * vb
    # norms
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# =========================
# Node schemas
# =========================


@dataclass(frozen=True)
class Statement:
    sid: str
    text: str
    created_ts: float
    source: str  # "voice" | "chat" | etc.
    tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Derivation:
    did: str
    rule: str  # e.g. "implication-extract", "rewrite", "bridge"
    premises: List[str]  # IDs: sid/eid (strings)
    conclusions: List[str]  # IDs: sid/eid
    notes: str
    created_ts: float

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Equation:
    eid: str
    lean_name: str
    lean_file: str
    statement: str  # human-readable statement of lemma/theorem
    version_hash: str
    created_ts: float

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Triangle:
    tid: str
    sid: str
    did: str
    eid: str
    created_ts: float

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# =========================
# Index / adjacency
# =========================


@dataclass
class GridIndex:
    # node registries
    statements: Dict[str, Dict[str, Any]]
    derivations: Dict[str, Dict[str, Any]]
    equations: Dict[str, Dict[str, Any]]
    triangles: Dict[str, Dict[str, Any]]

    # adjacency
    # sid -> set(tid)
    sid_to_tids: Dict[str, List[str]]
    # eid -> set(tid)
    eid_to_tids: Dict[str, List[str]]
    # did -> set(tid)
    did_to_tids: Dict[str, List[str]]

    # edges / dependencies (graph)
    # node -> neighbors (IDs)
    neighbors: Dict[str, List[str]]

    # lightweight text features for similarity selection
    tf_s: Dict[str, Dict[str, float]]  # sid -> tf
    tf_e: Dict[str, Dict[str, float]]  # eid -> tf (from equation.statement)
    tf_d: Dict[str, Dict[str, float]]  # did -> tf (from notes/rule)

    # anti-collapse trace
    recent_triangle_trace: List[str]  # list of tids (most recent last)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def empty() -> "GridIndex":
        return GridIndex(
            statements={},
            derivations={},
            equations={},
            triangles={},
            sid_to_tids={},
            eid_to_tids={},
            did_to_tids={},
            neighbors={},
            tf_s={},
            tf_e={},
            tf_d={},
            recent_triangle_trace=[],
        )


# =========================
# Core grid
# =========================


class IVISimplicialGrid:
    """
    Persistent IVI simplicial grid:
      - JSONL logs for append-only durability
      - index.json for fast lookups + adjacency

    Directory structure:
      base_dir/
        data/
          statements.jsonl
          derivations.jsonl
          equations.jsonl
          triangles.jsonl
          index.json
        lean/
          Derived/
            <auto>.lean
    """

    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        self.data_dir = os.path.join(self.base_dir, "data")
        self.lean_dir = os.path.join(self.base_dir, "lean")
        self.lean_derived_dir = os.path.join(self.lean_dir, "Derived")

        _ensure_dir(self.data_dir)
        _ensure_dir(self.lean_derived_dir)

        self.paths = {
            "S": os.path.join(self.data_dir, "statements.jsonl"),
            "D": os.path.join(self.data_dir, "derivations.jsonl"),
            "E": os.path.join(self.data_dir, "equations.jsonl"),
            "T": os.path.join(self.data_dir, "triangles.jsonl"),
            "IDX": os.path.join(self.data_dir, "index.json"),
        }

        self.idx: GridIndex = self._load_index()

    # -------------
    # Persistence
    # -------------

    def _load_index(self) -> GridIndex:
        d = _json_read(self.paths["IDX"], None)
        if d is None:
            return GridIndex.empty()
        # dataclass reconstruction
        return GridIndex(**d)

    def _save_index(self) -> None:
        _json_write(self.paths["IDX"], self.idx.to_dict())

    # -------------
    # Add nodes
    # -------------

    def add_statement(
        self,
        text: str,
        source: str = "voice",
        tags: Optional[List[str]] = None,
    ) -> Statement:
        text = text.strip()
        if not text:
            raise ValueError("Statement text is empty.")

        sid = "S_" + _stable_hash(f"{_now_ts()}|{source}|{text}")
        st = Statement(
            sid=sid,
            text=text,
            created_ts=_now_ts(),
            source=source,
            tags=tags or [],
        )

        # persist
        _jsonl_append(self.paths["S"], st.to_dict())

        # index
        self.idx.statements[sid] = st.to_dict()
        self.idx.sid_to_tids.setdefault(sid, [])
        self.idx.neighbors.setdefault(sid, [])
        self.idx.tf_s[sid] = _tf(text)

        self._save_index()
        return st

    def add_equation(
        self,
        lean_name: str,
        statement: str,
        lean_file: Optional[str] = None,
    ) -> Equation:
        statement = statement.strip()
        if not statement:
            raise ValueError("Equation statement is empty.")

        # ensure a stable file mapping
        if lean_file is None:
            lean_file = os.path.join(self.lean_derived_dir, "AutoDerived.lean")
        else:
            # allow relative
            if not os.path.isabs(lean_file):
                lean_file = os.path.join(self.lean_derived_dir, lean_file)

        base = f"{lean_name}|{statement}|{lean_file}"
        eid = "E_" + _stable_hash(base)
        ver = _stable_hash(base + "|v1")

        eq = Equation(
            eid=eid,
            lean_name=lean_name,
            lean_file=lean_file,
            statement=statement,
            version_hash=ver,
            created_ts=_now_ts(),
        )

        # persist
        _jsonl_append(self.paths["E"], eq.to_dict())

        # index
        self.idx.equations[eid] = eq.to_dict()
        self.idx.eid_to_tids.setdefault(eid, [])
        self.idx.neighbors.setdefault(eid, [])
        self.idx.tf_e[eid] = _tf(statement)

        self._save_index()
        return eq

    def add_derivation(
        self,
        rule: str,
        premises: List[str],
        conclusions: List[str],
        notes: str = "",
    ) -> Derivation:
        rule = rule.strip() or "derivation"
        did = "D_" + _stable_hash(f"{_now_ts()}|{rule}|{premises}|{conclusions}|{notes}")

        dv = Derivation(
            did=did,
            rule=rule,
            premises=premises,
            conclusions=conclusions,
            notes=notes,
            created_ts=_now_ts(),
        )

        # persist
        _jsonl_append(self.paths["D"], dv.to_dict())

        # index
        self.idx.derivations[did] = dv.to_dict()
        self.idx.did_to_tids.setdefault(did, [])
        self.idx.neighbors.setdefault(did, [])
        self.idx.tf_d[did] = _tf(f"{rule} {notes}")

        # dependency edges (neighbors)
        for p in premises:
            self._add_neighbor(did, p)
            self._add_neighbor(p, did)
        for c in conclusions:
            self._add_neighbor(did, c)
            self._add_neighbor(c, did)

        self._save_index()
        return dv

    def add_triangle(self, sid: str, did: str, eid: str) -> Triangle:
        if sid not in self.idx.statements:
            raise KeyError(f"Unknown sid: {sid}")
        if did not in self.idx.derivations:
            raise KeyError(f"Unknown did: {did}")
        if eid not in self.idx.equations:
            raise KeyError(f"Unknown eid: {eid}")

        tid = "T_" + _stable_hash(f"{sid}|{did}|{eid}|{_now_ts()}")
        tr = Triangle(tid=tid, sid=sid, did=did, eid=eid, created_ts=_now_ts())

        _jsonl_append(self.paths["T"], tr.to_dict())

        self.idx.triangles[tid] = tr.to_dict()
        self.idx.sid_to_tids.setdefault(sid, []).append(tid)
        self.idx.did_to_tids.setdefault(did, []).append(tid)
        self.idx.eid_to_tids.setdefault(eid, []).append(tid)

        # triangle adjacency edges: connect all three endpoints
        self._add_neighbor(sid, did)
        self._add_neighbor(did, sid)
        self._add_neighbor(did, eid)
        self._add_neighbor(eid, did)
        self._add_neighbor(sid, eid)
        self._add_neighbor(eid, sid)

        self._save_index()
        return tr

    def _add_neighbor(self, a: str, b: str) -> None:
        if a not in self.idx.neighbors:
            self.idx.neighbors[a] = []
        if b not in self.idx.neighbors[a]:
            self.idx.neighbors[a].append(b)

    # =========================
    # Derivation + Lean emission (pluggable)
    # =========================

    def derive_phase1_minimal(self, sid: str) -> Dict[str, Any]:
        """
        Minimal deterministic derivation:
          - creates one Equation E as a Lean lemma stub name derived from statement
          - creates one Derivation D linking sid -> eid
          - creates one Triangle (sid, did, eid)
          - writes/updates Lean stub file
        This is a scaffold. Replace this with your real implication extractor.

        Returns dict with created ids.
        """
        st = self.idx.statements.get(sid)
        if st is None:
            raise KeyError(f"Unknown sid: {sid}")

        text = st["text"]
        lean_name = self._lean_name_from_text(text)
        eq_stmt = self._equation_statement_from_text(text)

        eq = self.add_equation(lean_name=lean_name, statement=eq_stmt)
        dv = self.add_derivation(
            rule="phase1_stub_implication",
            premises=[sid],
            conclusions=[eq.eid],
            notes="Minimal scaffold: treat statement as candidate lemma statement.",
        )
        tr = self.add_triangle(sid=sid, did=dv.did, eid=eq.eid)

        # Lean patch
        self.patch_lean_stub(eq)

        # update trace (anti-collapse)
        self._trace_triangle(tr.tid)

        return {"sid": sid, "eid": eq.eid, "did": dv.did, "tid": tr.tid}

    def patch_lean_stub(self, eq: Equation) -> None:
        """
        Writes/updates a Lean file with a lemma stub for the equation.

        Policy:
          - Ensure file exists and has a header.
          - Insert/replace a marked block for this equation id.
        """
        path = eq.lean_file
        _ensure_dir(os.path.dirname(path))

        header = (
            "-- Auto-generated by IVISimplicialGrid\n"
            "-- This file is a scaffold; replace stubs with real formalizations.\n\n"
        )
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(header)

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        block_start = f"-- >>> IVI_EQUATION {eq.eid} BEGIN\n"
        block_end = f"-- <<< IVI_EQUATION {eq.eid} END\n"

        lemma_stub = self._lean_lemma_stub(eq.lean_name, eq.statement)
        new_block = block_start + lemma_stub + "\n" + block_end

        if block_start in content and block_end in content:
            # replace existing block
            pre, rest = content.split(block_start, 1)
            _, post = rest.split(block_end, 1)
            content2 = pre + new_block + post
        else:
            # append at end
            content2 = content.rstrip() + "\n\n" + new_block + "\n"

        with open(path, "w", encoding="utf-8") as f:
            f.write(content2)

    def _lean_name_from_text(self, text: str) -> str:
        toks = _tokenize(text)
        if not toks:
            return "ivi_stmt"
        # lean identifier: start with letter, then alnum/underscore
        base = "_".join(toks[:8])
        base = re.sub(r"[^a-z0-9_]", "_", base.lower())
        if not re.match(r"^[a-z_]", base):
            base = "ivi_" + base
        return base[:60]

    def _equation_statement_from_text(self, text: str) -> str:
        # You can replace this with a real “implication extractor”
        # For now: treat the statement as a proposition label.
        # Keep it short to avoid dumping long prose into Lean.
        t = text.strip()
        if len(t) > 180:
            t = t[:177] + "..."
        return f"Proposition derived from: {t}"

    def _lean_lemma_stub(self, lean_name: str, statement: str) -> str:
        # This is intentionally simple; you will later generate real Lean.
        # The 'statement' is kept as a docstring; the lemma itself is `True` for now.
        return (
            f"/-- {statement} -/\n"
            f"theorem {lean_name} : True := by\n"
            f"  trivial\n"
        )

    # =========================
    # Ω_u = Λ(Π_u(G)) : Context building over triangles
    # =========================

    def build_context(
        self,
        query: str,
        mode: Literal["statement", "question", "derive", "lean"] = "question",
        max_triangles: int = 16,
        closure_hops: int = 2,
        novelty_lambda: float = 1.2,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Returns a context packet (Ω_u) as sampled triangles plus their incident nodes.

        Π_u(G): selects candidate triangles by stance alignment (query/mode).
        Λ(...): expands locally in the neighbor graph to pull supporting triangles.

        Anti-collapse: penalize recently used triangles.
        """
        if seed is not None:
            random.seed(seed)

        q_tf = _tf(f"{mode} {query}")

        # 1) Candidate triangles: score by relevance of (S,E,D) texts
        tri_scores: List[Tuple[str, float]] = []
        for tid, tr in self.idx.triangles.items():
            sid = tr["sid"]
            eid = tr["eid"]
            did = tr["did"]

            s_score = _cosine_sparse(q_tf, self.idx.tf_s.get(sid, {}))
            e_score = _cosine_sparse(q_tf, self.idx.tf_e.get(eid, {}))
            d_score = _cosine_sparse(q_tf, self.idx.tf_d.get(did, {}))

            # base relevance: max or blend
            base = 0.55 * max(s_score, e_score) + 0.45 * d_score

            # novelty penalty from trace frequency
            freq = self._trace_freq(tid)
            novelty_pen = math.exp(-novelty_lambda * freq)

            score = base * novelty_pen
            if score > 0.0:
                tri_scores.append((tid, score))

        tri_scores.sort(key=lambda x: x[1], reverse=True)

        # If empty, fall back to most recent triangles (still novelty-penalized)
        if not tri_scores:
            fallback = list(self.idx.triangles.keys())[-min(64, len(self.idx.triangles)) :]
            for tid in fallback:
                base = 0.05
                freq = self._trace_freq(tid)
                novelty_pen = math.exp(-novelty_lambda * freq)
                tri_scores.append((tid, base * novelty_pen))
            tri_scores.sort(key=lambda x: x[1], reverse=True)

        # Π_u: take top-K candidates before closure
        top = tri_scores[: max(8, max_triangles * 3)]

        # 2) Λ closure: expand around selected triangles by walking neighbor graph
        selected_tids: Set[str] = set(tid for tid, _ in top[:max_triangles])
        frontier_nodes: Set[str] = set()
        for tid in selected_tids:
            tr = self.idx.triangles[tid]
            frontier_nodes.update([tr["sid"], tr["did"], tr["eid"]])

        for _ in range(closure_hops):
            next_nodes: Set[str] = set()
            for n in frontier_nodes:
                for nb in self.idx.neighbors.get(n, []):
                    next_nodes.add(nb)
            frontier_nodes |= next_nodes

            # pull triangles incident to any frontier node
            for n in list(frontier_nodes):
                if n.startswith("S_"):
                    for tid in self.idx.sid_to_tids.get(n, []):
                        selected_tids.add(tid)
                elif n.startswith("D_"):
                    for tid in self.idx.did_to_tids.get(n, []):
                        selected_tids.add(tid)
                elif n.startswith("E_"):
                    for tid in self.idx.eid_to_tids.get(n, []):
                        selected_tids.add(tid)

        # 3) Sample triangles from selected_tids using Born-like weights:
        # amplitudes a_i := score_i, probabilities p_i ∝ |a_i|^2
        # (here scores are real, so |a|^2 = a^2)
        weight_map: Dict[str, float] = {}
        score_map = dict(tri_scores)

        for tid in selected_tids:
            s = score_map.get(tid, 0.01)
            weight_map[tid] = s * s

        potential_probs = self._normalize_weights(weight_map)

        sampled_tids = self._sample_weighted_without_replacement(
            weight_map, k=min(max_triangles, len(weight_map))
        )

        # update trace
        for tid in sampled_tids:
            self._trace_triangle(tid)

        # 4) Gather incident nodes (S,D,E) for the packet
        packet = self._context_packet_from_triangles(sampled_tids)

        potential_top = sorted(potential_probs.items(), key=lambda x: x[1], reverse=True)[:16]
        formal_targets: List[Dict[str, str]] = []
        for tid in sampled_tids:
            tri = self.idx.triangles.get(tid)
            if not tri:
                continue
            eq = self.idx.equations.get(tri["eid"])
            if not eq:
                continue
            formal_targets.append(
                {
                    "eid": eq["eid"],
                    "lean_name": eq["lean_name"],
                    "lean_file": eq["lean_file"],
                }
            )

        # include meta
        packet["meta"] = {
            "mode": mode,
            "query": query,
            "max_triangles": max_triangles,
            "closure_hops": closure_hops,
            "novelty_lambda": novelty_lambda,
            "potential_distribution": [{"tid": tid, "p": p} for tid, p in potential_top],
            "collapse_selection": sampled_tids,
            "formal_targets": formal_targets,
            "sampled_tids": sampled_tids,
        }

        self._save_index()
        return packet

    def _context_packet_from_triangles(self, tids: List[str]) -> Dict[str, Any]:
        sids: Set[str] = set()
        dids: Set[str] = set()
        eids: Set[str] = set()

        tris: List[Dict[str, Any]] = []
        for tid in tids:
            tr = self.idx.triangles[tid]
            sids.add(tr["sid"])
            dids.add(tr["did"])
            eids.add(tr["eid"])
            tris.append(tr)

        statements = [self.idx.statements[sid] for sid in sids if sid in self.idx.statements]
        derivations = [self.idx.derivations[did] for did in dids if did in self.idx.derivations]
        equations = [self.idx.equations[eid] for eid in eids if eid in self.idx.equations]

        # sort by time
        statements.sort(key=lambda x: x.get("created_ts", 0.0))
        derivations.sort(key=lambda x: x.get("created_ts", 0.0))
        equations.sort(key=lambda x: x.get("created_ts", 0.0))

        return {
            "triangles": tris,
            "statements": statements,
            "derivations": derivations,
            "equations": equations,
        }

    # =========================
    # Anti-collapse trace
    # =========================

    def _trace_triangle(self, tid: str, max_len: int = 256) -> None:
        self.idx.recent_triangle_trace.append(tid)
        if len(self.idx.recent_triangle_trace) > max_len:
            self.idx.recent_triangle_trace = self.idx.recent_triangle_trace[-max_len:]

    def _trace_freq(self, tid: str, window: int = 128) -> float:
        # frequency in last `window` selections
        tr = self.idx.recent_triangle_trace[-window:]
        if not tr:
            return 0.0
        return float(sum(1 for x in tr if x == tid)) / float(len(tr))

    # =========================
    # Weighted sampling utilities
    # =========================

    def _sample_weighted_without_replacement(self, weights: Dict[str, float], k: int) -> List[str]:
        items = list(weights.items())
        # filter nonpositive
        items = [(i, w) for i, w in items if w > 0.0]
        if not items or k <= 0:
            return []

        # Efraimidis–Spirakis sampling without replacement
        # key = u^(1/w)
        scored: List[Tuple[float, str]] = []
        for item, w in items:
            u = random.random()
            key = u ** (1.0 / w)
            scored.append((key, item))
        scored.sort(reverse=True)
        return [item for _, item in scored[:k]]

    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        positives = {k: v for k, v in weights.items() if v > 0.0}
        z = sum(positives.values())
        if z <= 0.0:
            return {}
        return {k: (v / z) for k, v in positives.items()}

    # =========================
    # Question vs statement routing helpers
    # =========================

    def classify_utterance(self, text: str) -> Literal["statement", "question"]:
        t = text.strip()
        if not t:
            return "statement"
        if t.endswith("?"):
            return "question"
        # simple heuristic: leading interrogatives
        if re.match(r"^\s*(what|why|how|when|where|which|who|can|could|should|is|are|do|does|did)\b", t.lower()):
            return "question"
        return "statement"

    # =========================
    # Simple analysis metrics (for Analysis Phase 1)
    # =========================

    def compute_graph_metrics(self) -> Dict[str, Any]:
        # contradictions are not computed here; you can add explicit conflict edges later
        nS = len(self.idx.statements)
        nD = len(self.idx.derivations)
        nE = len(self.idx.equations)
        nT = len(self.idx.triangles)

        # orphan equations: equations with no triangles
        orphan_E = [eid for eid, tids in self.idx.eid_to_tids.items() if not tids]
        orphan_S = [sid for sid, tids in self.idx.sid_to_tids.items() if not tids]

        # degree stats
        degs = [len(nbs) for nbs in self.idx.neighbors.values()] or [0]
        deg_avg = sum(degs) / float(len(degs))
        deg_max = max(degs)

        return {
            "counts": {"S": nS, "D": nD, "E": nE, "T": nT},
            "orphans": {"E": orphan_E[:50], "S": orphan_S[:50]},
            "degree": {"avg": deg_avg, "max": deg_max},
        }


# =========================
# A minimal loop controller
# =========================


class IVILoopController:
    """
    Implements:
      - if statement: add -> derive -> patch Lean -> analysis update -> status
      - if question: build context -> answer from repo state (no loop)

    The 'answer' is a placeholder; you will swap in a repo search (ripgrep, etc.)
    or an LLM-based codebase QA.
    """

    def __init__(self, grid: IVISimplicialGrid):
        self.grid = grid

        self.phase_dir = os.path.join(self.grid.base_dir, "ivi_memory")
        _ensure_dir(self.phase_dir)
        self.deriv_phase1_path = os.path.join(self.phase_dir, "derivations_phase1.md")
        self.analysis_phase1_path = os.path.join(self.phase_dir, "analysis_phase1.md")

    def ingest(self, text: str, source: str = "voice") -> Dict[str, Any]:
        kind = self.grid.classify_utterance(text)
        if kind == "question":
            return self.answer_question(text)
        return self.add_statement_and_loop(text, source=source)

    def add_statement_and_loop(self, text: str, source: str = "voice") -> Dict[str, Any]:
        st = self.grid.add_statement(text=text, source=source)

        # Derive (stub)
        created = self.grid.derive_phase1_minimal(st.sid)

        # Update derivations phase file
        self._append_derivations_phase1(st.sid, created)

        # Update analysis phase file
        metrics = self.grid.compute_graph_metrics()
        self._write_analysis_phase1(metrics)

        # Build a context packet for "derive" mode (what the system would use next)
        ctx = self.grid.build_context(query=text, mode="derive", max_triangles=12, closure_hops=2)

        return {
            "kind": "statement",
            "sid": st.sid,
            "created": created,
            "metrics": metrics,
            "context_packet": ctx,
        }

    def answer_question(self, question: str) -> Dict[str, Any]:
        # Build a question-mode context packet
        ctx = self.grid.build_context(query=question, mode="question", max_triangles=10, closure_hops=2)

        # Minimal deterministic answer: list the most relevant equations and where they live
        eqs = ctx.get("equations", [])
        top = []
        for e in eqs[:6]:
            top.append(
                {
                    "eid": e["eid"],
                    "lean_name": e["lean_name"],
                    "lean_file": e["lean_file"],
                    "statement": e["statement"],
                }
            )

        return {
            "kind": "question",
            "question": question,
            "context_packet": ctx,
            "suggested_refs": top,
        }

    def _append_derivations_phase1(self, sid: str, created: Dict[str, Any]) -> None:
        st = self.grid.idx.statements.get(sid, {})
        line = (
            f"- **{sid}**: {st.get('text','').strip()}\n"
            f"  - Derived: `{created.get('did')}` → `{created.get('eid')}` via `{created.get('tid')}`\n"
        )
        if not os.path.exists(self.deriv_phase1_path):
            with open(self.deriv_phase1_path, "w", encoding="utf-8") as f:
                f.write("# Derivations Phase 1\n\n")
        with open(self.deriv_phase1_path, "a", encoding="utf-8") as f:
            f.write(line)

    def _write_analysis_phase1(self, metrics: Dict[str, Any]) -> None:
        content = [
            "# Analysis Phase 1\n",
            "## Graph status\n",
            f"- Counts: {metrics['counts']}\n",
            f"- Orphan E (first 50): {metrics['orphans']['E']}\n",
            f"- Orphan S (first 50): {metrics['orphans']['S']}\n",
            f"- Degree: {metrics['degree']}\n",
            "\n## Instructions\n",
            "- (edit this section) Put rules for derivation and Lean patching here.\n",
            "  Example: prefer replacing redundant lemmas; minimize new primitives; keep lemma statements short.\n",
            "",
        ]
        with open(self.analysis_phase1_path, "w", encoding="utf-8") as f:
            f.write("\n".join(content))


# =========================
# CLI
# =========================


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="IVI Simplicial Grid (0–∞) minimal scaffold")
    ap.add_argument("--repo", type=str, default=".", help="Base directory for the grid storage")
    ap.add_argument("--text", type=str, required=True, help="Input utterance (statement or question)")
    ap.add_argument("--source", type=str, default="voice", help="Source tag")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for sampling")

    args = ap.parse_args()

    grid = IVISimplicialGrid(base_dir=args.repo)
    if args.seed is not None:
        random.seed(args.seed)

    loop = IVILoopController(grid)
    out = loop.ingest(args.text, source=args.source)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
