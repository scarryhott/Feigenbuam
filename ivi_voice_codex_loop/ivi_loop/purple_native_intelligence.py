"""
purple_native_intelligence.py

IVI-derived native intelligence that progressively replaces LLM (ChatGPT) calls.

Purple already has: TF-IDF scoring, cosine similarity, Born-like sampling,
closure computation, claim derivation, graph metrics, semantic enforcement.

This module builds on those foundations to create native AI capabilities:
1. AST-based code analysis (no LLM needed)
2. Pattern detection and extraction via structural analysis
3. IVI claim generation from code structure
4. Capability registry tracking what Purple can do vs what needs LLM
5. Progressive replacement: native first, LLM fallback

Over time, as the IVI grid accumulates claims and the capability registry grows,
more tasks shift from LLM to native Purple intelligence.
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .purple_goal_engine import _write_monitor


# ---------------------------------------------------------------------------
# 1. Native Code Analyzer — AST-based, zero LLM calls
# ---------------------------------------------------------------------------

@dataclass
class CodeInsight:
    """A single insight derived from native code analysis."""
    kind: str  # "function", "class", "pattern", "complexity", "dependency"
    name: str
    file_path: str
    line: int
    description: str
    confidence: float  # 0.0 - 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class NativeCodeAnalyzer:
    """Analyzes Python code using AST — no LLM required."""

    def analyze_file(self, file_path: str) -> List[CodeInsight]:
        """Extract structural insights from a Python file."""
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        insights: List[CodeInsight] = []
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return []

        insights.extend(self._extract_functions(tree, file_path))
        insights.extend(self._extract_classes(tree, file_path))
        insights.extend(self._extract_patterns(tree, file_path, source))
        insights.extend(self._extract_complexity(tree, file_path))
        insights.extend(self._extract_imports(tree, file_path))
        insights.extend(self._extract_call_graph(tree, file_path))

        return insights

    def _extract_functions(self, tree: ast.AST, path: str) -> List[CodeInsight]:
        insights = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                returns = None
                if node.returns:
                    try:
                        returns = ast.unparse(node.returns)
                    except Exception:
                        pass
                doc = ast.get_docstring(node) or ""
                body_lines = node.end_lineno - node.lineno + 1 if node.end_lineno else 0
                insights.append(CodeInsight(
                    kind="function",
                    name=node.name,
                    file_path=path,
                    line=node.lineno,
                    description=f"def {node.name}({', '.join(args[:5])})"
                               + (f" -> {returns}" if returns else "")
                               + (f": {doc[:80]}" if doc else ""),
                    confidence=0.95,
                    metadata={
                        "args": args,
                        "returns": returns,
                        "docstring": doc[:200],
                        "body_lines": body_lines,
                        "is_private": node.name.startswith("_"),
                        "decorators": [
                            ast.unparse(d) if hasattr(ast, "unparse") else str(d)
                            for d in node.decorator_list
                        ],
                    },
                ))
        return insights

    def _extract_classes(self, tree: ast.AST, path: str) -> List[CodeInsight]:
        insights = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = []
                for b in node.bases:
                    try:
                        bases.append(ast.unparse(b))
                    except Exception:
                        pass
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                doc = ast.get_docstring(node) or ""
                insights.append(CodeInsight(
                    kind="class",
                    name=node.name,
                    file_path=path,
                    line=node.lineno,
                    description=f"class {node.name}"
                               + (f"({', '.join(bases)})" if bases else "")
                               + (f": {doc[:80]}" if doc else ""),
                    confidence=0.95,
                    metadata={
                        "bases": bases,
                        "methods": methods,
                        "method_count": len(methods),
                        "docstring": doc[:200],
                    },
                ))
        return insights

    def _extract_patterns(self, tree: ast.AST, path: str, source: str) -> List[CodeInsight]:
        """Detect reusable patterns: decorators, context managers, error handling, etc."""
        insights = []
        for node in ast.walk(tree):
            # Detect try/except patterns
            if isinstance(node, ast.Try):
                handlers = [
                    ast.unparse(h.type) if h.type and hasattr(ast, "unparse") else "Exception"
                    for h in node.handlers
                ]
                insights.append(CodeInsight(
                    kind="pattern",
                    name="error_handling",
                    file_path=path,
                    line=node.lineno,
                    description=f"try/except handling: {', '.join(handlers[:3])}",
                    confidence=0.7,
                    metadata={"handlers": handlers},
                ))
            # Detect context managers (with statements)
            if isinstance(node, ast.With):
                items = []
                for item in node.items:
                    try:
                        items.append(ast.unparse(item.context_expr))
                    except Exception:
                        pass
                if items:
                    insights.append(CodeInsight(
                        kind="pattern",
                        name="context_manager",
                        file_path=path,
                        line=node.lineno,
                        description=f"with {', '.join(items[:2])}",
                        confidence=0.7,
                        metadata={"contexts": items},
                    ))
        return insights

    def _extract_complexity(self, tree: ast.AST, path: str) -> List[CodeInsight]:
        """Compute cyclomatic complexity approximation for functions."""
        insights = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = 1  # base
                for child in ast.walk(node):
                    if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                        complexity += 1
                    elif isinstance(child, ast.BoolOp):
                        complexity += len(child.values) - 1
                if complexity > 5:
                    insights.append(CodeInsight(
                        kind="complexity",
                        name=node.name,
                        file_path=path,
                        line=node.lineno,
                        description=f"{node.name} has cyclomatic complexity {complexity}",
                        confidence=0.9,
                        metadata={"cyclomatic_complexity": complexity},
                    ))
        return insights

    def _extract_imports(self, tree: ast.AST, path: str) -> List[CodeInsight]:
        """Extract dependency graph from imports."""
        insights = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    insights.append(CodeInsight(
                        kind="dependency",
                        name=alias.name,
                        file_path=path,
                        line=node.lineno,
                        description=f"import {alias.name}",
                        confidence=1.0,
                        metadata={"module": alias.name, "alias": alias.asname},
                    ))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = [a.name for a in node.names]
                insights.append(CodeInsight(
                    kind="dependency",
                    name=mod,
                    file_path=path,
                    line=node.lineno,
                    description=f"from {mod} import {', '.join(names[:5])}",
                    confidence=1.0,
                    metadata={"module": mod, "names": names},
                ))
        return insights

    def _extract_call_graph(self, tree: ast.AST, path: str) -> List[CodeInsight]:
        """Extract function→function call relationships as IVI derivation chains.
        These become the structural connective tissue of the grid — not just
        what exists, but how things relate."""
        insights = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            caller = node.name
            callees: Set[str] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        callees.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        callees.add(child.func.attr)
            # Filter self-calls and builtins
            callees.discard(caller)
            callees -= {"print", "len", "str", "int", "float", "bool",
                         "list", "dict", "set", "tuple", "range", "enumerate",
                         "isinstance", "getattr", "setattr", "hasattr", "super",
                         "round", "max", "min", "sorted", "any", "all", "zip",
                         "map", "filter", "open", "type", "repr", "format"}
            if callees:
                insights.append(CodeInsight(
                    kind="call_graph",
                    name=caller,
                    file_path=path,
                    line=node.lineno,
                    description=f"{caller} -> {', '.join(sorted(callees)[:8])}",
                    confidence=0.9,
                    metadata={
                        "caller": caller,
                        "callees": sorted(callees),
                        "edge_count": len(callees),
                    },
                ))
        return insights


# ---------------------------------------------------------------------------
# 2. OS/Runtime Discovery — full system visibility for the autonomous loop
# ---------------------------------------------------------------------------

class OSRuntimeDiscovery:
    """Discovers Python files, runtimes, and projects across the full OS.
    Gives the autonomous loop visibility beyond the fixed target file list
    so skills can be derived from the entire system the AI operates in.

    This is the 'full OS access' component: the skills loop can observe
    any file or runtime, and Purple-derived constraints keep the loop
    semantically invariant regardless of scope."""

    _IGNORED_DIRS = {
        ".git", "node_modules", ".venv", "venv", "__pycache__",
        ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
        "egg-info", ".eggs", "site-packages",
    }

    def __init__(self) -> None:
        self._discovered_files: List[str] = []
        self._discovered_runtimes: List[Dict[str, Any]] = []
        self._scan_roots: List[str] = []
        self._last_scan_ts: float = 0.0
        self._scan_interval: float = 120.0  # rescan every 2 minutes

    def add_scan_root(self, path: str) -> None:
        """Add a directory root to scan for Python files."""
        resolved = str(Path(path).expanduser().resolve())
        if resolved not in self._scan_roots and Path(resolved).is_dir():
            self._scan_roots.append(resolved)

    def discover_from_environment(self) -> None:
        """Auto-discover scan roots from the OS environment."""
        home = Path.home()
        # Standard project locations
        for candidate in [
            home / "Purple",
            home / "Downloads",
            home / "Projects",
            home / "Developer",
            home / "Code",
            home / "repos",
            home / "src",
            Path(__file__).resolve().parent.parent,  # ivi_voice_codex_loop
            Path(__file__).resolve().parent.parent.parent,  # Feigenbuam
        ]:
            if candidate.is_dir():
                self.add_scan_root(str(candidate))

    def discover_python_files(self, max_files: int = 200, max_depth: int = 4) -> List[str]:
        """Discover Python files across all scan roots."""
        now = time.time()
        if self._discovered_files and (now - self._last_scan_ts) < self._scan_interval:
            return self._discovered_files

        if not self._scan_roots:
            self.discover_from_environment()

        files: List[str] = []
        seen: Set[str] = set()

        for root in self._scan_roots:
            root_path = Path(root)
            try:
                for py_file in self._walk_python_files(root_path, max_depth):
                    resolved = str(py_file.resolve())
                    if resolved not in seen:
                        seen.add(resolved)
                        files.append(resolved)
                        if len(files) >= max_files:
                            break
            except Exception:
                continue
            if len(files) >= max_files:
                break

        self._discovered_files = files
        self._last_scan_ts = now
        return files

    def _walk_python_files(self, root: Path, max_depth: int, _depth: int = 0) -> List[Path]:
        """Recursively find .py files, respecting ignored dirs and depth limit."""
        if _depth > max_depth:
            return []
        results: List[Path] = []
        try:
            for item in sorted(root.iterdir()):
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    if item.name.lower() in self._IGNORED_DIRS:
                        continue
                    results.extend(self._walk_python_files(item, max_depth, _depth + 1))
                elif item.is_file() and item.suffix == ".py":
                    results.append(item)
        except (PermissionError, OSError):
            pass
        return results

    def discover_runtimes(self) -> List[Dict[str, Any]]:
        """Discover Python runtimes available on the system."""
        import subprocess
        import shutil

        runtimes: List[Dict[str, Any]] = []

        # Find python executables
        for name in ["python3", "python", "pypy3"]:
            exe = shutil.which(name)
            if exe:
                version = ""
                try:
                    result = subprocess.run(
                        [exe, "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    version = (result.stdout + result.stderr).strip()
                except Exception:
                    pass
                runtimes.append({
                    "name": name,
                    "path": exe,
                    "version": version,
                })

        # Check for Lean
        lean_exe = shutil.which("lean")
        if lean_exe:
            runtimes.append({"name": "lean", "path": lean_exe, "version": ""})
        lake_exe = shutil.which("lake")
        if lake_exe:
            runtimes.append({"name": "lake", "path": lake_exe, "version": ""})

        # Check for node/npm (potential tool backends)
        for name in ["node", "npm"]:
            exe = shutil.which(name)
            if exe:
                runtimes.append({"name": name, "path": exe, "version": ""})

        self._discovered_runtimes = runtimes
        return runtimes

    def discover_running_python_processes(self) -> List[Dict[str, Any]]:
        """Discover currently running Python processes (lightweight, no sudo)."""
        import subprocess
        procs: List[Dict[str, Any]] = []
        try:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "python" in line.lower():
                    parts = line.split(None, 10)
                    if len(parts) >= 11:
                        procs.append({
                            "user": parts[0],
                            "pid": parts[1],
                            "cpu": parts[2],
                            "mem": parts[3],
                            "command": parts[10][:200],
                        })
        except Exception:
            pass
        return procs

    def full_discovery(self) -> Dict[str, Any]:
        """Run complete OS/runtime discovery and return summary."""
        files = self.discover_python_files()
        runtimes = self.discover_runtimes()
        processes = self.discover_running_python_processes()

        return {
            "python_files": len(files),
            "scan_roots": list(self._scan_roots),
            "runtimes": runtimes,
            "running_python_processes": len(processes),
            "sample_files": files[:20],
        }


# ---------------------------------------------------------------------------
# 3. IVI Claim Generator — converts native insights into grid claims
# ---------------------------------------------------------------------------

class IVIClaimGenerator:
    """Converts CodeInsights into IVI grid statements/claims without LLM.
    Generates three tiers of claims:
    1. Definitions — what exists (functions, classes)
    2. Relations — how things connect (call graphs, dependencies)
    3. Hypotheses — what could be improved (complexity, gaps)
    This mirrors the IVI triangle: Statement → Derivation → Equation."""

    def insights_to_claims(self, insights: List[CodeInsight]) -> List[Dict[str, Any]]:
        """Convert code insights into claim-like dicts that can be fed to the grid."""
        claims = []
        for ins in insights:
            if ins.kind == "function":
                text = f"def {ins.name}: {ins.description}"
                claims.append({
                    "text": text[:200],
                    "kind": "definition",
                    "confidence": ins.confidence,
                    "symbols": [ins.name] + ins.metadata.get("args", [])[:5],
                    "source": "native_analysis",
                    "file": ins.file_path,
                    "line": ins.line,
                })
            elif ins.kind == "class":
                text = f"class {ins.name}: {ins.description}"
                claims.append({
                    "text": text[:200],
                    "kind": "definition",
                    "confidence": ins.confidence,
                    "symbols": [ins.name] + ins.metadata.get("bases", []),
                    "source": "native_analysis",
                    "file": ins.file_path,
                    "line": ins.line,
                })
            elif ins.kind == "call_graph":
                # Relationship claims — the derivation chains of the codebase
                caller = ins.metadata.get("caller", ins.name)
                callees = ins.metadata.get("callees", [])
                for callee in callees[:5]:
                    claims.append({
                        "text": f"if {caller} then {callee}",
                        "kind": "rule",
                        "confidence": 0.85,
                        "symbols": [caller, callee],
                        "source": "native_call_graph",
                        "file": ins.file_path,
                        "line": ins.line,
                    })
            elif ins.kind == "complexity":
                cc = ins.metadata.get("cyclomatic_complexity", 0)
                text = f"{ins.name} complexity={cc}, candidate for refactor"
                claims.append({
                    "text": text,
                    "kind": "hypothesis",
                    "confidence": min(0.5 + cc * 0.05, 0.95),
                    "symbols": [ins.name],
                    "source": "native_analysis",
                    "file": ins.file_path,
                    "line": ins.line,
                })
            elif ins.kind == "pattern":
                claims.append({
                    "text": f"pattern:{ins.name} at {Path(ins.file_path).name}:{ins.line}",
                    "kind": "fact",
                    "confidence": ins.confidence,
                    "symbols": [ins.name],
                    "source": "native_analysis",
                    "file": ins.file_path,
                    "line": ins.line,
                })
            elif ins.kind == "dependency":
                # Module dependency as a rule: importing X implies using X
                mod = ins.metadata.get("module", ins.name)
                fname = Path(ins.file_path).stem
                claims.append({
                    "text": f"if {fname} then {mod}",
                    "kind": "rule",
                    "confidence": 0.8,
                    "symbols": [fname, mod],
                    "source": "native_dependency",
                    "file": ins.file_path,
                    "line": ins.line,
                })
        return claims

    def feed_claims_to_grid(self, grid: Any, claims: List[Dict[str, Any]]) -> int:
        """Feed native claims into the IVI grid through the semantic enforcement duality.
        One propose/commit per batch (not per claim) to stay practical."""
        count = 0
        batch = [c for c in claims[:30] if c.get("text")]
        if not batch:
            return 0

        # One duality check for the whole batch
        batch_allowed = True
        try:
            from .ivi_semantic_enforcement import IVISemanticEnforcementDuality
            base = str(Path(grid.grid.base_dir).parent) if hasattr(grid, 'grid') else "."
            duality = IVISemanticEnforcementDuality(base_path=base)
            committed, _msg, _p = duality.propose_and_commit(
                kind="claim_add",
                description=f"batch of {len(batch)} native claims",
                payload={"count": len(batch), "sources": list({c.get('source','') for c in batch})},
                grid=grid,
            )
            batch_allowed = committed
        except Exception:
            pass  # duality unavailable, allow all

        if not batch_allowed:
            return 0

        for claim in batch:
            try:
                grid.add_statement_and_loop(
                    claim["text"],
                    source=claim.get("source", "native_analysis"),
                )
                count += 1
            except Exception:
                pass
        return count


# ---------------------------------------------------------------------------
# 3. Capability Registry — tracks what Purple can do natively
# ---------------------------------------------------------------------------

@dataclass
class NativeCapability:
    """A capability that Purple can perform without LLM."""
    name: str
    description: str
    replaces: str  # what LLM task this replaces
    confidence: float  # how reliable this native capability is
    invocations: int = 0
    last_used_ts: float = 0.0
    success_rate: float = 1.0


class CapabilityRegistry:
    """Tracks native capabilities and decides when to use them vs LLM."""

    def __init__(self) -> None:
        self._capabilities: Dict[str, NativeCapability] = {}
        self._init_builtin_capabilities()

    def _init_builtin_capabilities(self) -> None:
        """Register capabilities that Purple already has natively."""
        builtins = [
            NativeCapability(
                name="code_structure_analysis",
                description="AST-based extraction of functions, classes, imports, complexity",
                replaces="llm_read_file_and_describe",
                confidence=0.95,
            ),
            NativeCapability(
                name="pattern_detection",
                description="Detect error handling, context managers, decorators via AST",
                replaces="llm_find_patterns",
                confidence=0.85,
            ),
            NativeCapability(
                name="claim_derivation",
                description="Regex-based claim extraction from text (define, if-then, is)",
                replaces="llm_extract_claims",
                confidence=0.9,
            ),
            NativeCapability(
                name="grid_context_building",
                description="TF-IDF scoring + cosine similarity + Born sampling for context",
                replaces="llm_find_relevant_context",
                confidence=0.85,
            ),
            NativeCapability(
                name="closure_analysis",
                description="Compute closure deficit, gap rate, active/closure cells",
                replaces="llm_analyze_completeness",
                confidence=0.95,
            ),
            NativeCapability(
                name="conflict_detection",
                description="Detect definition conflicts and equation contradictions",
                replaces="llm_find_conflicts",
                confidence=0.9,
            ),
            NativeCapability(
                name="complexity_scoring",
                description="Cyclomatic complexity computation for functions",
                replaces="llm_assess_code_quality",
                confidence=0.9,
            ),
        ]
        for cap in builtins:
            self._capabilities[cap.name] = cap

    def register(self, cap: NativeCapability) -> None:
        self._capabilities[cap.name] = cap

    def can_handle_natively(self, task: str) -> Optional[NativeCapability]:
        """Check if any native capability can handle this task."""
        task_lower = task.lower()
        for cap in self._capabilities.values():
            if cap.confidence < 0.5:
                continue
            # Match by replaces field or name
            if cap.replaces in task_lower or cap.name in task_lower:
                return cap
            # Fuzzy match on key terms
            if any(term in task_lower for term in cap.name.split("_")):
                return cap
        return None

    def record_invocation(self, name: str, success: bool) -> None:
        cap = self._capabilities.get(name)
        if cap:
            cap.invocations += 1
            cap.last_used_ts = time.time()
            # Update success rate with exponential moving average
            alpha = 0.1
            cap.success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * cap.success_rate
            cap.confidence = min(cap.confidence + 0.01 if success else cap.confidence - 0.05, 1.0)

    def summary(self) -> Dict[str, Any]:
        return {
            "total_capabilities": len(self._capabilities),
            "capabilities": {
                name: {
                    "replaces": cap.replaces,
                    "confidence": round(cap.confidence, 2),
                    "invocations": cap.invocations,
                    "success_rate": round(cap.success_rate, 2),
                }
                for name, cap in self._capabilities.items()
            },
        }


# ---------------------------------------------------------------------------
# 4. Native Autonomous Cycle — replaces LLM for self-improvement
# ---------------------------------------------------------------------------

class IVIPotentialFunctions:
    """Native IVI potential functions that operate on the grid without LLM.
    These implement the core IVI operations that let Purple reason about itself:
    - Closure analysis: what's missing from the grid's topology
    - Gap detection: where the grid's coverage is thin
    - Context building: use the grid's own TF-IDF/Born sampling
    - Trace coverage: what has been visited vs what hasn't
    """

    @staticmethod
    def analyze_closure(grid: Any) -> Dict[str, Any]:
        """Use the grid's own closure computation to find what's missing."""
        try:
            snapshot = grid._autonomy_mission_snapshot()
            metrics = grid.grid.compute_graph_metrics() if hasattr(grid, 'grid') else {}
            return {
                "closure_deficit": int(snapshot.get("closure_deficit_estimate", 0)),
                "gap_rate": float(snapshot.get("gap_rate", 0.0)),
                "derived_density": float(snapshot.get("derived_density", 0.0)),
                "next_prompt": str(snapshot.get("next_prompt", "")),
                "graph_metrics": metrics,
            }
        except Exception:
            return {"closure_deficit": 0, "gap_rate": 0.0, "derived_density": 0.0}

    @staticmethod
    def build_native_context(grid: Any, query: str) -> Dict[str, Any]:
        """Use the grid's own build_context (TF-IDF + Born sampling) natively."""
        try:
            g = grid.grid if hasattr(grid, 'grid') else grid
            if hasattr(g, 'build_context'):
                return g.build_context(query, mode="derive", max_triangles=8)
        except Exception:
            pass
        return {"triangles": [], "statements": [], "derivations": [], "equations": []}

    @staticmethod
    def detect_gaps(grid: Any) -> List[Dict[str, Any]]:
        """Find structural gaps in the grid — areas where closure is incomplete."""
        gaps = []
        try:
            g = grid.grid if hasattr(grid, 'grid') else grid
            if hasattr(g, 'idx'):
                # Find statements without triangles (unconnected claims)
                all_sids = set(g.idx.statements.keys())
                connected_sids = set()
                for tr in g.idx.triangles.values():
                    connected_sids.add(tr.get("sid", ""))
                orphan_sids = all_sids - connected_sids
                for sid in list(orphan_sids)[:10]:
                    st = g.idx.statements.get(sid, {})
                    gaps.append({
                        "type": "orphan_statement",
                        "sid": sid,
                        "text": str(st.get("text", ""))[:100],
                    })
                # Find equations without derivations
                all_eids = set(g.idx.equations.keys())
                derived_eids = set()
                for tr in g.idx.triangles.values():
                    derived_eids.add(tr.get("eid", ""))
                orphan_eids = all_eids - derived_eids
                for eid in list(orphan_eids)[:5]:
                    eq = g.idx.equations.get(eid, {})
                    gaps.append({
                        "type": "orphan_equation",
                        "eid": eid,
                        "lean_name": str(eq.get("lean_name", ""))[:80],
                    })
        except Exception:
            pass
        return gaps

    @staticmethod
    def trace_coverage(grid: Any) -> Dict[str, Any]:
        """Analyze what percentage of the grid has been visited by trace."""
        try:
            g = grid.grid if hasattr(grid, 'grid') else grid
            if hasattr(g, 'idx'):
                total_tids = len(g.idx.triangles)
                traced_tids = len(getattr(g.idx, 'trace_freq', {}))
                total_sids = len(g.idx.statements)
                total_eids = len(g.idx.equations)
                total_dids = len(g.idx.derivations)
                return {
                    "total_triangles": total_tids,
                    "traced_triangles": traced_tids,
                    "trace_coverage": round(traced_tids / max(1, total_tids), 2),
                    "total_statements": total_sids,
                    "total_equations": total_eids,
                    "total_derivations": total_dids,
                }
        except Exception:
            pass
        return {"trace_coverage": 0.0}


