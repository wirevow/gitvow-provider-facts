# gitvow-provider-facts

A [gitvow](https://wirevow.dev/gitvow/) provider that answers the gate's questions from a derived fact store of your services: which routes exist, how each is gated, and who calls it.

With it, an agent that adds an endpoint the authorization layer does not cover, or removes one that other services call, is stopped before the file changes, and the message names the whitelist pattern or the calling services.

```sh
pip install gitvow-provider-facts
```

```json
"providers": [{
  "name": "topology",
  "command": "gitvow-provider-facts --store /var/lib/topology/facts.db --service orders",
  "questions": ["route_gate", "route_callers", "gate_bearing"]
}]
```

```
$ gitvow ask route_callers /v1/orders --path src/api/OrdersResource.java
topology: yes — called by client-orch (OrdersClient.java:88) POST; called by billing-worker (sync.py:41) GET; store built 2026-09-08 (1 day old)
decision: CONFIRM
```

Or point it at a code graph instead of a fact store. Any tool that exports its graph as NDJSON, nodes and edges with stable ids and `file:line`, feeds it; `CALLS` edges into a route's handler are the callers, `HANDLES_ROUTE` edges name the routes a file declares. A graph has no gate classification, so `route_gate` comes back `unknown` with the reason, and `gate_bearing` still uses your gate files.

```json
"providers": [{
  "name": "graph",
  "command": "gitvow-provider-facts --graph .graph/export.ndjson --service orders --gate-file 'auth/**'",
  "questions": ["route_callers", "gate_bearing"]
}]
```

No runtime dependencies: Python 3.9+ and sqlite3 from the standard library. The provider holds no knowledge of its own; it reads a store you build. It never writes to the store and never contacts the network.

Documentation: **https://wirevow.dev/gitvow-provider-facts/** · Protocol it implements: [gitvow provider protocol](https://wirevow.dev/gitvow/reference/provider-protocol/)

Apache-2.0.
