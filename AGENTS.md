# Instructions for AI coding agents

Read `docs/AI_MAINTENANCE_EN.md`, `docs/ARCHITECTURE_EN.md`, and
`docs/BUILD_EN.md` before changing behavior. This directory is the public b2
source tree; work only inside the checkout and an explicitly chosen temporary
build directory. Do not search adjacent private installations for examples,
profiles, secrets, logs, signing keys, or data.

- A request to analyze or document does not authorize implementation. Stay within
  the user's requested scope; stop on a stop/pause request.
- Never start a real collection, logger redirect, write command, history sync,
  migration, or production service to test a change. Use synthetic fixtures and
  temporary roots; bind test servers to loopback and ephemeral ports.
- Preserve API3, TLS1.3/pinning/SPAKE2, profile and revision guards, command
  confirmation/readback, atomic writes, resumable transfers, CAS and schemas.
- Keep b2 identities/storage/ports separate. Never add an automatic b1 migration.
- Blank identity/network defaults must remain blank. No personal names in
  identifiers, comments, examples, commits, fixture bytes or binary metadata.
- Build paths, credentials and signing identities come from documented local
  settings/environment variables. Never publish those files or values.
- Run the relevant focused regressions, `python tools/audit_public.py`, and
  `python -m unittest discover -s tests -v`. Do not claim device acceptance from
  host tests or builds. Record limitations in `docs/VALIDATION_UK.md`.
- Do not publish, push, tag a remote release, or install on user devices unless
  the user explicitly requests that action. Do not select a personal Git identity.
- Do not spawn agents unless the user explicitly requests delegation.


Language maintenance: keep English/Ukrainian documentation and presentation catalogs
synchronized. English is the default. Preserve canonical inputs/API keys. This
explicitly requested replacement keeps b2.0.0/code20000; do not bump them.
Ukrainian instructions: [AGENTS_UK.md](AGENTS_UK.md).
