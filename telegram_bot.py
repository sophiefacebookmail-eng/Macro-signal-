import os
import asyncio
import logging
from pathlib import Path
import yaml
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from market_data import TwelveDataClient
from indicators import build_signal
import storage

# Avoid leaking bot-token-bearing Telegram request URLs into Railway logs.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "httpcore", "telegram", "telegram.ext", "aiohttp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("macroedge")

with open(Path(__file__).with_name("config.yaml"), "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_KEY = os.getenv("TWELVEDATA_API_KEY", "").strip()
if not TOKEN or not API_KEY:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TWELVEDATA_API_KEY environment variable")

bot_cfg = CONFIG["bot"]
data_client = TwelveDataClient(
    API_KEY,
    spacing_seconds=bot_cfg.get("request_spacing_seconds", 9),
    retry_wait_seconds=bot_cfg.get("retry_wait_seconds", 65)
)
scan_lock = asyncio.Lock()

def fmt_price(value):
    return f"{value:,.5f}" if abs(value) < 100 else f"{value:,.2f}"

def format_signal(market, signal):
    return (
        f"📊 {market['label']} — {signal['direction']}\n"
        f"Timeframe: {bot_cfg['timeframe']}\n"
        f"Entry reference: {fmt_price(signal['entry'])}\n"
        f"Stop reference: {fmt_price(signal['stop'])}\n"
        f"Target 1: {fmt_price(signal['target1'])}\n"
        f"Target 2: {fmt_price(signal['target2'])}\n"
        f"Confluence: {signal['score']}/4 | RSI: {signal['rsi']:.1f}\n"
        f"Candle: {signal['timestamp']}\n\n"
        "Research signal only — verify price, spread and risk before trading."
    )

async def run_scan():
    if scan_lock.locked():
        return None, ["A scan is already running. Please wait and try again."]
    async with scan_lock:
        found, notes = [], []
        for market in CONFIG["markets"]:
            try:
                candles = await data_client.candles(
                    market["symbol"], bot_cfg["timeframe"], int(bot_cfg["candle_count"])
                )
                signal = build_signal(candles, {**CONFIG["strategy"], "minimum_confluence": bot_cfg["minimum_confluence"]})
                if signal:
                    found.append((market, signal))
                else:
                    notes.append(f"{market['label']}: no qualifying setup")
            except Exception as exc:
                # Do not print request URLs or credentials.
                log.warning("Market scan failed for %s: %s", market["label"], str(exc).replace(API_KEY, "[REDACTED]")[:240])
                notes.append(f"{market['label']}: data unavailable ({str(exc).replace(API_KEY, "[REDACTED]")[:120]})")
        return found, notes

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage.add_subscriber(update.effective_chat.id)
    await update.message.reply_text(
        "Welcome to MacroEdge Forex Signals.\n"
        "Alerts are enabled for this chat.\n\n"
        "Markets: XAUUSD, GBPUSD, EURUSD, USDJPY, BTCUSD, ETHUSD\n"
        "Timeframe: 15 minutes\n"
        "Commands: /scan /signals /markets /status /unsubscribe\n\n"
        "Signals are educational research, not financial advice."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start — subscribe\n/scan — run a scan now\n/signals — scan and show setups\n/markets — list markets\n/status — service status\n/unsubscribe — stop alerts")

async def markets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = "\n".join(f"• {m['label']} ({m['symbol']})" for m in CONFIG["markets"])
    await update.message.reply_text("Configured markets:\n" + names)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "MacroEdge signals: RUNNING\nTelegram alerts: ON\n"
        "Twelve Data feed: CONFIGURED (live request checked during scans)\n"
        f"Timeframe: {bot_cfg['timeframe']}\n"
        "Execution: DISABLED — signals only"
    )

async def unsubscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage.remove_subscriber(update.effective_chat.id)
    await update.message.reply_text("Alerts disabled for this chat. Send /start to subscribe again.")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Scanning six configured markets. Requests are spaced to respect the provider's rate limit; this may take about a minute.")
    found, notes = await run_scan()
    if found is None:
        await update.message.reply_text(notes[0])
        return
    if not found:
        await update.message.reply_text("Scan finished. No qualifying setups found.\n\n" + "\n".join(notes))
        return
    for market, signal in found:
        await update.message.reply_text(format_signal(market, signal))

async def signals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await scan_cmd(update, context)

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    found, notes = await run_scan()
    if found is None:
        log.info("Scheduled scan skipped because another scan is active")
        return
    for market, signal in found:
        key = f"{market['label']}:{signal['direction']}:{signal['timestamp']}"
        if not storage.first_time_signal(key, signal["timestamp"]):
            continue
        message = format_signal(market, signal)
        for chat_id in storage.subscribers():
            try:
                await context.bot.send_message(chat_id=chat_id, text=message)
            except Exception as exc:
                log.warning("Could not send alert to chat %s: %s", chat_id, str(exc)[:160])
    log.info("Scheduled scan complete: %d setups; %d market notes", len(found), len(notes))

async def post_init(application: Application):
    await data_client.start()
    log.info("MacroEdge Telegram signals bot started; six markets configured")

async def post_shutdown(application: Application):
    await data_client.close()

def main():
    application = (Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build())
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("markets", markets_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_cmd))
    application.add_handler(CommandHandler("scan", scan_cmd))
    application.add_handler(CommandHandler("signals", signals_cmd))
    # 15-minute cadence; one run at a time due to scan_lock.
    application.job_queue.run_repeating(
        scheduled_scan, interval=int(bot_cfg["scan_interval_seconds"]), first=60,
        name="market-scan"
    )
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
