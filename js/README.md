# Telegram Daily Bot — Cloudflare Workers (JavaScript)

This is a JavaScript/Cloudflare Workers port of the Python Telegram scheduled-message bot. It uses a Telegram webhook, a one-minute Cron Trigger, and Cloudflare KV for configuration/history. It does not need a continuously running computer or Docker container.

## Included commands

`/start`, `/myid`, `/status`, `/change_message`, `/set_time`, `/set_days`, `/change_destination`, `/set_timezone`, `/send_now`, `/pause`, `/resume`, `/add_schedule`, `/list_schedules`, `/change_schedule`, `/remove_schedule`, `/history`.

## 1. Create a KV namespace

Install Node.js, then from this folder:

```bash
npm install
npx wrangler login
npx wrangler kv namespace create BOT_DATA
```

Copy the namespace `id` from the output into `wrangler.toml`, replacing `REPLACE_WITH_YOUR_KV_NAMESPACE_ID`.

## 2. Configure secrets

```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_ADMIN_ID
npx wrangler secret put WEBHOOK_SECRET
```

Paste the Telegram bot token when prompted. `TELEGRAM_ADMIN_ID` is your numeric Telegram user ID. `WEBHOOK_SECRET` should be a long random string containing URL-safe characters, for example generated with `openssl rand -hex 32`.

Optional initial destination:
```bash
npx wrangler secret put TELEGRAM_CHAT_ID
```
This sets the default destination on first run only. You can also configure it by sending `/change_destination <chat_id>` to the bot after deployment.

## 3. Deploy

```bash
npm run deploy
```

Copy the deployed `https://....workers.dev` URL. Test:
```bash
curl https://YOUR-WORKER.workers.dev/health
```

## 4. Register Telegram webhook

On your computer, set these environment variables (do not commit them to Git):

```bash
export WORKER_URL="https://YOUR-WORKER.workers.dev"
export TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
export WEBHOOK_SECRET="THE_SAME_SECRET_USED_IN_WRANGLER"
npm run set-webhook
```

The script should return `"ok": true`. Send `/myid` to the bot, then `/start`.

## How scheduling works

The Worker Cron Trigger runs every minute. It calculates the current local time/day using the schedule's configured IANA timezone (default `Asia/Kolkata`), then sends matching enabled schedules. A KV key is used to avoid sending the same schedule repeatedly during the same local date.

Cron schedules have one-minute granularity, so set times using `HH:MM`. Cron executions and KV operations are subject to Cloudflare's current free-tier limits and platform availability. KV is eventually consistent; the deduplication reduces repeat sends but is not a transactional lock.

## Security

- Never commit `.env`, bot tokens, admin IDs, or webhook secrets.
- Keep the webhook secret private; it is part of the URL.
- The `/myid` command is intentionally available without admin authorization, matching the Python version.
- The Worker endpoint is not a dashboard. `/health` is a basic health check.

## Notes / differences from Python version

- The Python local `config.json` is not automatically imported. The Worker creates a default config in KV on first use. If you have customized `config.json`, manually copy its destination, timezone, schedules, and message into the KV `config` JSON value using the Cloudflare dashboard or Wrangler KV commands.
- The Worker is not a direct line-by-line runtime conversion: Telegram commands and schedule behavior are ported to Workers' webhook/Cron/KV model.
- Cloudflare Workers does not run the Python Docker container; deploy this folder as a separate Worker.
