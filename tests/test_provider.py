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
