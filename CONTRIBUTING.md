# Contributing

Ronda is pre-alpha. The public repo opens with the beta; until then this file is a stub.

- Python 3.11+, managed with [uv](https://docs.astral.sh/uv/): `uv sync`, then `uv run pytest`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/).
- Non-trivial decisions get a short ADR in `docs/adr/` (copy `0000-template.md`).
- UI work follows `design.md` and `brand/BRAND.md`.
- A new platform adapter (a *pos*) implements `discover()`, `stream()` and optionally `act()`, or posts
  events to `/v1/events` from any language. A guide lands with M1.
