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

No runtime dependencies: Python 3.9+ and sqlite3 from the standard library. The provider holds no knowledge of its own; it reads a store you build. It never writes to the store and never contacts the network.

Documentation: **https://wirevow.dev/gitvow-provider-facts/** · Protocol it implements: [gitvow provider protocol](https://wirevow.dev/gitvow/reference/provider-protocol/)

Apache-2.0.
