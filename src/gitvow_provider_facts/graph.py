"""A second source for the same questions: a code graph exported as NDJSON, one record per line.

Several tools write one: a session recorder's graph plugin (its whole-graph export with stable ids and file:line),
Graphify, a SCIP index turned into records. They differ in field names and agree on the shape, so this reader takes
a small field map and defaults to the compound-v1 convention:

  {"type": "node", "id": "<repo>:<lang>:<file>:<kind>:<name>", "kind": "function", "file": "api/orders.py",
   "line": 12, "name": "list_orders", "repo": "orders-svc"}
  {"type": "node", "id": "orders-svc:py:api/orders.py:route:GET /v1/orders", "kind": "route", "name": "GET /v1/orders"}
  {"type": "edge", "from": "<handler id>", "to": "<route id>", "relation": "HANDLES_ROUTE", "confidence": 1.0}
  {"type": "edge", "from": "<caller id>", "to": "<handler id>", "relation": "CALLS", "confidence": 0.9}

A node missing `repo`, `file`, `kind` or `name` has them read out of its id. Routes are nodes of kind `route`
(their name is `VERB /path`, or the path alone), or the targets of `HANDLES_ROUTE` edges. Callers of a route are the
sources of `CALLS` edges into the route's handler, at their file and line. What a graph does not know it does not
pretend to: it has no gate classification, no deployment exposure, no whitelist, so those questions come back
`unknown` with the reason, and `gate_bearing` is answered from the configured gate files as before.

Read-only; the file is opened once. Lines that are not JSON objects are counted and skipped.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .store import ROUTE_SUBJECT, Caller, Gate, edge_hits_route, normalize

DEFAULT_FIELDS: dict[str, Any] = {
    "type": "type",
    "node_type": "node",
    "edge_type": "edge",
    "id": "id",
    "kind": "kind",
    "file": "file",
    "line": "line",
    "name": "name",
    "repo": "repo",
    "from": ["from", "src", "source"],
    "to": ["to", "dst", "target"],
    "relation": ["relation", "type", "kind", "label"],
    "confidence": "confidence",
    "route_kinds": ["route", "endpoint", "http_route"],
    "calls": ["CALLS"],
    "handles_route": ["HANDLES_ROUTE"],
    "id_separator": ":",
}


def load_fields(path: str | None) -> dict[str, Any]:
    out = dict(DEFAULT_FIELDS)
    if path:
        with open(path, encoding="utf-8") as fh:
            out.update(json.load(fh))
    return out


def _get(rec: dict[str, Any], key: Any) -> Any:
    keys = key if isinstance(key, list) else [key]
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return None


@dataclass
class Node:
    id: str
    kind: str
    file: str
    line: int | None
    name: str
    repo: str


@dataclass
class GraphStore:
    """The same surface `Store` offers, over an NDJSON graph. Methods a graph cannot answer return empty."""

    path: str
    fields: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_FIELDS))
    nodes: dict[str, Node] = field(default_factory=dict)
    calls_in: dict[str, list[tuple[str, float | None]]] = field(default_factory=lambda: defaultdict(list))
    handles: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))  # handler id → route ids
    route_handlers: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))  # route id → handler ids
    skipped: int = 0

    def __post_init__(self) -> None:
        if not os.path.exists(self.path):
            raise FileNotFoundError(self.path)
        f = self.fields
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    self.skipped += 1
                    continue
                if not isinstance(rec, dict):
                    self.skipped += 1
                    continue
                t = rec.get(f["type"])
                if t == f["node_type"] or (t is None and _get(rec, f["id"]) and not _get(rec, f["from"])):
                    self._node(rec)
                elif t == f["edge_type"] or _get(rec, f["from"]):
                    self._edge(rec)
                else:
                    self.skipped += 1

    def _node(self, rec: dict[str, Any]) -> None:
        f = self.fields
        nid = str(_get(rec, f["id"]) or "")
        if not nid:
            self.skipped += 1
            return
        parts = nid.split(f["id_separator"])
        repo = _get(rec, f["repo"]) or (parts[0] if len(parts) >= 5 else "")
        file = _get(rec, f["file"]) or (parts[2] if len(parts) >= 5 else "")
        kind = _get(rec, f["kind"]) or (parts[3] if len(parts) >= 5 else "")
        name = _get(rec, f["name"]) or (f["id_separator"].join(parts[4:]) if len(parts) >= 5 else nid)
        line = _get(rec, f["line"])
        try:
            line_n = int(line) if line is not None else None
        except (TypeError, ValueError):
            line_n = None
        self.nodes[nid] = Node(nid, str(kind), str(file), line_n, str(name), str(repo))

    def _edge(self, rec: dict[str, Any]) -> None:
        f = self.fields
        src, dst = _get(rec, f["from"]), _get(rec, f["to"])
        rel = str(_get(rec, f["relation"]) or "")
        if not src or not dst:
            self.skipped += 1
            return
        conf = _get(rec, f["confidence"])
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        if rel in f["calls"]:
            self.calls_in[str(dst)].append((str(src), conf_f))
        elif rel in f["handles_route"]:
            self.handles[str(src)].append(str(dst))
            self.route_handlers[str(dst)].append(str(src))

    # ---------------------------------------------------------------- the Store surface

    def age_days(self) -> float:
        return (time.time() - os.path.getmtime(self.path)) / 86400

    def _route_nodes(self) -> list[Node]:
        kinds = set(self.fields["route_kinds"])
        return [n for n in self.nodes.values() if n.kind in kinds or n.id in self.route_handlers]

    @staticmethod
    def _route_path(n: Node) -> str:
        m = ROUTE_SUBJECT.match(n.name or "")
        return m.group(2) if m else (n.name if n.name.startswith("/") else "")

    @staticmethod
    def _route_verb(n: Node) -> str:
        m = ROUTE_SUBJECT.match(n.name or "")
        return m.group(1) if m else ""

    def routes_in_file(self, repo: str, file: str) -> list[str]:
        """Routes declared in a file: route nodes in it, or routes whose handler is in it."""
        out: list[str] = []
        base = os.path.basename(file)
        for n in self._route_nodes():
            path = self._route_path(n)
            if not path:
                continue
            files = {n.file} | {self.nodes[h].file for h in self.route_handlers.get(n.id, []) if h in self.nodes}
            repos = {n.repo} | {self.nodes[h].repo for h in self.route_handlers.get(n.id, []) if h in self.nodes}
            if repo and repo not in repos and any(repos):
                continue
            here = any(
                fl == file or fl.endswith("/" + base) or file.endswith("/" + os.path.basename(fl)) for fl in files if fl
            )
            if here and path not in out:
                out.append(path)
        return out

    def gates(self, repo: str, route: str) -> list[Gate]:
        return []  # a code graph records no gate classification

    def whitelist_patterns(self, repo: str) -> list[tuple[str, bool]]:
        return []

    def exposure(self, repo: str) -> tuple[str, str, str] | None:
        return None

    def auth_style(self, repo: str) -> tuple[int, int]:
        return (0, 0)

    def has_gate_data(self, repo: str) -> bool:
        return False

    def caller_count(self, service: str) -> int:
        """CALLS edges into this service's nodes from nodes of another repository."""
        n = 0
        for dst, srcs in self.calls_in.items():
            d = self.nodes.get(dst)
            if d and d.repo == service:
                n += sum(1 for s, _ in srcs if self.nodes.get(s) and self.nodes[s].repo != service)
        return n

    def callers(self, service: str, route: str) -> list[Caller]:
        """Who calls the route: the sources of CALLS edges into its handlers (and into the route node itself)."""
        rt = normalize(route)
        out: list[Caller] = []
        for n in self._route_nodes():
            path = self._route_path(n)
            if not path or not edge_hits_route(path, rt):
                continue
            if (
                service
                and n.repo
                and n.repo != service
                and not any(
                    self.nodes.get(h) and self.nodes[h].repo == service for h in self.route_handlers.get(n.id, [])
                )
            ):
                continue
            targets = [n.id, *self.route_handlers.get(n.id, [])]
            seen: set[str] = set()
            for t in targets:
                for src, _conf in self.calls_in.get(t, []):
                    if src in seen:
                        continue
                    seen.add(src)
                    s = self.nodes.get(src)
                    site = f"{s.file}:{s.line}" if s and s.line is not None else (s.file if s else src)
                    out.append(Caller(s.repo if s else "?", site or "?", self._route_verb(n), path))
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "nodes": len(self.nodes),
            "routes": len(self._route_nodes()),
            "calls_edges": sum(len(v) for v in self.calls_in.values()),
            "handles_route_edges": sum(len(v) for v in self.handles.values()),
            "skipped_lines": self.skipped,
            "repositories": sorted({n.repo for n in self.nodes.values() if n.repo}),
        }


_ = re  # kept for field maps that may add regexes later
