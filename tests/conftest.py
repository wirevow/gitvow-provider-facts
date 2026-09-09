import sqlite3

import pytest

SCHEMA = """
CREATE TABLE fact(id INTEGER PRIMARY KEY, repo TEXT, kind TEXT, subject TEXT, predicate TEXT, object TEXT, file TEXT, line INTEGER, method TEXT, source TEXT, confidence TEXT, reopen_on TEXT, owner TEXT, created TEXT DEFAULT (datetime('now')));
CREATE TABLE edge(id INTEGER PRIMARY KEY, src_repo TEXT, src_site TEXT, dst_service TEXT, dst_path TEXT, verb TEXT, matched_route INTEGER, source TEXT, confidence TEXT);
"""
F = "controller/src/main/java/com/example/OrdersResource.java"


@pytest.fixture
def store(tmp_path):
    p = tmp_path / "facts.db"
    db = sqlite3.connect(p)
    db.executescript(SCHEMA)
    facts = [
        ("orders-svc", "route", "GET /v1/orders", "auth", "AuthenticateV2|AuthorizeV2", F),
        ("orders-svc", "route", "GET /v1/orders/{id}", "auth", "AuthenticateV2|AuthorizeV2", F),
        ("orders-svc", "route", "POST /v1/orders", "auth", "AuthenticateV2|AuthorizeV2", F),
        ("orders-svc", "route_gate", "GET /v1/orders", "gate", "reachable:AuthorizeV2", F),
        ("orders-svc", "route_gate", "GET /v1/orders/{id}", "gate", "reachable:AuthorizeV2", F),
        ("orders-svc", "route_gate", "POST /v1/orders", "gate", "reachable:AuthorizeV2", F),
        (
            "orders-svc",
            "route_gate",
            "GET /v1/webhook/stripe",
            "gate",
            "OPEN:whitelisted,no-auth-annotation via v1/webhook/*",
            "controller/WebhookResource.java",
        ),
        (
            "orders-svc",
            "route_gate",
            "GET /myadmin/users",
            "gate",
            "reachable:whitelisted+authn via myadmin/*",
            "controller/AdminResource.java",
        ),
        (
            "orders-svc",
            "route_gate",
            "GET /v1/legacy/dump",
            "gate",
            "BLOCKED:403-by-gate",
            "controller/LegacyResource.java",
        ),
        ("other-svc", "route", "GET /x", "auth", "", "x.py"),
    ]
    db.executemany("insert into fact(repo,kind,subject,predicate,object,file) values (?,?,?,?,?,?)", facts)
    edges = [
        ("client-orch", "src/OrdersClient.java:88", "orders", "/v1/orders", "POST", 1),
        ("billing-worker", "sync.py:41", "orders", "/v1/orders/{orderId}", "GET", 1),
        ("someone", "a.go:1", "payments", "/v1/orders", "GET", 1),
    ]
    db.executemany(
        "insert into edge(src_repo,src_site,dst_service,dst_path,verb,matched_route) values (?,?,?,?,?,?)", edges
    )
    db.commit()
    db.close()
    return str(p)
