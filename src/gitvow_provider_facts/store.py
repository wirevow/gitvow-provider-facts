"""Read-only queries over the fact store."""

from __future__ import annotations

import fnmatch
import os
import re
import sqlite3
import time
from dataclasses import dataclass

ROUTE_SUBJECT = re.compile(r"^(\w+)\s+(/\S*)$")


def normalize(path: str) -> str:
    p = re.sub(r"\{[^}]*\}", "{}", path.strip())
    p = re.sub(r"/{2,}", "/", p)
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p or "/"


def route_matches(pattern: str, route: str) -> bool:
    """Whitelist-style match: leading slash optional, trailing '*' matches any depth, {} matches one segment."""
    pat = normalize("/" + pattern.lstrip("/"))
    rt = normalize(route)
    if pat.endswith("/*"):
        base = pat[:-2]
        return rt == base or rt.startswith(base + "/")
    if pat.endswith("*"):
        return rt.startswith(pat[:-1])
    ps, rs = pat.split("/"), rt.split("/")
    if len(ps) != len(rs):
        return False
    return all(a == b or a == "{}" or b == "{}" or fnmatch.fnmatchcase(b, a) for a, b in zip(ps, rs))


def edge_hits_route(edge_path: str, route: str) -> bool:
    """Does a recorded call to edge_path reach route? A route parameter accepts any caller segment;
    a caller parameter only matches a route parameter, never a literal segment."""
    es, rs = normalize(edge_path).split("/"), normalize(route).split("/")
    if len(es) != len(rs):
        return False
    for e, r in zip(es, rs):
        if r == "{}":
            continue
        if e == "{}" or e != r:
            return False
    return True


@dataclass
class Gate:
    verb: str
    route: str
    classification: str
    file: str

    @property
    def exposed(self) -> bool:
        return self.classification.startswith(("OPEN", "BLOCKED"))

    @property
    def pattern(self) -> str | None:
        m = re.search(r"\bvia\s+(\S+)", self.classification)
        return m.group(1) if m else None


@dataclass
class Caller:
    repo: str
    site: str
    verb: str
    path: str

    def text(self) -> str:
        return f"{self.repo} ({self.site}) {self.verb}".rstrip()


class Store:
    def __init__(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        self.path = path
        uri = f"file:{os.path.abspath(path)}?mode=ro"
        self.db = sqlite3.connect(uri, uri=True)

    def age_days(self) -> float:
        return (time.time() - os.path.getmtime(self.path)) / 86400

    def routes_in_file(self, repo: str, file: str) -> list[str]:
        rows = self.db.execute(
            "select subject from fact where repo=? and kind in ('route','route_gate') and (file=? or file like ?)",
            (repo, file, f"%/{os.path.basename(file)}"),
        ).fetchall()
        out: list[str] = []
        for (subj,) in rows:
            m = ROUTE_SUBJECT.match(subj or "")
            if m and m.group(2) not in out:
                out.append(m.group(2))
        return out

    def gates(self, repo: str, route: str) -> list[Gate]:
        rt = normalize(route)
        out: list[Gate] = []
        for subj, obj, file in self.db.execute(
            "select subject, object, file from fact where repo=? and kind='route_gate'", (repo,)
        ):
            m = ROUTE_SUBJECT.match(subj or "")
            if m and normalize(m.group(2)) == rt:
                out.append(Gate(m.group(1), m.group(2), obj or "", file or ""))
        return out

    def whitelist_patterns(self, repo: str) -> list[tuple[str, bool]]:
        """(pattern, authenticated) pairs seen in this repo's gate classifications."""
        seen: dict[str, bool] = {}
        for (obj,) in self.db.execute("select distinct object from fact where repo=? and kind='route_gate'", (repo,)):
            m = re.search(r"\bvia\s+(\S+)", obj or "")
            if m:
                seen[m.group(1)] = not (obj or "").startswith("OPEN")
        return sorted(seen.items())

    def has_gate_data(self, repo: str) -> bool:
        return (
            self.db.execute("select 1 from fact where repo=? and kind='route_gate' limit 1", (repo,)).fetchone()
            is not None
        )

    def callers(self, service: str, route: str) -> list[Caller]:
        rt = normalize(route)
        out: list[Caller] = []
        for src_repo, src_site, dst_path, verb in self.db.execute(
            "select src_repo, src_site, dst_path, coalesce(verb,'') from edge where dst_service=?", (service,)
        ):
            if dst_path and edge_hits_route(dst_path, rt):
                out.append(Caller(src_repo or "?", src_site or "?", verb, dst_path or ""))
        return out
