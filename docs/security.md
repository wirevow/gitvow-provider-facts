# Security

The provider opens the store read-only, makes no network calls, and writes nothing. Evidence strings it returns are built from route paths, repository names and call sites in the store; they are shown to the agent and written, redacted, to gitvow's hook log. If the store contains anything that must not reach an agent's context, do not put it in `file`, `subject`, `object` or `src_site` columns.

Report vulnerabilities to nikhil@wirevow.com or through a private GitHub security advisory.
