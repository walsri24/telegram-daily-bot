const baseUrl = process.env.WORKER_URL;
const token = process.env.TELEGRAM_BOT_TOKEN;
const secret = process.env.WEBHOOK_SECRET;

if (!baseUrl || !token || !secret) {
  console.error("Set WORKER_URL, TELEGRAM_BOT_TOKEN and WEBHOOK_SECRET environment variables.");
  process.exit(1);
}
const webhookUrl = `${baseUrl.replace(/\/$/, "")}/webhook/${secret}`;
const response = await fetch(`https://api.telegram.org/bot${token}/setWebhook`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ url: webhookUrl, drop_pending_updates: false })
});
const result = await response.json();
console.log(JSON.stringify(result, null, 2));
if (!response.ok || !result.ok) process.exit(1);
