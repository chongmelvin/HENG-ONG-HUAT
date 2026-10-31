# Architecture

```
Telegram  <->  bot/telegram_app.py  (auth, send, receipts, jobs)      <- thin adapter
                    |
                 bot/engine.py  (routing, PIN gate, callbacks)         <- the brain, no Telegram imports
        +-----------+-----------+------------------+
   expense_flow  commands_v1/15/2  setup_flow        jobs
        |
     core/  (ledger, splits, budgets, people, bills, networth, claims, vouchers, items, insurance, cards, savings)
     v2/    (fx, trips, investments, rewards, bestcard, subscriptions, loans, annual, llm)
     parsing/ (dates, expense text parser)
     reports/ (dataset -> messages + monthly_pdf + yearly_pdf)       <- Telegram message, PDF and calendar read ONE dataset
        |
     storage/  base.Repo  <-  MemoryRepo (tests)  |  SheetsRepo (production)
```

## Rules that keep it correct

1. **Services never touch Telegram or Sheets.** They take a `Repo`, so every flow runs in tests with `MemoryRepo`.
2. **One dataset per report.** `reports/dataset.py` computes everything once; the message, PDF and calendar render from it, so numbers always match.
3. **Net spend** (`core/ledger.NetIndex`) = paid − friend repayments − claim payouts − linked refunds. Budgets and reports use it. Repayments reduce the month of the *original* expense.
4. **Spent with** (`core/people.py`) = your *share* of each entry a person is on, counted in full per person. Repayments never change it.
5. **Reconciliation** (`core/networth.py`) compares typed balances with balances derived from flows, per fixed account, zero tolerance. Only the gap left after review is written off, as an Adjustment.
6. **Reports are configuration-driven.** No category, card, policy, account or person is hard-coded. Sections appear only when there is data; renamed or archived items keep history by stable ID.
7. **Personality is cosmetic** (`messaging/templates.py`). Numbers, buttons and the order of facts never change. Security, errors that touch money and sensitive content stay plain.
8. **The LLM is read-only.** `v2/llm.py` exposes query tools only. There is no tool that writes.

## Data

Each dataclass in `domain/models.py` is one Sheet tab; the header row is the field list. `storage/codec.py` keeps scalar cells human-editable and puts lists/dicts in one JSON cell. On startup `SheetsRepo.verify_schema()` refuses to run if a header was changed by hand.

## Idempotency and safety

- Telegram `update_id`s are recorded (`Processed`) so a redelivery is ignored.
- Scheduled jobs write a `job:<date>` marker so a restart at 9:00 cannot resend everything.
- Two-part allowlist: your user ID **and** your private group; everything else is ignored silently.
- PIN: PBKDF2 hash only, message deleted on read, 3 wrong tries lock sensitive commands for 15 minutes, unlock lasts 15 minutes. The bot refuses a PIN it cannot delete.
- Webhook requires an unguessable path **and** Telegram's secret-token header.
