# @gaia/bot-harness (`gaia-sim`)

A fifth `BaseBotAdapter` that drives the **real** shared GAIA bot pipeline while
emulating a platform and recording a JSONL transcript — no real Discord / Slack
/ Telegram / WhatsApp connection.

**Fidelity contract:** emulating platform X pulls X's real `PLATFORM_LIMITS`,
`STREAMING_DEFAULTS`, and markdown converter from `@gaia/shared`, and
authenticates to the backend as X (`X-Bot-Platform: X`) via the real
`GaiaClient`. The harness never keeps its own behavior tables. The conformance
suite (`apps/bots/__tests__/harness/`) fails CI the moment harness output
diverges from the real adapter's.

## CLI

```bash
# one-shot: mint + link a dev user, inject one message, print + write the transcript
nx run bot-harness:sim -- send --emulate telegram --user dev@gaia.local --out t.jsonl "remind me tomorrow"

# multi-turn scenario with transcript assertions
nx run bot-harness:sim -- run apps/bots/harness/scenarios/plain-reply.yaml --out run.jsonl
```

Flags: `--emulate <discord|slack|telegram|whatsapp>`, `--user <email>`,
`--out <file>` (optional), `--api <url>` (default `$GAIA_API_URL` →
`http://localhost:$API_PORT` → `:8000`), `--channel <id>` (optional). Both env
vars come from `.env.worktree`, so a worktree targets its own API unattended.

Requires a running API (real LLM or the `dev:sim` scripted stub) and the same
`apps/bots/.env` a real bot uses (`GAIA_API_URL`, `GAIA_BOT_API_KEY`,
`GAIA_FRONTEND_URL`, `BOT_LOG_HASH_SECRET`). Set `RABBITMQ_URL` to record
proactive `outbound-delivery` events through the real outbound consumer.

See the `driving-gaia` skill (§6) for the full end-to-end recipe.
