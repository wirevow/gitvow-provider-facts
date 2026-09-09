# gitvow-provider-facts

The gate in [gitvow](https://wirevow.dev/gitvow/) can ask an external program three questions before an agent edits a file: is this file gate-bearing, would this new route be exposed without the expected authorization, does this removed route have callers. This provider answers them from a **fact store**: a SQLite database of facts derived from your repositories by static analysis, describing routes, their gating, and the calls between services.

## What it answers

| Question | Answer from the store |
|---|---|
| `route_gate` | Resolves the edited literal to a full route using the routes already recorded for the same file, then classifies it: an existing route reports its recorded gate; a new route is matched against the whitelist patterns the store knows, or, where a repository has none, against the deployment's exposure and the authentication style of its existing routes. `yes` when the route would be reachable without authentication from outside the mesh, or blocked by a gate because no pattern covers it. |
| `route_callers` | Inbound edges whose destination is this service and whose path matches the route, parameters included. `yes` when at least one caller exists, naming each calling repository, call site and verb. |
| `gate_bearing` | Files you name with `--gate-file` globs (authorization filters, whitelists, production values). The store does not record which files gate; you do. |

Every answer carries the store's age, so a stale store is visible in the message the agent sees.

## Why a store rather than live analysis
Static analysis of an estate takes minutes to hours and needs the source of every service. The gate has a fraction of a second and sees one repository. Building the store is a batch job; answering from it is a lookup. The [store](store.md) page describes the schema and how to keep it fresh.

## Honest limits
The provider knows what the store knows. A route added since the store was built is "new" to it; a caller added since is invisible. It resolves class-level path prefixes only when the file already has recorded routes. It answers `unknown` rather than guessing, and gitvow treats `unknown` as no evidence.
