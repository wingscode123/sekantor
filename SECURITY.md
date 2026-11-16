# Security

SeKantor can approve shell commands on your behalf (from M2 on), so its attack surface is close to
terminal access. The defaults are built for that:

- The hub binds to `127.0.0.1:7878` only.
- Every request needs the local token in `~/.sekantor/token` (mode 600).
- Fail closed: if the hub is down, slow or errors, the hook returns no decision and the agent
  shows its own prompt. SeKantor never auto-approves.
- No telemetry and no outbound network calls from the hub.

The full threat model, with residual risks, is in [docs/threat-model.md](docs/threat-model.md).

## Reporting a vulnerability

SeKantor is pre-alpha and not yet public. Until a security contact is published here, please report
issues privately to the repository owner through GitHub (Security tab, "Report a vulnerability"),
not in a public issue.
