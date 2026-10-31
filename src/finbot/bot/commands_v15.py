"""v1.5 commands: accounts, net worth, claims, vouchers, big-ticket, insurance, cards, calendar, review (PRD 5)."""
from __future__ import annotations

import calendar
import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal

from ..core import (bills as bills_core, budgets, cards as cards_core, claims as claims_core, indicators as ind, insurance as ins_core,
                    items as items_core, networth, savings, splits, vouchers)
from ..core.indicators import expiry_light
from ..core.ledger import LedgerError, NetIndex, active_expenses, create_transfer
from ..core.lookup import find_account, norm
from ..domain.enums import ACTIVE, AccountType, Bucket
from ..domain.models import Account, Claim, ClaimStatus, Expense, Item, Pending, ReviewSession, SavingsBucket, Voucher
from ..domain.money import D, ZERO, fmt
from ..parsing.dates import MONTHS
from ..reports import dataset, messages, monthly_pdf, yearly_pdf
from .types import Button, Reply


def _amt(t: str) -> Decimal:
    try:
        return D(t)
    except ValueError:
        raise LedgerError("I need a number, for example 40.00.")


class CommandsV15:
    # ------------------------------------------------------------------ accounts and transfers
    def cmd_accounts(self, args: str) -> list[Reply]:
        s = self.settings()
        bal = networth.computed_balances(self.repo, s)
        lines = []
        for a in self.repo.all(Account):
            if a.status == ACTIVE and a.type != AccountType.VOUCHER:
                lines.append(f"{a.name} ({a.type.value}): {fmt(bal.get(a.id, ZERO))}")
        return [Reply("\n".join(lines) or "No accounts yet.", sensitive=True)]

    def cmd_transfer(self, args: str) -> list[Reply]:
        toks = args.split()
        if len(toks) < 3:
            return [Reply("Usage: /transfer 200 dbs cash")]
        amount = _amt(toks[0])
        accts = []
        rest = toks[1:]
        for L in (2, 1):
            pass
        a1 = find_account(self.repo, rest[0]) or find_account(self.repo, " ".join(rest[:2]))
        used = 2 if find_account(self.repo, " ".join(rest[:2])) else 1
        a2 = find_account(self.repo, " ".join(rest[used:]))
        if not a1 or not a2:
            return [Reply("I couldn't match both accounts. Example: /transfer 200 dbs cash")]
        create_transfer(self.repo, self.now(), from_account=a1.id, to_account=a2.id, amount=amount, on=self.today())
        return [Reply(f"✅ Transferred {fmt(amount)} from {a1.name} to {a2.name}. A transfer is not an expense or income.")]

    # ------------------------------------------------------------------ net worth and snapshot
    def cmd_networth(self, args: str) -> list[Reply]:
        snaps = networth.snapshots(self.repo)
        if not snaps:
            return [Reply("No snapshot yet. Run /snapshot to set your starting balances.", sensitive=True)]
        cur = snaps[-1]
        prev = networth.previous_snapshot(self.repo, cur.date)
        b = self.badge()
        ch = (cur.net_worth - prev.net_worth) if prev else None
        head = f"Net worth ({cur.date:%-d %b}): {fmt(cur.net_worth, 0)}"
        if prev:
            head += f" {b.pre(ind.networth_light(ch, prev.net_worth))}{'up' if ch >= 0 else 'down'} {fmt(abs(ch), 0)}"
        return [Reply(f"{head}\nFixed {fmt(cur.fixed, 0)} | Variable {fmt(cur.variable, 0)}\nMoney owed to you: {fmt(cur.owed, 0)}", sensitive=True)]

    def cmd_snapshot(self, args: str) -> list[Reply]:
        s = self.settings()
        accts = networth.fixed_accounts(self.repo)
        if not accts:
            return [Reply("Add accounts first with /settings account add.")]
        p = self.pend("snapshot", {"queue": [a.id for a in accts], "entered": {}, "i": 0}, awaiting_text=True)
        return [self.snapshot_prompt(p)]

    def snapshot_prompt(self, p: Pending) -> Reply:
        d = p.payload
        a = self.repo.get(Account, d["queue"][d["i"]])
        exp = networth.computed_balances(self.repo, self.settings()).get(a.id)
        first = self.settings().first_snapshot_date is None
        label = f"Step {d['i'] + 1}/{len(d['queue'])}: balance of {a.name}" + (" (owed, enter as a negative number)" if a.is_liability else "") + "?"
        btn = [] if first or exp is None else [[Button(f"Same as expected ({fmt(exp)})", self.cb(p, "same", str(exp)))]]
        return Reply(label, btn)

    def snapshot_text(self, p: Pending, text: str) -> list[Reply]:
        try:
            v = D(text)
        except ValueError:
            return [Reply("I need an exact number, for example 18200.50.")]
        return self._snapshot_record(p, v)

    def snapshot_callback(self, p: Pending, action: str, arg: str) -> list[Reply]:
        if action == "same":
            return self._snapshot_record(p, D(arg))
        if action == "writeoff":
            return self.snapshot_finish(p.payload, write_off=True)
        return [Reply("Okay. Add the missing entries, then run /snapshot again.")]

    def _snapshot_record(self, p: Pending, v: Decimal) -> list[Reply]:
        d = p.payload
        d["entered"][d["queue"][d["i"]]] = str(v)
        d["i"] += 1
        self.drop(p)
        if d["i"] < len(d["queue"]):
            p2 = self.pend("snapshot", d, awaiting_text=True)
            return [self.snapshot_prompt(p2)]
        return self.snapshot_finish(d, write_off=False)

    def snapshot_finish(self, d: dict, write_off: bool) -> list[Reply]:
        s = self.settings()
        entered = {k: D(v) for k, v in d["entered"].items()}
        b = self.badge()
        recon = networth.reconcile(self.repo, s, entered, self.today())
        if not recon.first and recon.gap != 0 and not write_off:
            movers = ", ".join(f"{m.account.name} {fmt(m.gap, sign=True)}" for m in recon.movers[:3])
            p = self.pend("snapshot", d)
            return [Reply(f"{b.pre(ind.RED)}Fixed assets: expected {fmt(sum((r.expected for r in recon.rows), ZERO))}, you entered {fmt(sum((r.entered for r in recon.rows), ZERO))}. Gap: {fmt(recon.gap)}.\n"
                          f"Biggest movers: {movers}.\nAdd any missing expense, income or transfer, then run /snapshot again, or write off what remains.",
                          [[Button("Write off the gap", self.cb(p, "writeoff")), Button("I'll keep looking", self.cb(p, "cancel"))]], sensitive=True)]
        snap, recon = networth.take_snapshot(self.repo, s, self.now(), entered, write_off=write_off)
        prev = networth.previous_snapshot(self.repo, snap.date)
        if recon.first:
            return [Reply(f"✅ Starting balances saved. Net worth {fmt(snap.net_worth, 0)}. Reconciliation starts with your next snapshot.", sensitive=True)]
        lead = f"{b(ind.OK)} " + self.msg.say("reconciled") if recon.gap == 0 else f"{b(ind.RED)} Gap of {fmt(snap.written_off)} written off as an unexplained adjustment."
        ch = f" Net worth {fmt(snap.net_worth, 0)}" + (f" ({fmt(snap.net_worth - prev.net_worth, 0, sign=True)})." if prev else ".")
        return [Reply(lead + ch, sensitive=True)]

    # ------------------------------------------------------------------ savings buckets
    def cmd_buckets(self, args: str) -> list[Reply]:
        toks = args.split()
        if toks and toks[0] == "new" and len(toks) >= 2:
            tgt = D(toks[-1]) if len(toks) >= 3 and re.match(r"^\d", toks[-1]) else ZERO
            name = " ".join(toks[1:-1] if tgt else toks[1:])
            savings.create_bucket(self.repo, name.title(), tgt)
            return [Reply(f"✅ Created {name.title()}.")]
        rows = savings.progress(self.repo, self.today())
        if not rows:
            return [Reply("No savings buckets yet. Create one: /buckets new House 50000")]
        lines = [f"{r['bucket'].name}: {fmt(r['balance'], 0)}" + (f" of {fmt(r['bucket'].target, 0)} ({r['pct']:.0f}%)" if r["bucket"].target else "") + (f", on pace for {r['eta']:%b %Y}" if r["eta"] else "") for r in rows]
        snaps = networth.snapshots(self.repo)
        if snaps:
            over = savings.check_total(self.repo, snaps[-1].net_worth)
            if over:
                lines.append(f"⚠️ Buckets add up to {fmt(over)} more than your assets.")
        return [Reply("\n".join(lines))]

    def cmd_allocate(self, args: str) -> list[Reply]:
        toks = args.split()
        if len(toks) < 2:
            return [Reply("Usage: /allocate 2000 house")]
        amount, name = _amt(toks[0]), " ".join(toks[1:])
        b = next((x for x in self.repo.all(SavingsBucket) if norm(x.name) == norm(name)), None)
        if not b:
            return [Reply(f"I don't have a bucket called {name}. Create it: /buckets new {name.title()} 50000")]
        savings.allocate(self.repo, b.id, amount, self.today())
        return [Reply(f"✅ Allocated {fmt(amount)} to {b.name}. Now {fmt(savings.balance(self.repo, b.id))}. (Virtual: no money moved.)")]

    # ------------------------------------------------------------------ claims
    def cmd_claims(self, args: str) -> list[Reply]:
        pend = claims_core.pending(self.repo)
        if not pend:
            return [Reply("No claims outstanding.")]
        out, by = [], {}
        for c in pend:
            by.setdefault(c.claimant, []).append(c)
        for who, cs in by.items():
            tot = sum((c.outstanding for c in cs), ZERO)
            st = "Unclaimed" if any(c.status == ClaimStatus.UNCLAIMED for c in cs) else "Submitted"
            btn = [[Button("Submit batch", f"x:claim:{who}:submit")]] if st == "Unclaimed" else [[Button("Mark rejected", f"x:claim:{cs[0].id}:reject")]]
            out.append(Reply(f"{who}: {fmt(tot)} ({st}, {len(cs)} item(s))", btn))
        return out

    def claim_callback(self, key: str, action: str) -> list[Reply]:
        if action == "submit":
            batch, todo = claims_core.submit(self.repo, self.now(), key)
            return [Reply(f"✅ Batch submitted: {fmt(sum((c.amount for c in todo), ZERO))} to {key}.")]
        if action == "reject":
            c = self.repo.get(Claim, key)
            p = self.pend("confirm", {"do": "noop", "args": {}})
            claims_core.reject(self.repo, self.now(), key)
            return [Reply(f"Marked rejected. The {fmt(c.amount)} stays as your own spending.")]
        return [Reply("Unknown action.")]

    def cmd_claim(self, args: str) -> list[Reply]:
        toks = args.split()
        if len(toks) < 3 or toks[0].lower() != "paid":
            return [Reply("Usage: /claim paid acme 25 dbs")]
        acct = find_account(self.repo, " ".join(toks[3:])) if len(toks) > 3 else None
        return self.claim_pay(toks[1], _amt(toks[2]), acct.id if acct else self._default_account())

    def claim_pay(self, claimant: str, amount: Decimal, account_id: str, confirm: bool = False) -> list[Reply]:
        try:
            claims_core.pay(self.repo, self.now(), claimant, amount, account_id, confirm_excess=confirm)
        except claims_core.ExcessPayout as e:
            p = self.pend("confirm", {"do": "claim_excess", "args": {"claimant": claimant, "amount": str(amount), "account": account_id}})
            return [Reply(f"⚠️ The open claim is only {fmt(e.owed)}. Record {fmt(e.owed)} and treat {fmt(e.excess)} as other money?", self.buttons(p, [("Yes", "ok", ""), ("Change amount", "cancel", "")]))]
        return [Reply(f"✅ Reimbursement {fmt(amount)} recorded into {self.acct_name(account_id)}. It lowers that expense's net spend; it is not income.")]

    # ------------------------------------------------------------------ vouchers
    def cmd_vouchers(self, args: str) -> list[Reply]:
        rows = vouchers.summary(self.repo, self.today())
        if not rows:
            return [Reply("No vouchers. Add one: +CDC 100 exp 31 dec")]
        b = self.badge()
        lines = [f"{b.pre(r['light'])}{r['voucher'].scheme}{' ' + r['voucher'].label if r['voucher'].label else ''} {fmt(r['voucher'].remaining)}, {r['days_left']} days left (expires {r['voucher'].expires:%-d %b})" for r in rows]
        lines.append("Vouchers are not included in net worth.")
        return [Reply("\n".join(lines))]

    def voucher_quick_add(self, scheme: str, amount: str, expiry_text) -> list[Reply]:
        exp = self._parse_expiry(expiry_text) if expiry_text else None
        if expiry_text and exp is None:
            return [Reply("I couldn't read that expiry date. Try 31 dec.")]
        if exp is None:
            self.pend("voucher_expiry", {"scheme": scheme.upper(), "amount": amount}, awaiting_text=True)
            return [Reply('When does it expire? (e.g. 31 dec, or "none")')]
        v = vouchers.add_voucher(self.repo, self.now(), scheme.upper(), D(amount), exp)
        return [Reply(f"✅ Added {v.scheme} voucher: {fmt(v.original)}, expires {v.expires:%a %-d %b %Y}.")]

    def voucher_expiry_text(self, p: Pending, text: str) -> list[Reply]:
        self.drop(p)
        exp = date(9999, 12, 31) if norm(text) == "none" else self._parse_expiry(text)
        if exp is None:
            self.pend("voucher_expiry", p.payload, awaiting_text=True)
            return [Reply("I couldn't read that. Try 31 dec, or none.")]
        v = vouchers.add_voucher(self.repo, self.now(), p.payload["scheme"], D(p.payload["amount"]), exp)
        return [Reply(f"✅ Added {v.scheme} voucher: {fmt(v.original)}.")]

    def _parse_expiry(self, text: str):
        m = re.match(r"^(\d{1,2})\s+([a-z]{3,4})(?:\s+(\d{4}))?$", text.strip().lower())
        if not m or m.group(2)[:3] not in MONTHS:
            return None
        y = int(m.group(3)) if m.group(3) else self.today().year
        try:
            d = date(y, MONTHS[m.group(2)[:3]], int(m.group(1)))
        except ValueError:
            return None
        if d < self.today() and not m.group(3):
            d = date(y + 1, d.month, d.day)
        return d

    def voucher_callback(self, vid: str, action: str, arg: str) -> list[Reply]:
        if action == "expired":
            v = self.repo.get(Voucher, vid)
            p = self.pend("confirm", {"do": "expire_voucher", "args": {"vid": vid}})
            return [Reply(f"Mark {fmt(v.remaining)} as expired unused?", self.buttons(p, [("Confirm", "ok", ""), ("It was extended", "cancel", "")]))]
        return [Reply("Okay.")]

    # ------------------------------------------------------------------ big-ticket items
    def bigticket_callback(self, p: Pending, action: str, arg: str) -> list[Reply]:
        eid = p.payload["expense_id"]
        if action == "bt" and arg == "no" or (action == "bt" and arg == "skip"):
            self.drop(p)
            return [Reply("Okay, skipped. You can add it later with /item add.")]
        if action == "bt" and arg == "yes":
            self.drop(p)
            p2 = self.pend("bigticket", {"expense_id": eid, "step": "warranty"})
            return [Reply("Warranty length?", self.buttons(p2, [("1 yr", "w", "12"), ("2 yrs", "w", "24"), ("3 yrs", "w", "36"), ("None", "w", "0")]))]
        if action == "w":
            e = self.repo.get(Expense, eid)
            self.drop(p)
            it = items_core.create_item(self.repo, self.now(), e, e.description or self.cat_name(e.category_id), int(arg))
            self.pend("receipt_name", {"item_id": it.id}, awaiting_text=False)
            return [Reply(f"✅ Tracking {it.name}" + (f", warranty ends {it.warranty_end:%-d %b %Y}." if it.warranty_end else ".") + " Send the receipt or warranty now (photo or PDF).")]
        return [Reply("Okay.")]

    def item_name_text(self, p: Pending, text: str) -> list[Reply]:
        self.drop(p)
        return self.handle_text(text)

    def handle_file(self, *, file_id: str, link: str = "", caption: str = "") -> list[Reply]:
        """A receipt or warranty sent into the group. Attach it to the named or latest item."""
        its = self.repo.all(Item)
        target = items_core.find_item(self.repo, caption) if caption else None
        if target is None:
            waiting = [p for p in self.repo.all(Pending) if p.kind == "receipt_name"]
            if waiting:
                target = self.repo.get(Item, max(waiting, key=lambda x: x.created).payload["item_id"])
                self.drop(max(waiting, key=lambda x: x.created))
        if target is None:
            if not its:
                return [Reply("I saved nothing: there is no item to attach this to yet.")]
            p = self.pend("receipt_pick", {"file_id": file_id, "link": link})
            return [Reply("Which item is this receipt for?", self.buttons(p, *[[(i.name, "pick", i.id)] for i in its[:6]]))]
        items_core.attach_receipt(self.repo, target.id, link, file_id)
        tail = "" if link else " I couldn't make a message link here (the group must be a supergroup), so I'll send the file itself when you ask."
        return [Reply(f"✅ Saved the receipt for {target.name}." + (f" Warranty ends {target.warranty_end:%-d %b %Y}." if target.warranty_end else "") + tail)]

    def cmd_item(self, args: str) -> list[Reply]:
        if not args.strip():
            its = self.repo.all(Item)
            return [Reply("Items: " + (", ".join(i.name for i in its) or "none yet"))]
        it = items_core.find_item(self.repo, args.strip())
        if not it:
            return [Reply(f'I couldn\'t find "{args.strip()}". Items: {", ".join(i.name for i in self.repo.all(Item)) or "none"}.')]
        wl = ""
        if it.warranty_end:
            days = (it.warranty_end - self.today()).days
            wl = f", warranty to {it.warranty_end:%-d %b %Y} ({self.badge().pre(expiry_light(days))}{days} days)"
        text = f"{it.name}, {fmt(it.price)}, bought {it.purchase_date:%-d %b %Y}{wl}."
        if it.receipt_link:
            text += f"\nReceipt: {it.receipt_link}"
        return [Reply(text, [[Button("Send file", f"x:itemfile:{it.id}")]] if it.file_id else [])]

    # ------------------------------------------------------------------ insurance, cards
    def cmd_insurance(self, args: str) -> list[Reply]:
        s = ins_core.summary(self.repo, self.today())
        if not s["policies"]:
            return [Reply("No policies yet. Add them in /setup insurance.", sensitive=True)]
        b = self.badge()
        lines = [f"Annual premiums {fmt(s['annual'], 0)} ({fmt(s['monthly'], 0)} a month)."]
        if s["due_90"]:
            p, d = s["due_90"][0]
            days = (d - self.today()).days
            lines.append(f"Next due: {b.pre(ind.bill_light(days))}{p.insurer} {fmt(p.premium, 0)} on {d:%-d %b} (in {days} days).")
        lines.append("By type: " + ", ".join(f"{k} {fmt(v, 0)}" for k, v in s["by_type"].items()) + ".")
        return [Reply("\n".join(lines), sensitive=True)]

    def cmd_coverage(self, args: str) -> list[Reply]:
        found = ins_core.coverage_of(self.repo, args.strip() or "")
        if not found:
            return [Reply("I couldn't find that policy.", sensitive=True)]
        return [Reply("\n".join(f"{p.insurer} {p.product}: {p.coverage_notes or 'no coverage notes saved yet'}" for p in found), sensitive=True)]

    def cmd_cards(self, args: str) -> list[Reply]:
        toks = args.split()
        s, b = self.settings(), self.badge()
        if toks and toks[0] == "statement" and len(toks) >= 3:
            card = next((c for c in self.repo.all(cards_core.Card) if norm(toks[1]) in norm(c.bank + " " + c.name)), None)
            if not card:
                return [Reply("I couldn't find that card.")]
            gap = cards_core.statement_gap(self.repo, card, _amt(toks[2]), self.today())
            if gap == 0:
                return [Reply(f"✅ Matches your entries.")]
            return [Reply(f"⚠️ You logged {fmt(cards_core.cycle_spend(self.repo, card, self.today()))} for this cycle. Statement says {fmt(_amt(toks[2]))}. {'Missing' if gap > 0 else 'Extra'} {fmt(abs(gap))}.")]
        rows = cards_core.summarise(self.repo, s, self.today())
        if not rows:
            return [Reply("No cards yet. Add them in /setup cards.")]
        return [Reply("\n".join(f"{r.card.bank} {r.card.name}: cycle {r.cycle_start:%-d %b} to {r.cycle_end:%-d %b}, spent {fmt(r.spent)}, due {r.next_due:%-d %b}, utilisation {b.pre(ind.budget_light(r.utilisation_pct))}{r.utilisation_pct:.0f}%" for r in rows))]

    # ------------------------------------------------------------------ calendar and day
    def cmd_calendar(self, args: str) -> list[Reply]:
        y, m = self.today().year, self.today().month
        if re.match(r"^\d{4}-\d{2}$", args.strip()):
            y, m = int(args[:4]), int(args[5:7])
        d = dataset.monthly(self.repo, self.settings(), y, m, self.today())
        cal = calendar.Calendar(0).monthdayscalendar(y, m)
        rows = [f"{calendar.month_name[m]} {y} (net spend by day)", "Mo   Tu   We   Th   Fr   Sa   Su"]
        for wk in cal:
            rows.append(" ".join((f"{d.day_totals.get(x, 0):>4.0f}" if x else "    ") + ("*" if x in d.bill_days else " ") for x in wk))
        no = [x for x in range(1, calendar.monthrange(y, m)[1] + 1) if x not in d.day_totals and date(y, m, x) <= self.today()]
        return [Reply("<pre>" + "\n".join(rows) + "</pre>" + f"\n* bill due. No-entry days: {', '.join(map(str, no)) or 'none'}.\nThe PDF report has the full colour calendar.")]

    def cmd_day(self, args: str) -> list[Reply]:
        try:
            n = int(args.strip())
            d = date(self.today().year, self.today().month, n)
        except ValueError:
            return [Reply("Usage: /day 11")]
        es = [e for e in active_expenses(self.repo) if e.spend_date == d]
        if not es:
            return [Reply(f"Nothing logged on {d:%a %-d %b}.")]
        idx = NetIndex(self.repo)
        return [Reply(f"{d:%a %-d %b}:\n" + "\n".join(f"{e.description or self.cat_name(e.category_id)} {fmt(e.amount)}" + (f" (net {fmt(idx.net(e))})" if idx.net(e) != e.amount else "") for e in es))]

    # ------------------------------------------------------------------ report and export
    def cmd_report(self, args: str) -> list[Reply]:
        toks = args.split()
        today = self.today()
        if toks and toks[0].lower() == "year":
            y = int(toks[1]) if len(toks) > 1 else today.year - 1 if today.month == 1 else today.year
            return self.yearly_report(y)
        if toks and re.match(r"^\d{4}-\d{2}$", toks[0]):
            y, m = int(toks[0][:4]), int(toks[0][5:7])
            if not 1 <= m <= 12:
                return [Reply("I couldn't read that month. Try /report 2026-09.")]
        else:
            y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return self.monthly_report(y, m)

    def monthly_report(self, y: int, m: int) -> list[Reply]:
        s = self.settings()
        d = dataset.monthly(self.repo, s, y, m, self.today())
        if not d.entries and d.nw is None:
            return [Reply(f"{calendar.month_name[m]} report: no entries were logged this month, so there is nothing to summarise.", [[Button("Start monthly review", "x:review:1")]])]
        text = messages.monthly_message(d, self.msg)
        try:
            pdf = monthly_pdf.render(d)
            return [Reply(text, [[Button("Start monthly review", "x:review:1")]], files=[(f"report-{y}-{m:02d}.pdf", pdf)])]
        except Exception:
            import logging
            logging.getLogger(__name__).exception("monthly PDF failed")
            return [Reply(text + "\nThe PDF didn't generate. I'll retry in a few minutes.", [[Button("Retry now", f"x:retrypdf:{y}-{m:02d}"), Button("Start monthly review", "x:review:1")]])]

    def yearly_report(self, y: int) -> list[Reply]:
        d = dataset.yearly(self.repo, self.settings(), y, self.today())
        text = messages.yearly_message(d, self.msg)
        return [Reply(text, files=[(f"report-{y}.pdf", yearly_pdf.render(d))])]

    def cmd_export(self, args: str) -> list[Reply]:
        y = int(args.strip()) if args.strip().isdigit() else self.today().year
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "description", "category", "bucket", "amount", "my_share", "people", "account", "location", "tags"])
        for e in sorted(active_expenses(self.repo), key=lambda e: e.spend_date):
            if e.spend_date.year == y:
                w.writerow([e.spend_date, e.description, self.cat_name(e.category_id), e.bucket.value, e.amount, e.my_share,
                            ";".join(self.person_name(p) for p in e.people), ";".join(self.acct_name(p.account_id) for p in e.payments), e.location, ";".join(e.tags)])
        return [Reply(f"CSV for {y}.", files=[(f"expenses-{y}.csv", buf.getvalue().encode())], sensitive=True)]

    # ------------------------------------------------------------------ monthly guided review
    REVIEW_STEPS = ["Missing entries", "Report highlights", "Receivables", "Claims", "Bills and cards", "Vouchers", "Warranties",
                    "Net worth snapshot", "Savings buckets", "Next month's budget", "Done"]

    def cmd_review(self, args: str) -> list[Reply]:
        t = self.today()
        key = f"{t.year}-{t.month:02d}"
        rs = next((r for r in self.repo.all(ReviewSession) if r.month == key), None)
        if rs and rs.step > 1:
            return [Reply(f"Resuming your {calendar.month_name[t.month]} review at step {rs.step}/11 ({self.REVIEW_STEPS[rs.step - 1]}).", [[Button("Continue", f"x:review:{rs.step}"), Button("Start over", "x:review:1")]])]
        return self.review_step(1)

    def review_callback(self, p, action, arg):
        self.drop(p)
        return self.review_step(int(arg or 1))

    def review_step(self, step: int) -> list[Reply]:
        t = self.today()
        key = f"{t.year}-{t.month:02d}"
        rs = next((r for r in self.repo.all(ReviewSession) if r.month == key), None) or self.repo.add(ReviewSession(id=f"rv{key}", month=key))
        rs.step = step
        self.repo.update(rs)
        title = f"{step}/11 {self.REVIEW_STEPS[step - 1]}"
        body = ""
        if step == 1:
            es = {e.spend_date.day for e in active_expenses(self.repo) if (e.spend_date.year, e.spend_date.month) == (t.year, t.month)}
            miss = [d for d in range(1, t.day + 1) if d not in es]
            body = f"No entries on: {', '.join(map(str, miss)) or 'none'}." if miss else "Every day has an entry."
        elif step == 3:
            body = "\n".join(f"{self.badge().pre(ind.owed_light(splits.oldest_open_days(self.repo, pid, t)))}{self.person_name(pid)} {fmt(v)}" for pid, v in splits.balances(self.repo).items() if v > 0) or "Nothing outstanding."
        elif step == 4:
            body = "\n".join(f"{c.claimant} {fmt(c.outstanding)} ({c.status.value})" for c in claims_core.pending(self.repo)) or "Nothing outstanding."
        elif step == 5:
            body = "\n".join(f"{b.name} due {bills_core.next_due(b, t):%-d %b}" for b in self.repo.find(bills_core.Bill, status=ACTIVE)[:6]) or "No bills set up."
        elif step == 6:
            body = "\n".join(f"{r['voucher'].scheme} {fmt(r['voucher'].remaining)}, {r['days_left']} days" for r in vouchers.summary(self.repo, t) if r["days_left"] <= 60) or "Nothing expiring in the next 60 days."
        elif step == 7:
            body = "\n".join(f"{i.name} warranty ends {i.warranty_end:%-d %b} ({d} days)" for i, d in items_core.expiring_within(self.repo, t, 60)) or "No warranties ending soon."
        elif step == 8:
            body = "Run /snapshot to enter balances and reconcile."
        elif step == 9:
            body = "Use /allocate to move money into your goals, and /buckets to see progress."
        elif step == 10:
            body = "Use /budget set <category> <amount> to adjust limits, or keep them as they are."
        elif step == 11:
            return [Reply(f"✅ Review done. Next review: {date(t.year + (t.month // 12), t.month % 12 + 1, 1):%-d %b}.")]
        nxt = step + 1
        return [Reply(f"{title}\n{body}", [[Button("Next", f"x:review:{nxt}"), Button("Skip", f"x:review:{nxt}")]])]
