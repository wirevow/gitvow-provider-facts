"""The graph source (0.3): the same questions from an NDJSON code graph; what the graph does not know stays unknown."""

import json
import os
import subprocess
import sys
import time

import pytest

from gitvow_provider_facts import cli
from gitvow_provider_facts.graph import GraphStore, load_fields
from gitvow_provider_facts.provider import Config, answer

F = "api/orders.py"


def _rec(**kw):
    return json.dumps(kw)


@pytest.fixture
def graph(tmp_path):
    p = tmp_path / "export.ndjson"
    lines = [
        # ids carry repo:lang:file:kind:name; the fields are also given explicitly on some, read from the id on others
        _rec(
            type="node",
            id="orders-svc:py:api/orders.py:function:list_orders",
            kind="function",
            file=F,
            line=12,
            name="list_orders",
            repo="orders-svc",
        ),
        _rec(type="node", id="orders-svc:py:api/orders.py:function:get_order"),  # everything from the id
        _rec(type="node", id="orders-svc:py:api/orders.py:route:GET /v1/orders", kind="route", name="GET /v1/orders"),
        _rec(
            type="node",
            id="orders-svc:py:api/orders.py:route:GET /v1/orders/{id}",
            kind="route",
            name="GET /v1/orders/{id}",
        ),
        _rec(
            type="node",
            id="orders-svc:py:api/export.py:route:POST /v1/orders/export",
            kind="route",
            name="POST /v1/orders/export",
        ),
        _rec(
            type="node",
            id="client-orch:java:src/OrdersClient.java:method:fetch",
            file="src/OrdersClient.java",
            line=88,
            name="fetch",
            repo="client-orch",
            kind="method",
        ),
        _rec(type="node", id="billing-worker:py:sync.py:function:pull", line=41),
        _rec(type="node", id="orders-svc:py:api/internal.py:function:helper", line=3),
        _rec(
            type="edge",
            **{"from": "orders-svc:py:api/orders.py:function:list_orders"},
            to="orders-svc:py:api/orders.py:route:GET /v1/orders",
            relation="HANDLES_ROUTE",
            confidence=1.0,
        ),
        _rec(
            type="edge",
            **{"from": "orders-svc:py:api/orders.py:function:get_order"},
            to="orders-svc:py:api/orders.py:route:GET /v1/orders/{id}",
            relation="HANDLES_ROUTE",
        ),
        _rec(
            type="edge",
            **{"from": "client-orch:java:src/OrdersClient.java:method:fetch"},
            to="orders-svc:py:api/orders.py:function:list_orders",
            relation="CALLS",
            confidence=0.9,
        ),
        _rec(
            type="edge",
            **{"from": "billing-worker:py:sync.py:function:pull"},
            to="orders-svc:py:api/orders.py:function:get_order",
            relation="CALLS",
        ),
        _rec(
            type="edge",
            **{"from": "orders-svc:py:api/internal.py:function:helper"},
            to="orders-svc:py:api/orders.py:function:list_orders",
            relation="CALLS",
        ),  # same repo: not a service caller
        _rec(
            type="edge",
            **{"from": "orders-svc:py:api/orders.py:function:list_orders"},
            to="orders-svc:py:api/internal.py:function:helper",
            relation="IMPORTS",
        ),  # another relation, ignored
        "not json at all",
        json.dumps([1, 2]),
    ]
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_graph_store_reads_nodes_edges_routes_and_callers(graph):
    g = GraphStore(graph)
    s = g.summary()
    assert (
        s["nodes"] == 8
        and s["routes"] == 3
        and s["calls_edges"] == 3
        and s["handles_route_edges"] == 2
        and s["skipped_lines"] == 2
    )
    assert s["repositories"] == ["billing-worker", "client-orch", "orders-svc"]
    n = g.nodes["orders-svc:py:api/orders.py:function:get_order"]
    assert (n.repo, n.file, n.kind, n.name, n.line) == ("orders-svc", F, "function", "get_order", None)
    assert g.routes_in_file("orders-svc", F) == ["/v1/orders", "/v1/orders/{id}"]
    assert g.routes_in_file("orders-svc", "api/export.py") == ["/v1/orders/export"]
    assert g.routes_in_file("other", F) == []
    c = g.callers("orders-svc", "/v1/orders")
    assert [(x.repo, x.site, x.verb) for x in c] == [
        ("client-orch", "src/OrdersClient.java:88", "GET"),
        ("orders-svc", "api/internal.py:3", "GET"),
    ]
    c = g.callers("orders-svc", "/v1/orders/{orderId}")  # a caller's parameter matches the route's parameter
    assert [(x.repo, x.site) for x in c] == [("billing-worker", "sync.py:41")]
    assert g.callers("orders-svc", "/v1/orders/export") == [] and g.callers("other-svc", "/v1/orders") == []
    assert g.caller_count("orders-svc") == 2  # the helper is the same repository
    assert (
        g.gates("orders-svc", "/v1/orders") == []
        and not g.has_gate_data("orders-svc")
        and g.exposure("orders-svc") is None
    )
    assert g.whitelist_patterns("orders-svc") == [] and g.auth_style("orders-svc") == (0, 0)


