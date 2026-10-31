# finbot: a personal finance Telegram bot (v1, v1.5, v2)

A single-user bot that lives in your private Telegram group. Type `chicken rice 5.50 paylah`; get budgets, net worth,
money owed by friends, reminders, vouchers, claims, travel mode, investments, rewards and monthly and yearly PDF
reports. Data lives in **your own Google Sheet**. Built from the PRD (v4) and tested against its sample flows.

```
chicken rice 5.50 paylah
✅ Saved lah. S$5.50, Food, PayLah, Alone, today.
🟢 Monthly budget left: S$1,240 of S$2,000. 🟢 Food left: S$310 of S$600.
```

## What is in the box

| Release  | What                                                                                                                                                                                                                                                        | Where                                            |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| **v1**   | Setup wizard; free-text and guided entry; backdating; named people and `/with`; splits and `/settle`; budgets (Monthly vs Yearly), traffic lights, personality and scolding; refunds; bills; `/help` PDF guide; safeguards (duplicates, large amounts, PIN) | `bot/`, `core/`, `parsing/`, `messaging/`        |
| **v1.5** | Accounts, transfers, snapshots and zero-tolerance reconciliation (fixed vs variable assets); savings buckets; cards, insurance; claims; vouchers; big-ticket items and receipts; monthly message + PDF with calendar; guided review                         | `core/networth.py`, `core/claims.py`, `reports/` |
| **v2**   | Trips and FX; automatic investment prices; rewards and expiry; best card; subscriptions, loans, annual plan; yearly report; read-only LLM questions                                                                                                         | `v2/`                                            |

## Quick start

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q                      # no network needed
python scripts/seed_demo.py              # sample monthly and yearly PDFs
```

Deploying: see [docs/DEPLOY.md](docs/DEPLOY.md). Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The sample chats and test cases from the PRD: [docs/sample-flows-and-test-cases.md](docs/sample-flows-and-test-cases.md).

## Commands

`/start /setup /add /income /undo /search /today /budget /owed /settle /with /people /refund /bills /report /settings /help`
(v1) · `/accounts /transfer /networth /snapshot /allocate /buckets /claims /claim /vouchers /item /insurance /coverage /cards /calendar /day /review /export`
(v1.5) · `/trip /invest /rewards /bestcard /subs /loans /yearplan /fees` and plain-language questions (v2).
`/help` in the group sends the full guide (generated from `help/registry.py`, so it can't drift).

## How the tricky rules are implemented

- **Net spend** counts the full amount until a friend repays or a claim is paid; a repayment lowers the month of the _original_ expense (`core/ledger.NetIndex`).
- **$80 dinner with Alice and Bob** (`dinner 80 cc split alice bob`): your share S$26.68, they owe S$26.66 each (leftover cents are yours), the budget drops S$80 until they repay, money owed counts as a fixed asset so it never shows as a reconciliation gap.
- **Spent with** = your share of each entry, counted in full per person present; repayments never change the ranking.
- **Reports are configuration-driven**: rename a category, close a card or add a policy and the next report adapts; history keeps its stable IDs.

## Testing

`tests/` has ~110 tests: domain rules, parser, every engine flow (including the unhappy ones from the test-case file), setup wizard, jobs, reports and PDFs, Telegram adapter, webhook server, Sheets repo against a fake spreadsheet, and the LLM tool loop with a scripted client.

## Known gaps (read before relying on it)

These are honest limits of this first build, not hidden behaviour:

1. **Never run against live services.** Telegram, Google Sheets, price feeds, FX and the LLM were exercised only through fakes and stubs. Run `scripts/check_setup.py` and do a dry run in a throwaway group and Sheet first.
2. **Price sources are placeholders.** `YahooProvider` uses an unofficial endpoint and `CoinGeckoProvider` a public one. Pick a source you trust (PRD open question) and implement `PriceProvider`.
3. **`/calendar` in chat is a text grid**; the colour calendar is in the PDF.
4. **PDF retry** after a failed render is a manual button, not a timed retry.
5. **Setup covers v1 and v1.5 modules.** Holdings, earn rules, subscriptions and loans are added with commands (`/invest add`, `/rewards rule`, `/subs add`, `/loans add`, `/yearplan add`) rather than wizard steps.
6. **Google Sheets is the bottleneck by design** (about 60 writes a minute, in-process cache, no transactions). Fine for one user; migrate to SQLite/Postgres past about 50,000 rows (the `Repo` interface makes that a one-file change).
7. **Concurrency:** one process, one user. Run a single replica.
8. **Security:** the PIN is hashed, but it travels through Telegram before the bot deletes it. Group chats are not end-to-end encrypted. See PRD 9.4.
9. **Card and voucher rules are yours to enter and re-verify.** The bot never states them from memory.
