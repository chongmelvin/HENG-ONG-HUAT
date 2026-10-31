# Deploy: Telegram + Google Sheets + Railway

## 1. Telegram
1. In Telegram, talk to **@BotFather** → `/newbot`. Copy the token (`BOT_TOKEN`).
2. BotFather → `/mybots` → your bot → *Bot Settings → Group Privacy → Turn off*.
3. Create a **private group** with only you and the bot. In *Group settings* turn on *Chat history: visible* (or make it a supergroup in any other way) so it becomes a **supergroup**; receipt links need that.
4. Make the bot an **admin** with **Delete messages** permission (needed to remove PIN messages).
5. Get your user ID from **@userinfobot** (`OWNER_USER_ID`) and the group ID (forward a group message to @userinfobot, or use `getUpdates`; it starts with `-100`) (`GROUP_CHAT_ID`).
6. Optional: in the group, turn on *Restrict saving content* and turn off invite links.

## 2. Google Sheets
1. Google Cloud console → create a project → enable the **Google Sheets API** and **Google Drive API**.
2. *IAM → Service accounts* → create one → *Keys → Add key → JSON*. Keep the file private.
3. Create an empty Google Sheet. **Share it with the service account's email as Editor.**
4. The long id in the sheet URL is `SHEET_ID`. The JSON file's contents go in `GOOGLE_CREDENTIALS_JSON`.
5. The bot creates every tab itself on first start (`ensure_tabs`). Do not rename header cells (the bot checks them).

## 3. Railway
1. New project → *Deploy from GitHub repo* (this repo). Railway builds the `Dockerfile`.
2. Set the variables from `.env.example`. Generate three long random strings for `WEBHOOK_SECRET`, `WEBHOOK_PATH`, `GUIDE_TOKEN` (`python -c "import secrets;print(secrets.token_urlsafe(24))"`).
3. Set `PUBLIC_URL` to the domain Railway gives you (Settings → Networking → Generate domain).
4. Deploy. On start the bot registers its webhook, checks the group (admin, privacy mode, supergroup) and posts any problems in the group.
5. Open the group and send `/start`. The setup wizard takes about 3 minutes.

Data lives in the Sheet, so redeploys lose nothing. The scheduler runs inside the app at 9:00 Asia/Singapore.

## 4. Local development
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q                       # 100+ tests, no network needed
python scripts/seed_demo.py               # writes demo-monthly.pdf / demo-yearly.pdf
STORAGE=memory MODE=polling BOT_TOKEN=... OWNER_USER_ID=... GROUP_CHAT_ID=... python -m finbot
python scripts/check_setup.py             # verifies Sheet + group before you go live
```

## 5. Before you rely on it
- Run `scripts/check_setup.py` and fix anything it lists.
- Send `/start`, finish setup, then `/snapshot` to enter opening balances (clean slate).
- Pick a market-data source for prices (open question in the PRD): `YahooProvider` and `CoinGeckoProvider` are provided and unofficial; swap in a provider you trust by implementing `PriceProvider`.
- Card earn rules are yours to enter and re-verify (`/rewards rule ...`); the bot never recites them.
