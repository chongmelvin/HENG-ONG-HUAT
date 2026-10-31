"""Command registry: the single source for /help, /help <command> and the PDF guide."""
from __future__ import annotations

# name, usage, what it does, example, release
COMMANDS: list[tuple[str, str, str, str, str]] = [
    ("start", "/start", "First-time setup wizard (also /setup)", "/start", "v1"),
    ("setup", "/setup [module]", "Resume setup, or rerun one module", "/setup bills", "v1"),
    ("add", "/add", "Guided expense entry with buttons", "/add", "v1"),
    ("income", "/income <amount> <source> <account> [gross N deductions N]", "Log income, optional payslip fields", "/income 3500 salary dbs", "v1"),
    ("undo", "/undo", "Remove your last entry", "/undo", "v1"),
    ("edit", "(tap Edit under an entry)", "Change an entry's amount, category, account, people, place or date", "Tap Edit", "v1"),
    ("search", "/search <word>", "Find entries", "/search grab", "v1"),
    ("today", "/today", "List today's entries", "/today", "v1"),
    ("budget", "/budget [set <category|total|yearly> <amount>]", "Show every bucket, or change a limit", "/budget set food 650", "v1"),
    ("owed", "/owed [person]", "See who owes you", "/owed bob", "v1"),
    ("settle", "/settle <person> <amount> <account>", "Record money a friend paid back", "/settle bob 40 paynow", "v1"),
    ("with", "/with [person]", "Spend with one person, or the ranking of everyone", "/with bob", "v1"),
    ("people", "/people add|rename|merge|archive", "Manage the people you spend with", "/people add Sam friend", "v1"),
    ("refund", "/refund <amount> <category> <account>", "Record money back from a shop", "/refund 20 shopping cc", "v1"),
    ("bills", "/bills", "See bills and their reminder dates", "/bills", "v1"),
    ("report", "/report [YYYY-MM | year [YYYY]]", "Monthly or yearly report (message and PDF)", "/report 2026-09", "v1"),
    ("settings", "/settings [persona|indicators|reports|category|account|place]", "Change configuration", "/settings persona", "v1"),
    ("help", "/help [command]", "This list, or a quick reminder for one command", "/help settle", "v1"),
    ("accounts", "/accounts", "Accounts and balances (PIN)", "/accounts", "v1.5"),
    ("transfer", "/transfer <amount> <from> <to>", "Move money between accounts", "/transfer 200 dbs cash", "v1.5"),
    ("networth", "/networth", "Net worth, fixed and variable assets (PIN)", "/networth", "v1.5"),
    ("snapshot", "/snapshot", "Monthly balances and reconciliation (PIN)", "/snapshot", "v1.5"),
    ("allocate", "/allocate <amount> <bucket>", "Allocate money to a savings bucket", "/allocate 2000 house", "v1.5"),
    ("buckets", "/buckets [new <name> <target>]", "Savings buckets and progress", "/buckets", "v1.5"),
    ("claims", "/claims", "Reimbursements: list and submit", "/claims", "v1.5"),
    ("claim", "/claim paid <claimant> <amount> <account>", "Record a reimbursement payout", "/claim paid acme 25 dbs", "v1.5"),
    ("vouchers", "/vouchers  or  +CDC 100 exp 31 dec", "Voucher balances and expiry", "/vouchers", "v1.5"),
    ("item", "/item <name>  or  /item add", "Big-ticket items, warranties, receipts", "/item desk", "v1.5"),
    ("insurance", "/insurance [add ...]", "Policies and premiums (PIN)", "/insurance", "v1.5"),
    ("coverage", "/coverage <name>", "What a policy covers, from your notes (PIN)", "/coverage prudential", "v1.5"),
    ("cards", "/cards [statement <card> <total>]", "Credit card cycle summary", "/cards", "v1.5"),
    ("calendar", "/calendar [YYYY-MM]", "Month calendar of net spend", "/calendar", "v1.5"),
    ("day", "/day <number>", "One day's entries", "/day 11", "v1.5"),
    ("review", "/review", "Monthly guided review", "/review", "v1.5"),
    ("export", "/export [year]", "CSV export (PIN)", "/export 2026", "v1.5"),
    ("trip", "/trip start|pause|resume|end|summary", "Travel mode with foreign currency", "/trip start Japan 20 Nov to 27 Nov jpy", "v2"),
    ("invest", "/invest [add|refresh]", "Investment values and holdings (PIN)", "/invest", "v2"),
    ("rewards", "/rewards [confirm <card> <balance> | rule <card> <category> <rate> [cap N] [min N]]", "Miles, cashback and expiry", "/rewards", "v2"),
    ("bestcard", "/bestcard <merchant> <amount>  |  /bestcard map <word> <category>", "Best card for a purchase", "/bestcard grab 20", "v2"),
    ("subs", "/subs [add <name> <amount>]", "Subscriptions and renewals", "/subs", "v2"),
    ("loans", "/loans [add <lender> <balance> <rate%> <instalment>]", "Loans and payoff scenarios", "/loans", "v2"),
    ("yearplan", "/yearplan [add <name> <amount> <month>]", "Annual expenses calendar and sinking funds", "/yearplan", "v2"),
    ("fees", "/fees", "Fees paid this year", "/fees", "v2"),
]

BY_NAME = {c[0]: c for c in COMMANDS}
LIVE = {"v1", "v1.5", "v2"}


def usage_text(name: str) -> str | None:
    c = BY_NAME.get(name.lower().lstrip("/"))
    return f"{c[1]}\n{c[2]}. Example: {c[3]}" if c else None
