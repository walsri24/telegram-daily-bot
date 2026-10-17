import json
import logging
import os
import uuid
from datetime import time, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_ID = int(os.environ["TELEGRAM_ADMIN_ID"])
CONFIG_PATH = Path(os.getenv("CONFIG_FILE", "config.json"))
DEFAULT_TZ = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# PTB JobQueue uses Sunday=0, Monday=1, ... Saturday=6.
PTB_DAYS = {"Sun": 0, "Mon": 1, "Tue": 2, "Wed": 3, "Thu": 4, "Fri": 5, "Sat": 6}
MAX_HISTORY = 100
MAX_TEXT = 4096

DEFAULT = {
    "destination": os.getenv("TELEGRAM_CHAT_ID", ""),
    "timezone": DEFAULT_TZ,
    "paused": False,
    "schedules": [{
        "id": "main", "name": "Main", "time": "09:00",
        "days": DAY_ORDER, "message": "Good morning! This is your scheduled daily message.",
        "enabled": True,
    }],
    "history": [],
}


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def config():
    if not CONFIG_PATH.exists():
        save_config(json.loads(json.dumps(DEFAULT)))
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for key, value in DEFAULT.items():
        cfg.setdefault(key, json.loads(json.dumps(value)))
    return cfg


def record(cfg, event, sid="", details=""):
    try:
        tz = ZoneInfo(cfg.get("timezone", DEFAULT_TZ))
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    cfg.setdefault("history", []).append({
        "time": datetime.now(tz).isoformat(timespec="seconds"),
        "event": event, "schedule_id": sid, "details": str(details)[:400],
    })
    cfg["history"] = cfg["history"][-MAX_HISTORY:]
    save_config(cfg)


