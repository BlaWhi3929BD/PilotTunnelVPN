# TunnelPilot engineering rules

- Read `docs/TunnelPilot_Agent_Handoff_2026-10-23.md` before significant architectural or lifecycle work.
- Treat Git source as the source of truth; inspect `git status`, HEAD and existing diffs before editing.
- Do not discard user changes, run destructive shell commands, or use `git add .` automatically.
- Never commit private keys, device tokens, gateway tokens, secrets, signing credentials, APK credentials or SQLite data (`server/data/*.db*`).
- Client WireGuard private keys are generated and stored only on Android; the backend receives public keys only.
- Keep Gateway Agent private; do not expose it to the Internet. Avoid running the whole agent as root in production.
- For server changes run `.venv/bin/pytest server/tests -q`.
- For Android changes run `./gradlew :app:testDebugUnitTest`, `./gradlew :app:assembleDebug`, and `./gradlew :app:lintDebug`.
- Do not report tests as passing unless they were run; state what was not tested.
- Make lifecycle and security changes idempotent and failure-recoverable across SQLite + Gateway Agent side effects.
- Use Context7/official docs for version-sensitive APIs.
- Update tests and docs with API/schema/config changes.
