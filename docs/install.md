# Install and configure

```sh
pip install gitvow-provider-facts
gitvow-provider-facts --store facts.db --service orders ask route_callers /v1/orders
```

## Options

| Option | Default | Meaning |
|---|---|---|
| `--store PATH` | required | the SQLite fact store |
| `--repo NAME` | basename of the repository gitvow passes | the `repo` value used in `fact` rows for this repository |
| `--service NAME` | same as `--repo` | the `dst_service` value used in `edge` rows for calls into this repository |
| `--gate-file GLOB` | none | repeatable; files that answer `gate_bearing` with `yes` |
| `--max-age-days N` | 14 | above this, answers add a staleness warning to the evidence |

## A code graph instead of a fact store

`--graph graph.ndjson` reads a code graph exported as NDJSON, one record per line: nodes with a stable id, kind, file, line, name and repository, and edges with `from`, `to` and a relation. The defaults follow the compound-v1 convention, where an id is `<repo>:<lang>:<file>:<kind>:<name>` and a node missing a field has it read out of its id. Routes are nodes of kind `route` (name `GET /v1/orders`) or the targets of `HANDLES_ROUTE` edges; callers are the sources of `CALLS` edges into a route's handler, reported at their file and line. A graph whose keys differ takes `--graph-fields fields.json`:

```json
{"from": ["source"], "to": ["target"], "relation": ["label"], "calls": ["calls", "CALLS"], "handles_route": ["handles"], "route_kinds": ["endpoint"]}
```

A graph records no gate classification, deployment exposure or whitelist, so `route_gate` answers `unknown` with that reason; `gate_bearing` is answered from `--gate-file` as before. The age in every answer is the export file's age.

## Wire into gitvow

In `.gitvow/policy.json` of the repository, or `~/.gitvow/policy.json`:

```json
{
  "providers": [
    {
      "name": "topology",
      "command": "gitvow-provider-facts --store /var/lib/topology/facts.db --repo amnic-orders --service orders --gate-file auth/AuthorizeWhitelistedPaths.java",
      "questions": ["route_gate", "route_callers", "gate_bearing"],
      "timeout": 10
    }
  ]
}
```

Then test from the repository:

```sh
gitvow ask route_gate /export --path src/api/OrdersResource.java
gitvow ask route_callers /v1/orders/{id}
```

## Running the provider by hand

`gitvow-provider-facts ... ask <question> <subject> [--path FILE]` prints the JSON answer. Without `ask` it reads a gitvow request on stdin, which is how gitvow calls it.
