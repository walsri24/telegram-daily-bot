# Configurable Telegram Daily Sender

## Setup
1. Create a bot with @BotFather.
2. Add it to your group, or make it an administrator in your channel with permission to post.
3. Copy `.env.example` to `.env` and set the bot token, destination chat ID, and your numeric Telegram user ID.
4. Run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Open the bot's private chat and send `/start`.

## Commands
- `/myid` — show the current chat ID and your user ID
- `/status`
- `/change_message Your new message`
- `/set_time 09:30`
- `/set_days daily` or `weekdays`, `weekends`, `Mon,Wed,Fri`
- `/change_destination -1001234567890` or `/change_destination @publicchannel`
- `/set_timezone Asia/Kolkata`
- `/send_now` or `/send_now s123abc`
- `/pause`, `/resume`
- `/add_schedule name | HH:MM | days | message`
- `/list_schedules`
- `/change_schedule id | HH:MM | days | message`
- `/remove_schedule id` (Main cannot be removed)
- `/history` or `/history 20`

Example:
`/add_schedule Standup | 10:00 | weekdays | Daily stand-up starts now.`

Times are 24-hour `HH:MM`. Timezone uses IANA names such as `Asia/Kolkata`, `Europe/Berlin`, or `UTC`.

## Cloud deployment
Run as a continuously running Python worker. Configure the three environment variables in the hosting dashboard. `config.json` stores settings and the last 100 history events, so mount persistent storage or changes may be lost on redeploy/restart. Do not run multiple long-polling copies with the same token. Keep `.env` and `config.json` private.

This starter uses a JSON file and is intended for one bot process. For stronger durability or multiple instances, move configuration/history to a database.
