# Security

SeKantor only watches: it approves nothing and sends nothing to your agents (ADR-0021). Its attack
surface is the local hub that shows what your agents are doing. The defaults are built for that:

- The hub binds to `127.0.0.1:7878` only.
- Every request needs the local token in `~/.sekantor/token` (mode 600).
- Fail closed: if the hub is down, slow or errors, the hook prints nothing and the agent carries on
  as if SeKantor were not there.
- No telemetry and no outbound network calls from the hub.

The full threat model, with residual risks, is in [docs/threat-model.md](docs/threat-model.md).

## Reporting a vulnerability

SeKantor is pre-alpha and not yet public. Until a security contact is published here, please report
issues privately to the repository owner through GitHub (Security tab, "Report a vulnerability"),
not in a public issue.
