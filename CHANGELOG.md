# Changelog

## Unreleased

## 0.3.0 — 2026-10-13
- **A code graph as a second source.** `--graph graph.ndjson` answers the same questions from a graph exported as NDJSON: route nodes or `HANDLES_ROUTE` edges give the routes a file declares, `CALLS` edges into a route's handler give its callers at file and line. Field names default to the compound-v1 convention (stable ids `<repo>:<lang>:<file>:<kind>:<name>`) and a `--graph-fields` JSON map covers a graph that spells them differently. What a graph does not know it does not pretend to: gate classification, exposure and whitelists come back `unknown` with the reason, and `gate_bearing` is still answered from the configured gate files. Zero model calls, zero network, read once.

## 0.2.0 — 2026-09-09
- Understands estate-wide gate classifications (`OPEN:external,no-auth`, `OPEN:internal-gateway,no-auth`, `reachable:<exposure>,<deps>`, `internal:cluster-only,...`) with an optional ` @<env>` suffix.
- New routes in repositories without whitelist patterns are classified from `exposure` facts and the repository's prevailing authentication style; `unknown` when the repository authenticates per route.
- Evidence names the environment and, for cluster-only services, the recorded caller count.

## 0.1.0 — 2026-09-09
- First release: answers `route_gate`, `route_callers` and `gate_bearing` from a SQLite fact store; resolves class-level path prefixes from routes recorded for the edited file; classifies new routes against whitelist patterns in the store; reports store age; read-only; zero dependencies.