def test_answers_from_the_graph_say_what_a_graph_cannot_know(graph):
    c = Config(graph=graph, service="orders-svc", repo="orders-svc", gate_files=["auth/**"])
    r = answer(c, {"question": "route_callers", "subject": "/v1/orders", "path": F})
    assert r["answer"] == "yes" and any("client-orch (src/OrdersClient.java:88) GET" in e for e in r["evidence"])
    assert r["evidence"][-1].startswith("graph exported 0 days ago")
    r = answer(c, {"question": "route_callers", "subject": "/{id}", "path": F})  # method-level literal + class prefix
    assert (
        r["answer"] == "yes"
        and any("billing-worker" in e for e in r["evidence"])
        and "prefix /v1/orders" in r["evidence"][0]
    )
    r = answer(c, {"question": "route_callers", "subject": "/v1/orders/export", "path": "api/export.py"})
    assert r["answer"] == "unknown" and "no recorded callers" in r["evidence"][1]
    r = answer(c, {"question": "route_gate", "subject": "/v1/orders", "path": F})
    assert r["answer"] == "unknown" and "no gate classification recorded" in r["evidence"][1]
    assert answer(c, {"question": "gate_bearing", "subject": "x", "path": "auth/filter.py"})["answer"] == "yes"
    assert answer(c, {"question": "gate_bearing", "subject": "x", "path": "README.md"})["answer"] == "no"
    old = time.time() - 40 * 86400
    os.utime(graph, (old, old))
    r = answer(c, {"question": "route_callers", "subject": "/v1/orders", "path": F})
    assert "STALE: rebuild the graph" in r["evidence"][-1]


def test_field_map_covers_a_graph_that_spells_things_differently(tmp_path):
    p = tmp_path / "g.ndjson"
    p.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "svc|py|h.py|fn|handle",
                        "repo": "svc",
                        "file": "h.py",
                        "line": 5,
                        "kind": "fn",
                        "name": "handle",
                    }
                ),
                json.dumps(
                    {
                        "id": "svc|py|h.py|endpoint|/v1/x",
                        "repo": "svc",
                        "file": "h.py",
                        "kind": "endpoint",
                        "name": "/v1/x",
                    }
                ),
                json.dumps(
                    {
                        "id": "other|py|c.py|fn|go",
                        "repo": "other",
                        "file": "c.py",
                        "line": 9,
                        "kind": "fn",
                        "name": "go",
                    }
                ),
                json.dumps(
                    {"source": "svc|py|h.py|fn|handle", "target": "svc|py|h.py|endpoint|/v1/x", "label": "handles"}
                ),
                json.dumps({"source": "other|py|c.py|fn|go", "target": "svc|py|h.py|fn|handle", "label": "calls"}),
            ]
        )
    )
    fm = tmp_path / "fields.json"
    fm.write_text(
        json.dumps(
            {
                "from": ["source"],
                "to": ["target"],
                "relation": ["label"],
                "calls": ["calls"],
                "handles_route": ["handles"],
                "route_kinds": ["endpoint"],
                "id_separator": "|",
            }
        )
    )
    g = GraphStore(str(p), load_fields(str(fm)))
    assert g.summary()["routes"] == 1 and g.routes_in_file("svc", "h.py") == ["/v1/x"]
    assert [(x.repo, x.site) for x in g.callers("svc", "/v1/x")] == [("other", "c.py:9")]


def test_cli_graph_source_and_subprocess(graph, tmp_path, capsys):
    assert (
        cli.main(
            [
                "--graph",
                graph,
                "--service",
                "orders-svc",
                "--repo",
                "orders-svc",
                "ask",
                "route_callers",
                "/v1/orders",
                "--path",
                F,
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["answer"] == "yes"
    assert cli.main(["--graph", str(tmp_path / "missing.ndjson"), "ask", "route_callers", "/v1/orders"]) == 3
    assert "graph not found" in capsys.readouterr().err
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "gitvow_provider_facts.cli",
            "--graph",
            graph,
            "--service",
            "orders-svc",
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
    with pytest.raises(SystemExit):
        cli.main(["--store", "a.db", "--graph", "b.ndjson", "ask", "route_callers", "/x"])  # one source, not both
