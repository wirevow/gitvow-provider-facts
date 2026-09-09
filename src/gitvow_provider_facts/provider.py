"""Answer gitvow provider questions from a Store."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from typing import Any

from .store import Store, normalize, route_matches


@dataclass
class Config:
    store: str
    repo: str = ""
    service: str = ""
    gate_files: list[str] = field(default_factory=list)
    max_age_days: float = 14


def _age_evidence(st: Store, cfg: Config) -> str:
    days = st.age_days()
    warn = " (STALE: rebuild the store)" if days > cfg.max_age_days else ""
    return f"store built {int(days)} day{'s' if int(days) != 1 else ''} ago{warn}"


def resolve_route(st: Store, repo: str, literal: str, path: str) -> tuple[str, str]:
    """Return (full route, how). Combine a method-level literal with the class-level prefix implied by the file."""
    lit = normalize(literal)
    known = [normalize(r) for r in st.routes_in_file(repo, path)] if path else []
    if lit in known:
        return lit, "exact"
    # longest common prefix of the file's known routes is the class-level @Path
    if known:
        segs = [r.split("/") for r in known]
        prefix: list[str] = []
        for parts in zip(*segs):
            if all(p == parts[0] for p in parts):
                prefix.append(parts[0])
            else:
                break
        pre = "/".join(prefix)
        if pre and pre != "/" and not lit.startswith(pre + "/") and lit != pre:
            return normalize(pre + "/" + lit.lstrip("/")), f"prefix {pre} from {os.path.basename(path)}"
    return lit, "as written"


def answer(cfg: Config, req: dict[str, Any]) -> dict[str, Any]:
    st = Store(cfg.store)
    q = req.get("question")
    subject = str(req.get("subject") or "")
    path = str(req.get("path") or "")
    repo = cfg.repo or os.path.basename(str(req.get("repo") or "").rstrip("/"))
    service = cfg.service or repo
    age = _age_evidence(st, cfg)
    if q == "gate_bearing":
        hit = [g for g in cfg.gate_files if fnmatch.fnmatch(path, g) or path.endswith(g)]
        if hit:
            return {"answer": "yes", "evidence": [f"gate-bearing file ({hit[0]})", age], "confidence": 1.0}
        return {"answer": "no" if cfg.gate_files else "unknown", "evidence": [age], "confidence": 0.5}
    if q not in ("route_gate", "route_callers"):
        return {"answer": "unknown", "evidence": ["unsupported question"], "confidence": 0.0}
    route, how = resolve_route(st, repo, subject, path)
    resolved = f"resolved to {route} ({how})" if route != normalize(subject) else f"route {route}"
    if q == "route_callers":
        callers = st.callers(service, route)
        if callers:
            ev = [resolved] + [f"called by {c.text()}" for c in callers[:6]]
            if len(callers) > 6:
                ev.append(f"and {len(callers) - 6} more callers")
            return {"answer": "yes", "evidence": [*ev, age], "confidence": 0.9}
        return {
            "answer": "unknown",
            "evidence": [resolved, f"no recorded callers into service {service}", age],
            "confidence": 0.5,
        }
    gates = st.gates(repo, route)
    if gates:
        exposed = [g for g in gates if g.exposed]
        if exposed:
            g = exposed[0]
            return {
                "answer": "yes",
                "evidence": [resolved, f"recorded gate: {g.classification}", f"declared in {g.file}", age],
                "confidence": 0.9,
            }
        return {
            "answer": "no",
            "evidence": [resolved, f"recorded gate: {gates[0].classification}", age],
            "confidence": 0.9,
        }
    if not st.has_gate_data(repo):
        return {
            "answer": "unknown",
            "evidence": [resolved, f"no gate classification recorded for repo {repo}", age],
            "confidence": 0.3,
        }
    for pattern, authenticated in st.whitelist_patterns(repo):
        if route_matches(pattern, route):
            if authenticated:
                return {
                    "answer": "no",
                    "evidence": [resolved, f"new route; covered by authenticated whitelist pattern {pattern}", age],
                    "confidence": 0.8,
                }
            return {
                "answer": "yes",
                "evidence": [
                    resolved,
                    f"new route; whitelist pattern {pattern} makes it OPEN without authentication",
                    age,
                ],
                "confidence": 0.8,
            }
    return {
        "answer": "yes",
        "evidence": [
            resolved,
            "new route; no whitelist pattern covers it, so the gate would return 403 until it is whitelisted",
            age,
        ],
        "confidence": 0.7,
    }