class NativeAutonomousCycle:
    """Runs self-improvement cycles using native Purple intelligence.
    Uses IVI potential functions to guide analysis based on grid state."""

    def __init__(self) -> None:
        self.analyzer = NativeCodeAnalyzer()
        self.claim_gen = IVIClaimGenerator()
        self.registry = CapabilityRegistry()
        self.potential = IVIPotentialFunctions()
        self._cycles_run = 0
        self._native_cycles = 0
        self._llm_fallback_cycles = 0
        self._grid_state: Dict[str, Any] = {}

    def run_native_cycle(
        self,
        target_file: str,
        grid: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Run a self-improvement cycle using only native analysis.
        Returns a result dict or None if the file can't be analyzed."""

        if not Path(target_file).is_file():
            return None

        self._cycles_run += 1
        t0 = time.time()

        # 0. Lightweight grid state query (skip expensive metrics to avoid hangs)
        if grid is not None:
            try:
                g = grid.grid if hasattr(grid, 'grid') else grid
                self._grid_state = {
                    "closure_deficit": len(getattr(g.idx, 'statements', {})) - len(getattr(g.idx, 'triangles', {})),
                    "gap_rate": 0.0,
                    "derived_density": 0.0,
                }
                self.registry.record_invocation("closure_analysis", True)
            except Exception:
                pass

        # 1. Native code analysis
        insights = self.analyzer.analyze_file(target_file)
        if not insights:
            return None

        self.registry.record_invocation("code_structure_analysis", True)

        # 2. Generate claims from insights (now includes call graph + dependencies)
        claims = self.claim_gen.insights_to_claims(insights)

        # 3. Feed claims to grid if available
        claims_added = 0
        if grid is not None:
            claims_added = self.claim_gen.feed_claims_to_grid(grid, claims)

        # 4. Compute file-level metrics
        functions = [i for i in insights if i.kind == "function"]
        classes = [i for i in insights if i.kind == "class"]
        patterns = [i for i in insights if i.kind == "pattern"]
        complex_fns = [i for i in insights if i.kind == "complexity"]
        deps = [i for i in insights if i.kind == "dependency"]
        call_edges = [i for i in insights if i.kind == "call_graph"]

        elapsed = time.time() - t0
        self._native_cycles += 1

        result = {
            "type": "native_cycle",
            "file": target_file,
            "functions": len(functions),
            "classes": len(classes),
            "patterns": len(patterns),
            "high_complexity": [
                {"name": c.name, "complexity": c.metadata.get("cyclomatic_complexity", 0)}
                for c in complex_fns
            ],
            "call_edges": sum(e.metadata.get("edge_count", 0) for e in call_edges),
            "dependencies": len(deps),
            "claims_generated": len(claims),
            "claims_added_to_grid": claims_added,
            "elapsed_s": round(elapsed, 3),
            "insights_total": len(insights),
            "grid_closure_deficit": self._grid_state.get("closure_deficit", 0),
            "grid_gap_rate": self._grid_state.get("gap_rate", 0.0),
        }

        # Log to monitor
        _write_monitor({
            "ts": time.time(),
            "type": "native_autonomous_cycle",
            "file": Path(target_file).name,
            "insights": len(insights),
            "claims_added": claims_added,
            "call_edges": result["call_edges"],
            "closure_deficit": result["grid_closure_deficit"],
            "gap_rate": result["grid_gap_rate"],
            "elapsed_s": round(elapsed, 3),
            "cycle": self._cycles_run,
            "native_ratio": round(
                self._native_cycles / max(1, self._cycles_run), 2
            ),
        })

        return result

    def should_use_native(self, task_description: str) -> bool:
        """Decide whether to use native analysis or fall back to LLM."""
        cap = self.registry.can_handle_natively(task_description)
        if cap and cap.confidence >= 0.7:
            return True
        return False

    def status(self) -> Dict[str, Any]:
        total = max(1, self._cycles_run)
        return {
            "cycles_run": self._cycles_run,
            "native_cycles": self._native_cycles,
            "llm_fallback_cycles": self._llm_fallback_cycles,
            "native_ratio": round(self._native_cycles / total, 2),
            "capabilities": self.registry.summary(),
        }
