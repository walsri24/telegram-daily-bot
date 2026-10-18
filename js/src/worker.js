import existingConfig from "../../config.json" with { type: "json" };
const DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MAX_HISTORY = 100;
const MAX_TEXT = 4096;


const DEFAULT = {
  destination: "",
  timezone: "Asia/Kolkata",
  paused: false,
  schedules: [{
    id: "main",
    name: "Main",
    time: "09:00",
    days: DAY_ORDER,
    message: "Good morning! This is your scheduled daily message.",
    enabled: true
  }],
  history: [],
  ...existingConfig,
  schedules: existingConfig.schedules ?? [{
    id: "main",
    name: "Main",
    time: "09:00",
    days: DAY_ORDER,
    message: "Good morning! This is your scheduled daily message.",
    enabled: true
  }],
  history: existingConfig.history ?? []
};


function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" }
  });
}

async function loadConfig(env) {
  const saved = await env.BOT_DATA.get("config", "json");
  if (!saved) {
  const initial = structuredClone(DEFAULT);

  if (!initial.destination) {
    initial.destination = env.TELEGRAM_CHAT_ID || "";
  }

  await saveConfig(env, initial);
  return initial;
}
  return {
    ...structuredClone(DEFAULT),
    ...saved,
    schedules: Array.isArray(saved.schedules) ? saved.schedules : structuredClone(DEFAULT.schedules),
    history: Array.isArray(saved.history) ? saved.history : []
  };
}

async function saveConfig(env, cfg) {
  await env.BOT_DATA.put("config", JSON.stringify(cfg));
}

function timeParts(timeValue) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(timeValue || "").trim());
  if (!match) throw new Error("Use 24-hour HH:MM format, e.g. 09:30.");
  const hour = Number(match[1]), minute = Number(match[2]);
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    throw new Error("Use 24-hour HH:MM format, e.g. 09:30.");
  }
  return { hour, minute, value: `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}` };
}

function parseDays(raw) {
  const value = String(raw || "").trim().toLowerCase();
  if (["daily", "everyday"].includes(value)) return [...DAY_ORDER];
  if (value === "weekdays") return DAY_ORDER.slice(0, 5);
  if (value === "weekends") return ["Sat", "Sun"];
  const aliases = {
    mon: "Mon", monday: "Mon", tue: "Tue", tues: "Tue", tuesday: "Tue",
    wed: "Wed", wednesday: "Wed", thu: "Thu", thur: "Thu", thurs: "Thu",
    thursday: "Thu", fri: "Fri", friday: "Fri", sat: "Sat", saturday: "Sat",
    sun: "Sun", sunday: "Sun"
  };
  const selected = [];
  for (const item of value.split(",")) {
    const day = aliases[item.trim()];
    if (!day) throw new Error("Days: daily, weekdays, weekends, or Mon,Wed,Fri.");
    if (!selected.includes(day)) selected.push(day);
  }
  return DAY_ORDER.filter(day => selected.includes(day));
}

function localParts(date, timezone) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone,
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  }).formatToParts(date);
  const out = Object.fromEntries(parts.map(p => [p.type, p.value]));
  return {
    day: out.weekday,
    time: `${out.hour}:${out.minute}`,
    date: `${out.year}-${out.month}-${out.day}`
  };
}

function findSchedule(cfg, id) {
  return cfg.schedules.find(s => s.id === id);
}

function addHistory(cfg, event, sid = "", details = "") {
  let timestamp;
  try {
    timestamp = new Intl.DateTimeFormat("sv-SE", {
      timeZone: cfg.timezone || "Asia/Kolkata",
      dateStyle: "short",
      timeStyle: "medium",
      hour12: false
    }).format(new Date()).replace(" ", "T");
  } catch {
    timestamp = new Date().toISOString();
  }
  cfg.history.push({
    time: timestamp,
    event,
    schedule_id: sid,
    details: String(details).slice(0, 400)
  });
  cfg.history = cfg.history.slice(-MAX_HISTORY);
}

async function telegram(env, method, body) {
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.description || `Telegram API error (${response.status})`);
  return data.result;
}

async function sendText(env, chatId, text) {
  return telegram(env, "sendMessage", { chat_id: chatId, text: String(text).slice(0, MAX_TEXT) });
}

function commandParts(text) {
  const trimmed = String(text || "").trim();
  const match = /^\/([a-z_]+)(?:@\w+)?(?:\s+([\s\S]*))?$/i.exec(trimmed);
  return match ? { command: match[1].toLowerCase(), payload: (match[2] || "").trim() } : null;
}

