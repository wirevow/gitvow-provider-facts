# The fact store

A SQLite file with two tables. Any tool that fills them works; the reference producer is a static-analysis pipeline over compiler-level code graphs, but a hand-written store is enough to start.

```sql
CREATE TABLE fact(
  id INTEGER PRIMARY KEY, repo TEXT, kind TEXT, subject TEXT, predicate TEXT, object TEXT,
  file TEXT, line INTEGER, method TEXT, source TEXT, confidence TEXT, reopen_on TEXT, owner TEXT,
  created TEXT DEFAULT (datetime('now')));
CREATE TABLE edge(
  id INTEGER PRIMARY KEY, src_repo TEXT, src_site TEXT, dst_service TEXT, dst_path TEXT,
  verb TEXT, matched_route INTEGER, source TEXT, confidence TEXT);
```

## Rows the provider reads

| Table | kind | subject | object | file | Used for |
|---|---|---|---|---|---|
| fact | `route` | `GET /v1/orders/{id}` | authentication annotation, may be empty | file declaring the route | prefix resolution |
| fact | `route_gate` | `GET /v1/orders/{id}` | gate classification, see below | file declaring the route | route_gate |
| edge | | `src_repo`, `src_site` (`file:line`), `dst_service`, `dst_path`, `verb` | | | route_callers |

Gate classification strings the provider understands:

| Object | Meaning | `route_gate` answer |
|---|---|---|
| `reachable:AuthorizeV2` | authorized by the standard filter | no |
| `reachable:AuthorizeV2 via <pattern>` | authorized, whitelist pattern also applies | no |
| `reachable:whitelisted+authn via <pattern>` | authenticated through a whitelist pattern | no |
| `OPEN:... via <pattern>` | reachable without authentication | **yes** |
| `BLOCKED:...` | no filter covers it; the gate returns 403 | **yes** |
| `reachable:external,<deps>` / `reachable:internal,<deps>` | exposed service, route checks an auth dependency | no |
| `OPEN:external,no-auth` | internet-exposed service, route has no authentication | **yes** |
| `OPEN:internal-gateway,no-auth` | reachable from the company network without authentication | **yes**, evidence says internal network |
| `internal:cluster-only,...` | no gateway; reachable only from inside the mesh | no, evidence gives the caller count |

Any classification may carry a trailing ` @<environment>` naming the deployment environment it was derived from; the provider repeats it in the evidence.

### Exposure facts
`kind=exposure` rows, one per deployment and environment, say how a service is reachable: `object` is `external`, `internal` or `cluster-only`, `subject` is the environment, `file` the values file that decided it. `kind=exposure_host` rows list the hostnames. The provider uses the strongest exposure across environments when it classifies a **new** route in a repository that has no whitelist patterns: external or internal exposure with no route-level authentication in that repository answers **yes**; cluster-only answers **no** with the caller count; a repository whose existing routes mostly carry authentication dependencies answers **unknown**, because the answer depends on whether the new handler declares the dependency, which the gate cannot see.

For a route the store has never seen, the provider collects every `via <pattern>` from the repository's `route_gate` rows and matches the candidate route against them: a trailing `*` matches any depth, `{param}` segments match any single segment. Matching an authenticated pattern answers `no`; matching an open pattern, or matching nothing, answers `yes`.

## Keeping it fresh
The store is only as current as its last build. The provider reports the store file's age in every answer and adds a warning above `--max-age-days`. Rebuild on a schedule that matches how fast routes change, typically nightly, and on demand before large refactors.