def parse_time(value):
    try:
        hour, minute = map(int, value.strip().split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (ValueError, TypeError):
        raise ValueError("Use 24-hour HH:MM format, e.g. 09:30.")


def parse_days(value):
    value = value.strip().lower()
    if value in ("daily", "everyday"):
        return DAY_ORDER.copy()
    if value == "weekdays":
        return DAY_ORDER[:5]
    if value == "weekends":
        return ["Sat", "Sun"]
    aliases = {
        "mon": "Mon", "monday": "Mon", "tue": "Tue", "tues": "Tue", "tuesday": "Tue",
        "wed": "Wed", "wednesday": "Wed", "thu": "Thu", "thur": "Thu", "thurs": "Thu",
        "thursday": "Thu", "fri": "Fri", "friday": "Fri", "sat": "Sat",
        "saturday": "Sat", "sun": "Sun", "sunday": "Sun",
    }
    selected = []
    for item in value.split(","):
        day = aliases.get(item.strip())
        if not day:
            raise ValueError("Days: daily, weekdays, weekends, or Mon,Wed,Fri.")
        if day not in selected:
            selected.append(day)
    return [d for d in DAY_ORDER if d in selected]


def find_schedule(cfg, sid):
    return next((s for s in cfg["schedules"] if s["id"] == sid), None)


async def authorized(update, context):
    if update.effective_user and update.effective_user.id == ADMIN_ID:
        return True
    if update.effective_message:
        await update.effective_message.reply_text("You are not authorized to manage this bot.")
    return False


def payload(update):
    parts = (update.effective_message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def reschedule(app):
    for job in app.job_queue.jobs():
        if job.name and job.name.startswith("daily_sender_"):
            job.schedule_removal()
    cfg = config()
    if cfg.get("paused"):
        return
    try:
        tz = ZoneInfo(cfg["timezone"])
    except ZoneInfoNotFoundError:
        log.exception("Invalid configured timezone")
        return
    for s in cfg["schedules"]:
        if not s.get("enabled", True):
            continue
        try:
            h, m = parse_time(s["time"])
            days = tuple(PTB_DAYS[d] for d in s["days"])
            app.job_queue.run_daily(
                scheduled_send, time=time(h, m, tzinfo=tz), days=days,
                data=s["id"], name=f"daily_sender_{s['id']}",
            )
        except (ValueError, KeyError):
            log.exception("Skipping invalid schedule %s", s.get("id"))


async def deliver(context, s, manual=False):
    cfg = config()
    dest = str(cfg.get("destination", "")).strip()
    if not dest:
        record(cfg, "failed", s["id"], "No destination. Use /change_destination.")
        raise RuntimeError("No destination configured. Use /change_destination.")
    try:
        await context.bot.send_message(chat_id=dest, text=s["message"])
        record(config(), "sent_manual" if manual else "sent", s["id"], f"Destination: {dest}")
    except Exception as exc:
        record(config(), "failed", s["id"], repr(exc))
        log.exception("Message delivery failed")
        raise


async def scheduled_send(context: ContextTypes.DEFAULT_TYPE):
    cfg = config()
    if cfg.get("paused"):
        return
    s = find_schedule(cfg, context.job.data)
    if not s or not s.get("enabled", True):
        return
    try:
        await deliver(context, s)
    except Exception:
        pass


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the current chat ID and the sender's user ID."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if message and chat and user:
        await message.reply_text(
            f"Chat ID: {chat.id}\\n"
            f"Your user ID: {user.id}\\n"
            f"Chat type: {chat.type}"
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await authorized(update, context): return
    await update.effective_message.reply_text(
        "Commands:\n/status\n/change_message <text>\n/set_time HH:MM\n"
        "/set_days daily|weekdays|weekends|Mon,Wed,Fri\n"
        "/change_destination <chat_id or @channel>\n/set_timezone Asia/Kolkata\n"
        "/send_now [schedule_id]\n/pause\n/resume\n"
        "/add_schedule name | HH:MM | days | message\n/list_schedules\n"
        "/change_schedule id | HH:MM | days | message\n/remove_schedule <id>\n/history [1-30]"
    )


async def change_message(update, context):
    if not await authorized(update, context): return
    msg = payload(update)
    if not msg or len(msg) > MAX_TEXT:
        await update.effective_message.reply_text("Usage: /change_message Your message (max 4096 chars).")
        return
    cfg = config(); s = find_schedule(cfg, "main")
    if not s:
        await update.effective_message.reply_text("Main schedule not found."); return
    s["message"] = msg; save_config(cfg); record(cfg, "message_changed", "main", "Main message updated")
    await update.effective_message.reply_text("Main message updated.")


async def set_time(update, context):
    if not await authorized(update, context): return
    if len(context.args) != 1:
        await update.effective_message.reply_text("Usage: /set_time HH:MM"); return
    try: h, m = parse_time(context.args[0])
    except ValueError as e:
        await update.effective_message.reply_text(str(e)); return
    cfg = config(); s = find_schedule(cfg, "main")
    if not s:
        await update.effective_message.reply_text("Main schedule not found."); return
    s["time"] = f"{h:02d}:{m:02d}"; save_config(cfg)
    record(cfg, "time_changed", "main", s["time"]); reschedule(context.application)
    await update.effective_message.reply_text(f"Main time set to {s['time']} ({cfg['timezone']}).")


async def set_days(update, context):
    if not await authorized(update, context): return
    raw = payload(update)
    if not raw:
        await update.effective_message.reply_text("Usage: /set_days weekdays OR Mon,Wed,Fri"); return
    try: days = parse_days(raw)
    except ValueError as e:
        await update.effective_message.reply_text(str(e)); return
    cfg = config(); s = find_schedule(cfg, "main")
    if not s:
        await update.effective_message.reply_text("Main schedule not found."); return
    s["days"] = days; save_config(cfg); record(cfg, "days_changed", "main", ",".join(days))
    reschedule(context.application)
    await update.effective_message.reply_text(f"Main days set to {', '.join(days)}.")


async def change_destination(update, context):
    if not await authorized(update, context): return
    dest = payload(update)
    if not dest or len(dest.split()) != 1:
        await update.effective_message.reply_text("Usage: /change_destination -1001234567890 OR @channelusername"); return
    cfg = config(); cfg["destination"] = dest; save_config(cfg)
    record(cfg, "destination_changed", "", dest)
    await update.effective_message.reply_text(f"Destination set to {dest}. Ensure the bot can post there.")


async def set_timezone(update, context):
    if not await authorized(update, context): return
    zone = payload(update)
    if not zone:
        await update.effective_message.reply_text("Usage: /set_timezone Asia/Kolkata"); return
    try: ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        await update.effective_message.reply_text("Unknown timezone. Examples: Asia/Kolkata, Europe/Berlin, UTC."); return
    cfg = config(); cfg["timezone"] = zone; save_config(cfg); record(cfg, "timezone_changed", "", zone)
    reschedule(context.application)
    await update.effective_message.reply_text(f"Timezone set to {zone}; schedules rescheduled.")


async def send_now(update, context):
    if not await authorized(update, context): return
    cfg = config(); sid = context.args[0] if context.args else "main"; s = find_schedule(cfg, sid)
    if not s:
        await update.effective_message.reply_text("Unknown schedule ID. Use /list_schedules."); return
    try:
        await deliver(context, s, manual=True)
        await update.effective_message.reply_text(f"Sent schedule {sid} to {cfg['destination']}.")
    except Exception as e:
        await update.effective_message.reply_text(f"Send failed: {e}")


async def status(update, context):
    if not await authorized(update, context): return
    cfg = config(); s = find_schedule(cfg, "main")
    lines = [f"Global: {'Paused' if cfg['paused'] else 'Running'}",
             f"Destination: {cfg['destination'] or '(not set)'}",
             f"Timezone: {cfg['timezone']}", f"Schedule count: {len(cfg['schedules'])}"]
    if s:
        lines += [f"Main time: {s['time']}", f"Main days: {', '.join(s['days'])}",
                  f"Main enabled: {s.get('enabled', True)}", f"Main message: {s['message']}"]
    await update.effective_message.reply_text("\n".join(lines))


async def pause(update, context):
    if not await authorized(update, context): return
    cfg = config(); cfg["paused"] = True; save_config(cfg); record(cfg, "paused", "", "All schedules paused")
    reschedule(context.application); await update.effective_message.reply_text("All schedules paused.")


async def resume(update, context):
    if not await authorized(update, context): return
    cfg = config(); cfg["paused"] = False; save_config(cfg); record(cfg, "resumed", "", "All schedules resumed")
    reschedule(context.application); await update.effective_message.reply_text("All schedules resumed.")


async def add_schedule(update, context):
    if not await authorized(update, context): return
    parts = [p.strip() for p in payload(update).split("|", 3)]
    if len(parts) != 4 or not all(parts):
        await update.effective_message.reply_text(
            "Usage: /add_schedule name | HH:MM | days | message\n"
            "Example: /add_schedule Standup | 10:00 | weekdays | Standup starts now."
        ); return
    name, time_value, days_value, msg = parts
    if len(msg) > MAX_TEXT:
        await update.effective_message.reply_text("Message exceeds 4096 characters."); return
    try: h, m = parse_time(time_value); days = parse_days(days_value)
    except ValueError as e:
        await update.effective_message.reply_text(str(e)); return
    cfg = config(); sid = "s" + uuid.uuid4().hex[:6]
    cfg["schedules"].append({"id": sid, "name": name[:60], "time": f"{h:02d}:{m:02d}",
                             "days": days, "message": msg, "enabled": True})
    save_config(cfg); record(cfg, "schedule_added", sid, name); reschedule(context.application)
    await update.effective_message.reply_text(
        f"Added schedule.\nID: {sid}\nName: {name}\nTime: {h:02d}:{m:02d} ({cfg['timezone']})\nDays: {', '.join(days)}"
    )


async def list_schedules(update, context):
    if not await authorized(update, context): return
    cfg = config()
    if not cfg["schedules"]:
        await update.effective_message.reply_text("No schedules configured."); return
    lines = [f"Timezone: {cfg['timezone']}"]
    for s in cfg["schedules"]:
        lines.append(f"\nID: {s['id']} | {s['name']}\nTime: {s['time']} | Days: {', '.join(s['days'])}"
                     f"\nEnabled: {s.get('enabled', True)}\nMessage: {s['message']}")
    text = "\n".join(lines)
    await update.effective_message.reply_text(text[-3900:])


async def change_schedule(update, context):
    if not await authorized(update, context): return
    parts = [p.strip() for p in payload(update).split("|", 3)]
    if len(parts) != 4:
        await update.effective_message.reply_text(
            "Usage: /change_schedule id | HH:MM | days | message"); return
    sid, time_value, days_value, msg = parts
    if not msg or len(msg) > MAX_TEXT:
        await update.effective_message.reply_text("Message must contain 1-4096 characters."); return
    try: h, m = parse_time(time_value); days = parse_days(days_value)
    except ValueError as e:
        await update.effective_message.reply_text(str(e)); return
    cfg = config(); s = find_schedule(cfg, sid)
    if not s:
        await update.effective_message.reply_text("Unknown schedule ID. Use /list_schedules."); return
    s.update({"time": f"{h:02d}:{m:02d}", "days": days, "message": msg})
    save_config(cfg); record(cfg, "schedule_changed", sid, "Time/days/message changed")
    reschedule(context.application); await update.effective_message.reply_text(f"Schedule {sid} updated.")


async def remove_schedule(update, context):
    if not await authorized(update, context): return
    if len(context.args) != 1:
        await update.effective_message.reply_text("Usage: /remove_schedule <id>"); return
    sid = context.args[0]
    if sid == "main":
        await update.effective_message.reply_text("Main cannot be removed; change or pause it instead."); return
    cfg = config(); s = find_schedule(cfg, sid)
    if not s:
        await update.effective_message.reply_text("Unknown schedule ID. Use /list_schedules."); return
    cfg["schedules"].remove(s); save_config(cfg); record(cfg, "schedule_removed", sid, s["name"])
    reschedule(context.application); await update.effective_message.reply_text(f"Removed {sid}.")


async def history(update, context):
    if not await authorized(update, context): return
    count = 10
    if context.args:
        try:
            count = int(context.args[0])
            if not 1 <= count <= 30: raise ValueError
        except ValueError:
            await update.effective_message.reply_text("Usage: /history [1-30]"); return
    entries = config().get("history", [])[-count:]
    if not entries:
        await update.effective_message.reply_text("No history yet."); return
    lines = ["Recent history (newest last):"]
    for e in entries:
        lines.append(f"{e.get('time','?')} | {e.get('event','?')} | {e.get('schedule_id') or '-'} | {e.get('details','')}")
    await update.effective_message.reply_text("\n".join(lines)[-3900:])


async def post_init(app):
    reschedule(app)
    # Populate Telegram's "/" command menu.
    await app.bot.set_my_commands([
        ("start", "Show help and available commands"),
        ("myid", "Show this chat ID and your user ID"),
        ("status", "Show current settings and schedules"),
        ("change_message", "Change the Main schedule message"),
        ("set_time", "Set Main schedule time (HH:MM)"),
        ("set_days", "Set Main schedule days"),
        ("change_destination", "Change the destination chat"),
        ("set_timezone", "Set timezone, e.g. Asia/Kolkata"),
        ("send_now", "Send a message immediately"),
        ("pause", "Pause all scheduled messages"),
        ("resume", "Resume all scheduled messages"),
        ("add_schedule", "Add another scheduled message"),
        ("list_schedules", "List all schedules"),
        ("change_schedule", "Edit a schedule by ID"),
        ("remove_schedule", "Remove a schedule by ID"),
        ("history", "Show recent send history"),
    ])


async def error_handler(update, context):
    log.error("Unhandled error: %s", context.error, exc_info=context.error)


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    commands = {
        "start": start, "help": start, "myid": myid, "change_message": change_message,
        "set_time": set_time, "set_days": set_days, "change_destination": change_destination,
        "set_timezone": set_timezone, "send_now": send_now, "status": status,
        "pause": pause, "resume": resume, "add_schedule": add_schedule,
        "list_schedules": list_schedules, "change_schedule": change_schedule,
        "remove_schedule": remove_schedule, "history": history,
    }
    for name, callback in commands.items():
        app.add_handler(CommandHandler(name, callback))
    app.add_error_handler(error_handler)
    log.info("Telegram daily sender started")
    app.run_polling()


if __name__ == "__main__":
    main()
