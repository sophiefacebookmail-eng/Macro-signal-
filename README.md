# MacroEdge Forex Signals Bot — rate-limited build

Signal-only Telegram bot for six instruments:
- XAU/USD, GBP/USD, EUR/USD, USD/JPY, BTC/USD, ETH/USD

## Railway deployment

1. Upload the contents of this project folder to the **root** of your private GitHub repository (not the ZIP file).
2. In Railway, use the existing GitHub service.
3. Set the start command to `python telegram_bot.py`.
4. Add Railway Variables:
   - `TELEGRAM_BOT_TOKEN`
   - `TWELVEDATA_API_KEY`
5. Redeploy and inspect Deploy Logs.
6. In Telegram, send `/start`, then `/markets`, `/status`, and `/scan`.

## Rate-limit protection

Requests are serialized and spaced by at least 9 seconds, which targets no more than about 7 requests per rolling minute. A 429/credit-limit response causes a 65-second wait and one retry. A short cache avoids duplicate requests for the same instrument. Manual and scheduled scans cannot overlap.

A six-market scan may take around 45–60 seconds. The 15-minute schedule is deliberately conservative. The actual Twelve Data allowance and symbol availability depend on the user's subscription. BTC/USD and ETH/USD may require a plan that includes those instruments.

## Important

- This bot does not place orders.
- Entry, stop and target values are illustrative ATR-based research references, not guaranteed fills or financial advice.
- Do not commit `.env` or expose tokens in screenshots.
- Rotate any token that has appeared in logs or screenshots.
- HTTP client debug logging is suppressed to reduce the chance of credential-bearing request URLs appearing in Railway logs.

## Local run

```bash
pip install -r requirements.txt
cp .env.example .env
# Set environment variables in your shell or hosting dashboard.
python telegram_bot.py
```