async function recordAndSave(env, cfg, event, sid = "", details = "") {
  addHistory(cfg, event, sid, details);
  await saveConfig(env, cfg);
}

async function deliver(env, cfg, schedule, manual = false) {
  const destination = String(cfg.destination || "").trim();
  if (!destination) {
    await recordAndSave(env, cfg, "failed", schedule.id, "No destination. Use /change_destination.");
    throw new Error("No destination configured. Use /change_destination.");
  }
  try {
    await sendText(env, destination, schedule.message);
    const latest = await loadConfig(env);
    await recordAndSave(env, latest, manual ? "sent_manual" : "sent", schedule.id, `Destination: ${destination}`);
  } catch (error) {
    const latest = await loadConfig(env);
    await recordAndSave(env, latest, "failed", schedule.id, error.message || String(error));
    throw error;
  }
}

async function authorized(env, update) {
  const userId = update?.message?.from?.id;
  if (String(userId) === String(env.TELEGRAM_ADMIN_ID)) return true;
  if (update?.message?.chat?.id != null) {
    await sendText(env, update.message.chat.id, "You are not authorized to manage this bot.");
  }
  return false;
}

async function handleCommand(env, update) {
  const message = update.message;
  if (!message?.text) return;
  const parsed = commandParts(message.text);
  if (!parsed) return;
  const { command, payload } = parsed;
  const chatId = message.chat.id;

  if (command === "myid") {
    await sendText(env, chatId,
      `Chat ID: ${chatId}\nYour user ID: ${message.from.id}\nChat type: ${message.chat.type}`);
    return;
  }

  if (command === "start" || command === "help") {
    if (!(await authorized(env, update))) return;
    await sendText(env, chatId,
      "Commands:\n/status\n/change_message <text>\n/set_time HH:MM\n" +
      "/set_days daily|weekdays|weekends|Mon,Wed,Fri\n" +
      "/change_destination <chat_id or @channel>\n/set_timezone Asia/Kolkata\n" +
      "/send_now [schedule_id]\n/pause\n/resume\n" +
      "/add_schedule name | HH:MM | days | message\n/list_schedules\n" +
      "/change_schedule id | HH:MM | days | message\n/remove_schedule <id>\n/history [1-30]");
    return;
  }

  if (!(await authorized(env, update))) return;
  const cfg = await loadConfig(env);
  const main = findSchedule(cfg, "main");

  switch (command) {
    case "change_message": {
      if (!payload || payload.length > MAX_TEXT) {
        await sendText(env, chatId, "Usage: /change_message Your message (max 4096 chars)."); return;
      }
      if (!main) { await sendText(env, chatId, "Main schedule not found."); return; }
      main.message = payload;
      await saveConfig(env, cfg);
      await recordAndSave(env, cfg, "message_changed", "main", "Main message updated");
      await sendText(env, chatId, "Main message updated.");
      break;
    }
    case "set_time": {
      try {
        if (payload.split(/\s+/).length !== 1) throw new Error("Usage: /set_time HH:MM");
        const t = timeParts(payload);
        if (!main) throw new Error("Main schedule not found.");
        main.time = t.value;
        await saveConfig(env, cfg);
        await recordAndSave(env, cfg, "time_changed", "main", main.time);
        await sendText(env, chatId, `Main time set to ${main.time} (${cfg.timezone}).`);
      } catch (e) { await sendText(env, chatId, e.message); }
      break;
    }
    case "set_days": {
      try {
        if (!payload) throw new Error("Usage: /set_days weekdays OR Mon,Wed,Fri");
        const days = parseDays(payload);
        if (!main) throw new Error("Main schedule not found.");
        main.days = days;
        await saveConfig(env, cfg);
        await recordAndSave(env, cfg, "days_changed", "main", days.join(","));
        await sendText(env, chatId, `Main days set to ${days.join(", ")}.`);
      } catch (e) { await sendText(env, chatId, e.message); }
      break;
    }
    case "change_destination": {
      if (!payload || /\s/.test(payload)) {
        await sendText(env, chatId, "Usage: /change_destination -1001234567890 OR @channelusername"); return;
      }
      cfg.destination = payload;
      await saveConfig(env, cfg);
      await recordAndSave(env, cfg, "destination_changed", "", payload);
      await sendText(env, chatId, `Destination set to ${payload}. Ensure the bot can post there.`);
      break;
    }
    case "set_timezone": {
      if (!payload) { await sendText(env, chatId, "Usage: /set_timezone Asia/Kolkata"); return; }
      try {
        new Intl.DateTimeFormat("en-US", { timeZone: payload }).format(new Date());
        cfg.timezone = payload;
        await saveConfig(env, cfg);
        await recordAndSave(env, cfg, "timezone_changed", "", payload);
        await sendText(env, chatId, `Timezone set to ${payload}; schedules updated.`);
      } catch {
        await sendText(env, chatId, "Unknown timezone. Examples: Asia/Kolkata, Europe/Berlin, UTC.");
      }
      break;
    }
    case "send_now": {
      const sid = payload || "main";
      const schedule = findSchedule(cfg, sid);
      if (!schedule) { await sendText(env, chatId, "Unknown schedule ID. Use /list_schedules."); return; }
      try {
        await deliver(env, cfg, schedule, true);
        await sendText(env, chatId, `Sent schedule ${sid} to ${cfg.destination}.`);
      } catch (e) { await sendText(env, chatId, `Send failed: ${e.message}`); }
      break;
    }
    case "status": {
      const lines = [
        `Global: ${cfg.paused ? "Paused" : "Running"}`,
        `Destination: ${cfg.destination || "(not set)"}`,
        `Timezone: ${cfg.timezone}`,
        `Schedule count: ${cfg.schedules.length}`
      ];
      if (main) lines.push(`Main time: ${main.time}`, `Main days: ${main.days.join(", ")}`,
        `Main enabled: ${main.enabled !== false}`, `Main message: ${main.message}`);
      await sendText(env, chatId, lines.join("\n"));
      break;
    }
    case "pause":
      cfg.paused = true;
      await saveConfig(env, cfg);
      await recordAndSave(env, cfg, "paused", "", "All schedules paused");
      await sendText(env, chatId, "All schedules paused.");
      break;
    case "resume":
      cfg.paused = false;
      await saveConfig(env, cfg);
      await recordAndSave(env, cfg, "resumed", "", "All schedules resumed");
      await sendText(env, chatId, "All schedules resumed.");
      break;
    case "add_schedule": {
      const parts = payload.split("|").map(p => p.trim());
      if (parts.length !== 4 || parts.some(p => !p)) {
        await sendText(env, chatId, "Usage: /add_schedule name | HH:MM | days | message\nExample: /add_schedule Standup | 10:00 | weekdays | Standup starts now."); return;
      }
      const [name, timeValue, daysValue, msg] = parts;
      if (msg.length > MAX_TEXT) { await sendText(env, chatId, "Message exceeds 4096 characters."); return; }
      try {
        const t = timeParts(timeValue), days = parseDays(daysValue);
        const sid = "s" + crypto.randomUUID().replaceAll("-", "").slice(0, 6);
        cfg.schedules.push({ id: sid, name: name.slice(0, 60), time: t.value, days, message: msg, enabled: true });
        await saveConfig(env, cfg);
        await recordAndSave(env, cfg, "schedule_added", sid, name);
        await sendText(env, chatId, `Added schedule.\nID: ${sid}\nName: ${name}\nTime: ${t.value} (${cfg.timezone})\nDays: ${days.join(", ")}`);
      } catch (e) { await sendText(env, chatId, e.message); }
      break;
    }
    case "list_schedules": {
      if (!cfg.schedules.length) { await sendText(env, chatId, "No schedules configured."); return; }
      const lines = [`Timezone: ${cfg.timezone}`];
      for (const s of cfg.schedules) lines.push(`\nID: ${s.id} | ${s.name}\nTime: ${s.time} | Days: ${s.days.join(", ")}\nEnabled: ${s.enabled !== false}\nMessage: ${s.message}`);
      await sendText(env, chatId, lines.join("\n").slice(-3900));
      break;
    }
    case "change_schedule": {
      const parts = payload.split("|").map(p => p.trim());
      if (parts.length !== 4) { await sendText(env, chatId, "Usage: /change_schedule id | HH:MM | days | message"); return; }
      const [sid, timeValue, daysValue, msg] = parts;
      if (!msg || msg.length > MAX_TEXT) { await sendText(env, chatId, "Message must contain 1-4096 characters."); return; }
      const schedule = findSchedule(cfg, sid);
      if (!schedule) { await sendText(env, chatId, "Unknown schedule ID. Use /list_schedules."); return; }
      try {
        const t = timeParts(timeValue), days = parseDays(daysValue);
        Object.assign(schedule, { time: t.value, days, message: msg });
        await saveConfig(env, cfg);
        await recordAndSave(env, cfg, "schedule_changed", sid, "Time/days/message changed");
        await sendText(env, chatId, `Schedule ${sid} updated.`);
      } catch (e) { await sendText(env, chatId, e.message); }
      break;
    }
    case "remove_schedule": {
      const sid = payload;
      if (!sid || /\s/.test(sid)) { await sendText(env, chatId, "Usage: /remove_schedule <id>"); return; }
      if (sid === "main") { await sendText(env, chatId, "Main cannot be removed; change or pause it instead."); return; }
      const schedule = findSchedule(cfg, sid);
      if (!schedule) { await sendText(env, chatId, "Unknown schedule ID. Use /list_schedules."); return; }
      cfg.schedules = cfg.schedules.filter(s => s.id !== sid);
      await saveConfig(env, cfg);
      await recordAndSave(env, cfg, "schedule_removed", sid, schedule.name);
      await sendText(env, chatId, `Removed ${sid}.`);
      break;
    }
    case "history": {
      let count = 10;
      if (payload) {
        count = Number(payload);
        if (!Number.isInteger(count) || count < 1 || count > 30) {
          await sendText(env, chatId, "Usage: /history [1-30]"); return;
        }
      }
      const entries = cfg.history.slice(-count);
      if (!entries.length) { await sendText(env, chatId, "No history yet."); return; }
      const lines = ["Recent history (newest last):"];
      for (const e of entries) lines.push(`${e.time || "?"} | ${e.event || "?"} | ${e.schedule_id || "-"} | ${e.details || ""}`);
      await sendText(env, chatId, lines.join("\n").slice(-3900));
      break;
    }
    default:
      await sendText(env, chatId, "Unknown command. Send /start to see available commands.");
  }
}

