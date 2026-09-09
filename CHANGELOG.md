# Changelog

## Unreleased

## 0.2.0 — 2026-09-09
- Understands estate-wide gate classifications (`OPEN:external,no-auth`, `OPEN:internal-gateway,no-auth`, `reachable:<exposure>,<deps>`, `internal:cluster-only,...`) with an optional ` @<env>` suffix.
- New routes in repositories without whitelist patterns are classified from `exposure` facts and the repository's prevailing authentication style; `unknown` when the repository authenticates per route.
- Evidence names the environment and, for cluster-only services, the recorded caller count.

## 0.1.0 — 2026-09-09
- First release: answers `route_gate`, `route_callers` and `gate_bearing` from a SQLite fact store; resolves class-level path prefixes from routes recorded for the edited file; classifies new routes against whitelist patterns in the store; reports store age; read-only; zero dependencies.
