import json
import os
import subprocess
import sys
import time

from gitvow_provider_facts.cli import main
from gitvow_provider_facts.provider import Config, answer, resolve_route
from gitvow_provider_facts.store import Store, edge_hits_route, normalize, route_matches
from tests.conftest import F


def test_normalize_and_matching():
    assert normalize("/v1/orders/{id}/") == "/v1/orders/{}"
    assert normalize("//a//b") == "/a/b"
    assert route_matches("v1/webhook/*", "/v1/webhook/stripe/x")
    assert route_matches("v1/webhook/*", "/v1/webhook")
    assert not route_matches("v1/webhook/*", "/v1/webhooks")
    assert route_matches("/v1/orders/{orderId}", "/v1/orders/{id}")
    assert route_matches("/v1/orders/{id}", "/v1/orders/42")
    assert not route_matches("/v1/orders", "/v1/orders/42")
    assert edge_hits_route("/v1/orders/42", "/v1/orders/{id}")  # concrete call reaches the parameterised route
    assert edge_hits_route("/v1/orders/{orderId}", "/v1/orders/{id}")
    assert not edge_hits_route(
        "/v1/orders/{orderId}", "/v1/orders/export"
    )  # a caller of the id route is not a caller of export
    assert not edge_hits_route("/v1/orders", "/v1/orders/{id}")


def test_resolve_prefix_from_file(store):
    st = Store(store)
    assert resolve_route(st, "orders-svc", "/export", F) == (
        "/v1/orders/export",
        "prefix /v1/orders from OrdersResource.java",
    )
    assert resolve_route(st, "orders-svc", "/v1/orders/{id}", F) == ("/v1/orders/{}", "exact")
    assert resolve_route(st, "orders-svc", "/v1/orders/export", F) == ("/v1/orders/export", "as written")
    assert resolve_route(st, "orders-svc", "/export", "unknown.java") == ("/export", "as written")


def cfg(store, **kw):
    return Config(store, repo="orders-svc", service="orders", **kw)


def test_route_gate_answers(store):
    c = cfg(store)
    r = answer(c, {"question": "route_gate", "subject": "/export", "path": F})
    assert (
        r["answer"] == "yes"
        and "403" in " ".join(r["evidence"])
        and "resolved to /v1/orders/export" in r["evidence"][0]
    )
    r = answer(c, {"question": "route_gate", "subject": "/{id}", "path": F})
    assert r["answer"] == "no" and "reachable:AuthorizeV2" in r["evidence"][1]
    r = answer(c, {"question": "route_gate", "subject": "/v1/webhook/new", "path": "controller/WebhookResource.java"})
    assert r["answer"] == "yes" and "OPEN" in r["evidence"][1]
    r = answer(c, {"question": "route_gate", "subject": "/myadmin/reports", "path": "controller/AdminResource.java"})
    assert r["answer"] == "no" and "authenticated whitelist" in r["evidence"][1]
    r = answer(c, {"question": "route_gate", "subject": "/v1/legacy/dump", "path": ""})
    assert r["answer"] == "yes" and "BLOCKED" in r["evidence"][1]
    r = answer(Config(store, repo="other-svc"), {"question": "route_gate", "subject": "/y", "path": "x.py"})
    assert r["answer"] == "unknown" and "no gate classification" in r["evidence"][1]


def test_route_callers(store):
    c = cfg(store)
    r = answer(c, {"question": "route_callers", "subject": "/v1/orders", "path": F})
    assert r["answer"] == "yes" and any("client-orch (src/OrdersClient.java:88) POST" in e for e in r["evidence"])
    assert not any("someone" in e for e in r["evidence"])  # different service
    r = answer(c, {"question": "route_callers", "subject": "/{id}", "path": F})
    assert r["answer"] == "yes" and any("billing-worker" in e for e in r["evidence"])
    r = answer(c, {"question": "route_callers", "subject": "/v1/orders/export", "path": F})
    assert r["answer"] == "unknown" and "no recorded callers" in r["evidence"][1]


def test_gate_bearing_and_age(store):
    c = cfg(store, gate_files=["auth/AuthorizeWhitelistedPaths.java", "deploy/values/production-*.yaml"])
    assert (
        answer(c, {"question": "gate_bearing", "subject": "x", "path": "svc/auth/AuthorizeWhitelistedPaths.java"})[
            "answer"
        ]
        == "yes"
    )
    assert (
        answer(c, {"question": "gate_bearing", "subject": "x", "path": "deploy/values/production-in.yaml"})["answer"]
        == "yes"
    )
    assert answer(c, {"question": "gate_bearing", "subject": "x", "path": "README.md"})["answer"] == "no"
    assert answer(cfg(store), {"question": "gate_bearing", "subject": "x", "path": "README.md"})["answer"] == "unknown"
    old = time.time() - 40 * 86400
    os.utime(store, (old, old))
    r = answer(cfg(store), {"question": "route_callers", "subject": "/v1/orders", "path": F})
    assert "STALE" in r["evidence"][-1] and "40 days ago" in r["evidence"][-1]
    assert answer(c, {"question": "bogus", "subject": "x"})["answer"] == "unknown"