async function setCommands(env) {
  const commands = [
    ["start", "Show help and available commands"], ["myid", "Show this chat ID and your user ID"],
    ["status", "Show current settings and schedules"], ["change_message", "Change the Main schedule message"],
    ["set_time", "Set Main schedule time (HH:MM)"], ["set_days", "Set Main schedule days"],
    ["change_destination", "Change the destination chat"], ["set_timezone", "Set timezone, e.g. Asia/Kolkata"],
    ["send_now", "Send a message immediately"], ["pause", "Pause all scheduled messages"],
    ["resume", "Resume all scheduled messages"], ["add_schedule", "Add another scheduled message"],
    ["list_schedules", "List all schedules"], ["change_schedule", "Edit a schedule by ID"],
    ["remove_schedule", "Remove a schedule by ID"], ["history", "Show recent send history"]
  ].map(([command, description]) => ({ command, description }));
  await telegram(env, "setMyCommands", { commands });
}

async function runScheduled(env) {
  const cfg = await loadConfig(env);
  if (cfg.paused) return;
  let now;
  try {
    now = localParts(new Date(), cfg.timezone || "Asia/Kolkata");
  } catch (e) {
    console.error("Invalid configured timezone:", e);
    return;
  }
  for (const schedule of cfg.schedules) {
    if (schedule.enabled === false || schedule.time !== now.time || !schedule.days.includes(now.day)) continue;
    const dedupeKey = `sent:${now.date}:${schedule.id}`;
    if (await env.BOT_DATA.get(dedupeKey)) continue;
    try {
      await deliver(env, cfg, schedule, false);
      await env.BOT_DATA.put(dedupeKey, "1", { expirationTtl: 60 * 60 * 48 });
    } catch (e) {
      console.error(`Scheduled delivery failed for ${schedule.id}:`, e);
    }
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") return json({ ok: true, service: "telegram-daily-bot" });
    if (url.pathname.startsWith("/webhook/")) {
      const suppliedSecret = url.pathname.slice("/webhook/".length);
      if (!env.WEBHOOK_SECRET || suppliedSecret !== env.WEBHOOK_SECRET) return new Response("Not found", { status: 404 });
      if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });
      let update;
      try { update = await request.json(); } catch { return new Response("Bad JSON", { status: 400 }); }
      try {
        if (update.message?.text) await handleCommand(env, update);
      } catch (e) {
        console.error("Telegram update failed:", e);
        if (update.message?.chat?.id != null) {
          try { await sendText(env, update.message.chat.id, "Something went wrong. Check the Worker logs."); } catch {}
        }
      }
      return new Response("OK");
    }
    return json({ service: "telegram-daily-bot", status: "running", health: "/health" });
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(runScheduled(env));
  }
};