def test_cli_stdin_and_ask(store, capsys, monkeypatch, tmp_path):
    import io

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "protocol": 1,
                    "question": "route_callers",
                    "subject": "/v1/orders",
                    "path": F,
                    "repo": str(tmp_path / "orders-svc"),
                }
            )
        ),
    )
    assert main(["--store", store, "--service", "orders"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["answer"] == "yes"
    assert main(["--store", store, "--repo", "orders-svc", "ask", "route_gate", "/export", "--path", F]) == 0
    assert json.loads(capsys.readouterr().out)["answer"] == "yes"
    assert main(["--store", "/nonexistent.db", "ask", "route_gate", "/x"]) == 3
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert main(["--store", store]) == 2


def test_store_is_opened_read_only(store):
    st = Store(store)
    try:
        st.db.execute("insert into fact(repo) values ('x')")
        raise AssertionError("write should fail")
    except Exception as e:
        assert "readonly" in str(e).lower() or "read-only" in str(e).lower()


def test_works_with_gitvow_as_subprocess(store, tmp_path):
    """The real integration: gitvow's gate calls the console script and reads the answer."""
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "gitvow_provider_facts.cli",
            "--store",
            store,
            "--service",
            "orders",
            "--repo",
            "orders-svc",
        ],
        input=json.dumps(
            {"protocol": 1, "question": "route_callers", "subject": "/v1/orders", "path": F, "repo": str(tmp_path)}
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(r.stdout)["answer"] == "yes"


def _add_exposure(store, repo, env, klass, file="values/production-in/x/values.yaml"):
    import sqlite3

    db = sqlite3.connect(store)
    db.execute(
        "insert into fact(repo,kind,subject,predicate,object,file) values (?,?,?,?,?,?)",
        (repo, "exposure", env, "exposed_as", klass, file),
    )
    db.commit()
    db.close()


def _add_routes(store, repo, rows):
    import sqlite3

    db = sqlite3.connect(store)
    db.executemany(
        "insert into fact(repo,kind,subject,predicate,object,file) values (?,?,?,?,?,?)",
        [(repo, k, s, "x", o, f) for k, s, o, f in rows],
    )
    db.commit()
    db.close()


def test_estate_vocabulary_recorded_gates(store):
    _add_routes(
        store,
        "internal-svc",
        [
            ("route", "GET /v1/jobs", "", "app/api.py"),
            ("route_gate", "GET /v1/jobs", "OPEN:internal-gateway,no-auth @production-in", "app/api.py"),
            ("route", "GET /v1/inner", "", "app/inner.py"),
            ("route_gate", "GET /v1/inner", "internal:cluster-only,trusted-caller @production-in", "app/inner.py"),
        ],
    )
    import sqlite3

    db = sqlite3.connect(store)
    db.execute(
        "insert into edge(src_repo,src_site,dst_service,dst_path,verb,matched_route) values ('a','x:1','internal-svc','/v1/inner','GET',1)"
    )
    db.commit()
    db.close()
    c = Config(store, repo="internal-svc", service="internal-svc")
    r = answer(c, {"question": "route_gate", "subject": "/v1/jobs", "path": "app/api.py"})
    assert r["answer"] == "yes" and "internal-gateway" in r["evidence"][1]
    r = answer(c, {"question": "route_gate", "subject": "/v1/inner", "path": "app/inner.py"})
    assert r["answer"] == "no" and "cluster-only; 1 recorded callers" in r["evidence"][2]


def test_new_route_classified_from_exposure(store):
    # an internal-gateway Java service with no auth anywhere: a new route is reachable without auth -> yes
    _add_routes(
        store,
        "svc-a",
        [
            ("route", "GET /v1/a", "", "A.java"),
            ("route_gate", "GET /v1/a", "OPEN:internal-gateway,no-auth @production-in", "A.java"),
        ],
    )
    _add_exposure(store, "svc-a", "production-in", "internal")
    r = answer(
        Config(store, repo="svc-a", service="svc-a"), {"question": "route_gate", "subject": "/v1/new", "path": "A.java"}
    )
    assert r["answer"] == "yes" and "company network" in r["evidence"][1] and "production-in" in r["evidence"][1]
    # a cluster-only service: new route is not reachable from outside the mesh -> no, with caller count
    _add_routes(
        store,
        "svc-b",
        [
            ("route", "GET /x", "", "b.py"),
            ("route_gate", "GET /x", "internal:cluster-only,trusted-caller @production-us", "b.py"),
        ],
    )
    _add_exposure(store, "svc-b", "production-us", "cluster-only")
    r = answer(
        Config(store, repo="svc-b", service="svc-b"), {"question": "route_gate", "subject": "/y", "path": "b.py"}
    )
    assert r["answer"] == "no" and "cluster-only" in r["evidence"][1] and "recorded callers" in r["evidence"][2]
    # a per-route-authenticated FastAPI service: unknown, tell the agent to add the dependency
    _add_routes(
        store,
        "svc-c",
        [
            ("route", "GET /p", "require_org_request_context", "c.py"),
            ("route", "GET /q", "require_org_request_context", "c.py"),
            ("route_gate", "GET /p", "reachable:internal,require_org_request_context @production-in", "c.py"),
        ],
    )
    _add_exposure(store, "svc-c", "production-in", "internal")
    r = answer(
        Config(store, repo="svc-c", service="svc-c"), {"question": "route_gate", "subject": "/r", "path": "c.py"}
    )
    assert r["answer"] == "unknown" and "authenticates per route" in r["evidence"][1]
    # strongest exposure wins across environments
    _add_exposure(store, "svc-a", "production-us", "external")
    r = answer(
        Config(store, repo="svc-a", service="svc-a"),
        {"question": "route_gate", "subject": "/v1/new2", "path": "A.java"},
    )
    assert r["answer"] == "yes" and "internet" in r["evidence"][1] and "production-us" in r["evidence"][1]
