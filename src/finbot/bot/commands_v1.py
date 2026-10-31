"""v1 commands (PRD 4.2 to 4.5)."""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..core import bills as bills_core, budgets, claims as claims_core, items as items_core, people as people_core, splits
from ..core.indicators import owed_light
from ..core.ids import new_id
from ..core.ledger import (LedgerError, NetIndex, active_expenses, check_payslip, create_income, create_refund, delete_expense, last_expense,
                           links_of, recompute_split)
from ..core.lookup import find_account, find_category, find_person, norm
from ..core.pin import SENSITIVE
from ..domain.enums import ACTIVE, AccountType, Bucket, Persona, Relationship
from ..domain.models import Account, Bill, Category, Expense, Person, Receivable
from ..domain.money import D, ZERO, fmt
from .types import Button, Reply

MONEY = re.compile(r"^-?\d[\d,]*(\.\d+)?$")


def _amt(tok: str) -> Decimal:
    try:
        return D(tok)
    except ValueError:
        raise LedgerError("I need a number, for example 40.00.")


class CommandsV1:
    # ------------------------------------------------------------------ /add (guided)
    def cmd_add(self, args: str) -> list[Reply]:
        from ..parsing.expense import parse_expense
        from ..v2 import trips
        s = self.settings()
        if args.strip():
            return self.log_text(args)
        trip = trips.active_trip(self.repo, s)
        d = self.draft_from_parsed(parse_expense(self.repo, s, "", self.today()), trip)
        d["guided"] = True
        return self.advance(d)

    # ------------------------------------------------------------------ /income
    def cmd_income(self, args: str) -> list[Reply]:
        toks = args.split()
        if not toks:
            return [Reply("Usage: /income 3500 salary dbs   (optional: gross 5200 deductions 1000)")]
        amount = _amt(toks[0].lstrip("+"))
        gross = deductions = bonus = None
        rest, i = [], 1
        while i < len(toks):
            t = toks[i].lower()
            if t in ("gross", "deductions", "bonus") and i + 1 < len(toks):
                v = _amt(toks[i + 1])
                if t == "gross":
                    gross = v
                elif t == "deductions":
                    deductions = v
                else:
                    bonus = v
                i += 2
                continue
            rest.append(toks[i])
            i += 1
        acct = None
        for L in (2, 1):
            for j in range(len(rest)):
                cand = " ".join(rest[j:j + L])
                a = find_account(self.repo, cand)
                if a:
                    acct, rest = a, rest[:j] + rest[j + L:]
                    break
            if acct:
                break
        source = " ".join(rest) or "Income"
        implied = check_payslip(gross, deductions, amount)
        if implied is not None:
            p = self.pend("confirm", {"do": "income", "args": {"amount": str(amount), "source": source, "account": acct.id if acct else "", "gross": str(gross), "deductions": str(deductions)}})
            return [Reply(f"⚠️ Gross minus deductions is {fmt(implied)}, but you entered {fmt(amount)} received. Which is right?",
                          self.buttons(p, [(f"Received {fmt(amount)}", "ok", ""), (f"Received {fmt(implied)}", "alt", str(implied)), ("Cancel", "cancel", "")]))]
        if acct is None:
            p = self.pend("income_acct", {"amount": str(amount), "source": source, "gross": str(gross) if gross else "", "deductions": str(deductions) if deductions else ""})
            accts = [a for a in self.repo.all(Account) if a.status == ACTIVE and a.type != AccountType.VOUCHER and not a.is_liability]
            return [Reply("Which account did it go into?", self.buttons(p, *[[(a.name, "acct", a.id) for a in accts[i:i + 3]] for i in range(0, len(accts), 3)]))]
        return [self._save_income(amount, source, acct.id, gross, deductions, bonus)]

    def _save_income(self, amount, source, acct_id, gross=None, deductions=None, bonus=None) -> Reply:
        inc = create_income(self.repo, self.now(), amount=amount, source=source.title() if source.islower() else source, account_id=acct_id,
                            on=self.today(), gross=gross, deductions=deductions, bonus=bonus)
        extra = f" Payslip: gross {fmt(gross)} - deductions {fmt(deductions)} = {fmt(gross - deductions)}." if gross and deductions else ""
        return Reply(f"✅ Saved income: {fmt(amount)}, {inc.source}, into {self.acct_name(acct_id)}, today.{extra}")

    # ------------------------------------------------------------------ /undo, /edit
    def cmd_undo(self, args: str) -> list[Reply]:
        e = last_expense(self.repo)
        if not e:
            return [Reply("Nothing to undo.")]
        today_entry = e.entry_date == self.today()
        if not today_entry and not self.gate.is_unlocked(self.now()):
            return self.need_pin("undo", "")
        delete_expense(self.repo, self.now(), e.id)
        return [Reply(f"✅ Removed your last entry: {fmt(e.amount)}, {self.cat_name(e.category_id)}.", [[Button("Restore", f"e:{e.id}:restore")]])]

    def expense_action(self, eid: str, action: str, arg: str) -> list[Reply]:
        e = self.repo.get(Expense, eid)
        if e is None:
            return [Reply("I can't find that entry.")]
        old = e.spend_date < self.today() and action in ("del", "delok", "yearly", "monthly", "setcat", "setamt") and not self.gate.is_unlocked(self.now())
        if old:
            return self.need_pin("expense_action", f"{eid}|{action}|{arg}")
        if action == "menu":
            return [Reply("What do you want to change?", [[Button("Amount", f"e:{eid}:f:amount"), Button("Category", f"e:{eid}:f:category"), Button("Account", f"e:{eid}:f:account")],
                                                         [Button("With", f"e:{eid}:f:people"), Button("Location", f"e:{eid}:f:location"), Button("Date", f"e:{eid}:f:date")]])]
        if action == "f":
            if arg == "category":
                cats = [c for c in self.repo.all(Category) if c.status == ACTIVE]
                return [Reply("Pick a category:", [[Button(c.name, f"e:{eid}:setcat:{c.id}") for c in cats[i:i + 3]] for i in range(0, len(cats), 3)])]
            if arg == "account":
                accts = [a for a in self.repo.all(Account) if a.status == ACTIVE and a.type != AccountType.VOUCHER]
                return [Reply("Pick an account:", [[Button(a.name, f"e:{eid}:setacct:{a.id}") for a in accts[i:i + 3]] for i in range(0, len(accts), 3)])]
            self.pend("edit", {"expense_id": eid, "field": arg}, awaiting_text=True)
            hint = {"amount": "the new amount", "people": "names, e.g. bob alice (or 'alone')", "location": "the place", "date": "the date (y, -2d, 12 oct)"}[arg]
            return [Reply(f"Send {hint}.")]
        if action == "setcat":
            e.category_id = arg
            self.repo.update(e)
            self.audit("edit", "expenses", eid, "category")
            return [Reply(f"✅ Updated: {fmt(e.amount)}, {self.cat_name(arg)}.")]
        if action == "setacct":
            e.payments[0].account_id = arg
            self.repo.update(e)
            self.audit("edit", "expenses", eid, "account")
            return [Reply(f"✅ Updated: {fmt(e.amount)}, {self.acct_name(arg)}.")]
        if action in ("yearly", "monthly"):
            e.bucket = Bucket(action)
            self.repo.update(e)
            return [Reply(f"✅ Moved to {action.title()}."), *[Reply(l) for l in self._budget_lines(e)]]
        if action == "del":
            lk = links_of(self.repo, eid)
            warn = ""
            if lk["receivables"] or lk["vouchers"] or lk["claims"]:
                warn = "\nThis entry has links: " + ", ".join(filter(None, [
                    f"{len(lk['receivables'])} receivable(s)" + (f" (repaid {fmt(lk['repaid'])} stays as a credit)" if lk["repaid"] else "") if lk["receivables"] else "",
                    "voucher payment (balance is restored)" if lk["vouchers"] else "", "claim" if lk["claims"] else ""]))
            return [Reply(f"Delete {fmt(e.amount)} {self.cat_name(e.category_id)}?{warn}", [[Button("Delete", f"e:{eid}:delok"), Button("Cancel", "x:noop")]])]
        if action == "delok":
            delete_expense(self.repo, self.now(), eid)
            return [Reply("✅ Deleted.")]
        if action == "restore":
            e.status = ACTIVE
            self.repo.update(e)
            return [Reply("✅ Restored.")]
        return [Reply("Unknown action.")]

    def edit_text(self, p, text: str) -> list[Reply]:
        eid, field = p.payload["expense_id"], p.payload["field"]
        self.drop(p)
        e = self.repo.get(Expense, eid)
        try:
            if field == "amount":
                new = _amt(text)
                if e.people and e.split_mode:
                    if e.split_mode == "custom":
                        return [Reply("This is a custom split. Please give the new shares by logging it again.")]
                    pe = self.pend("confirm", {"do": "resplit", "args": {"eid": eid, "amount": str(new)}})
                    recs = splits_preview = None
                    return [Reply(f"Changing the amount to {fmt(new)} recalculates the shares by the original split. Confirm?", self.buttons(pe, [("Confirm", "ok", ""), ("Cancel", "cancel", "")]))]
                e.amount = new
                e.my_share = new
                e.payments = [type(e.payments[0])(e.payments[0].account_id, new)]
            elif field == "location":
                e.location = text.strip().title()
            elif field == "people":
                names = [] if norm(text) in ("alone", "none") else text.replace("@", " ").split()
                ids = []
                for n in names:
                    pr = find_person(self.repo, n)
                    if not pr:
                        return [Reply(f"I don't know {n.title()}. Add them with /people add {n.title()} friend.")]
                    ids.append(pr.id)
                e.people = ids
            elif field == "date":
                from ..parsing.dates import relative
                d = relative(text.strip(), self.today())
                if not d:
                    return [Reply("Try y, -2d, or today.")]
                e.spend_date = d
        except LedgerError as err:
            return [Reply(str(err))]
        self.repo.update(e)
        self.audit("edit", "expenses", eid, field)
        return [Reply(f"✅ Updated {field}.")]

    # ------------------------------------------------------------------ /search /today
    def cmd_search(self, args: str) -> list[Reply]:
        q = norm(args)
        if not q:
            return [Reply("Usage: /search grab")]
        idx = NetIndex(self.repo)
        hits = [e for e in active_expenses(self.repo) if q in norm(f"{e.description} {self.cat_name(e.category_id)} {e.location} {e.item}")]
        hits.sort(key=lambda e: e.spend_date, reverse=True)
        if not hits:
            return [Reply(f'No entries match "{args}".')]
        lines = [f"{e.spend_date:%-d %b}  {fmt(e.amount)}  {e.description or self.cat_name(e.category_id)}" for e in hits[:15]]
        total = sum((idx.net(e) for e in hits), ZERO)
        return [Reply(f"{len(hits)} entries, net {fmt(total)}:\n" + "\n".join(lines) + ("\n..." if len(hits) > 15 else ""))]

    def cmd_today(self, args: str) -> list[Reply]:
        t = self.today()
        es = [e for e in active_expenses(self.repo) if e.spend_date == t]
        if not es:
            return [Reply("Nothing logged today yet.")]
        idx = NetIndex(self.repo)
        return [Reply(f"Today ({t:%a %-d %b}):\n" + "\n".join(f"{fmt(e.amount)}  {e.description or self.cat_name(e.category_id)} ({self.acct_name(e.account_id)})" for e in es)
                      + f"\nNet {fmt(sum((idx.net(e) for e in es), ZERO))}")]

    # ------------------------------------------------------------------ /budget
    def cmd_budget(self, args: str) -> list[Reply]:
        toks = args.split()
        b, today = self.badge(), self.today()
        if toks and toks[0].lower() == "set":
            if len(toks) < 3:
                return [Reply("Usage: /budget set food 650   (or: total, yearly)")]
            try:
                amount = _amt(toks[-1])
            except LedgerError:
                return [Reply("I need a number, for example: /budget set food 650")]
            name = " ".join(toks[1:-1])
            if norm(name) in ("total", "monthly", "total monthly"):
                scope = budgets.TOTAL_M
            elif norm(name) in ("yearly", "year", "total yearly"):
                scope = budgets.TOTAL_Y
            else:
                c = find_category(self.repo, name)
                if not c:
                    p = self.pend("confirm", {"do": "newcat", "args": {"name": name.title(), "amount": str(amount)}})
                    return [Reply(f'I don\'t have a category called "{name}". Create it?', self.buttons(p, [("Create", "ok", ""), ("Cancel", "cancel", "")]))]
                scope = f"category:{c.id}"
            budgets.set_limit(self.repo, self.now(), scope, amount)
            out = [Reply(f"✅ {name.title()} limit is now {fmt(amount, 0)}.")]
            tot = budgets.limit_in_force(self.repo, budgets.TOTAL_M, today)
            ssum = budgets.category_limit_sum(self.repo, today)
            if tot and ssum > tot:
                p = self.pend("noop", {})
                out.append(Reply(f"⚠️ Category limits now add up to {fmt(ssum, 0)}, above your total Monthly limit of {fmt(tot, 0)}. Keep it?", [[Button("Keep", "x:noop"), Button("Cancel", "x:noop")]]))
            return out
        idx, exps = NetIndex(self.repo), active_expenses(self.repo)
        s, e = budgets.month_bounds(today.year, today.month)
        lines = [f"Budget, {today:%B %Y}:"]
        tl = budgets.limit_in_force(self.repo, budgets.TOTAL_M, today)
        if tl:
            sp = budgets.spent(idx, exps, s, e, bucket=Bucket.MONTHLY)
            l = budgets._line("Monthly", sp, tl)
            lines.append(f"{b.pre(l.light)}Monthly: {fmt(sp, 0)} of {fmt(tl, 0)} ({l.used_pct:.0f}%), {fmt(l.left, 0)} left")
        for c in self.repo.all(Category):
            if c.status != ACTIVE or c.default_bucket != Bucket.MONTHLY:
                continue
            lim = budgets.limit_in_force(self.repo, f"category:{c.id}", today)
            sp = budgets.spent(idx, exps, s, e, bucket=Bucket.MONTHLY, category_id=c.id)
            if lim:
                l = budgets._line(c.name, sp, lim)
                lines.append(f"  {b.pre(l.light)}{c.name}: {fmt(sp, 0)} of {fmt(lim, 0)} ({l.used_pct:.0f}%)")
            elif sp:
                lines.append(f"  {c.name}: {fmt(sp, 0)} (no limit)")
        yl = budgets.limit_in_force(self.repo, budgets.TOTAL_Y, today)
        if yl:
            ys, ye = budgets.year_bounds(today.year)
            sp = budgets.spent(idx, exps, ys, ye, bucket=Bucket.YEARLY)
            pace = budgets.yearly_pace(self.repo, today)
            lines.append(f"{b.pre(pace[2] if pace else '')}Yearly: {fmt(sp, 0)} of {fmt(yl, 0)} ({float(sp / yl * 100):.0f}%), year is {pace[1]*100:.0f}% elapsed" if pace else f"Yearly: {fmt(sp, 0)} of {fmt(yl, 0)}")
        return [Reply("\n".join(lines))]

    # ------------------------------------------------------------------ people and debts
    def cmd_owed(self, args: str) -> list[Reply]:
        b, today = self.badge(), self.today()
        if args.strip():
            p = find_person(self.repo, args.strip())
            if not p:
                return [Reply(f"I don't know {args.strip().title()}.")]
            recs = splits.open_receivables(self.repo, p.id)
            if not recs:
                return [Reply(f"{p.name} owes you nothing.")]
            lines = [f"{p.name} owes {fmt(splits.balance(self.repo, p.id))}:"]
            for r in recs:
                ex = self.repo.get(Expense, r.expense_id)
                d = (today - r.created).days
                lines.append(f"{b.pre(owed_light(d))}{r.created:%-d %b} {ex.description if ex else ''}: {fmt(r.outstanding)} ({d} days)")
            return [Reply("\n".join(lines), [[Button("Settle", f"x:settlehelp:{p.id}"), Button("Write off", f"x:writeoff:{p.id}")]])]
        bal = splits.balances(self.repo)
        if not bal:
            return [Reply("Nobody owes you anything.")]
        parts, total = [], ZERO
        for pid, v in sorted(bal.items(), key=lambda kv: -kv[1]):
            d = splits.oldest_open_days(self.repo, pid, today)
            parts.append(f"{b.pre(owed_light(d)) if v > 0 else ''}{self.person_name(pid)} {fmt(v)} ({d} days)" if v > 0 else f"{self.person_name(pid)} {fmt(v)} (you owe them)")
            total += max(v, ZERO)
        return [Reply("\n".join(parts) + f"\nTotal owed to you: {fmt(total)}")]

    def cmd_settle(self, args: str, confirm: bool = False) -> list[Reply]:
        toks = args.split()
        if len(toks) < 2:
            return [Reply("Usage: /settle bob 40 paynow")]
        person = find_person(self.repo, toks[0])
        if not person:
            return [Reply(f"I don't know {toks[0].title()}. Add them with /people add.")]
        amount = _amt(toks[1])
        acct = find_account(self.repo, " ".join(toks[2:])) if len(toks) > 2 else None
        if acct is None:
            acct = next((a for a in self.repo.all(Account) if a.name.lower() == "paynow"), None) or next(iter(self.repo.all(Account)), None)
        try:
            st = splits.settle(self.repo, self.now(), person.id, amount, acct.id, self.today(), confirm_credit=confirm)
        except splits.NeedsCreditConfirmation as e:
            p = self.pend("confirm", {"do": "settle_credit", "args": {"args": args}})
            if e.owed == 0:
                return [Reply(f"⚠️ {person.name} owes you nothing. Record {fmt(amount)} as a credit you owe them?", self.buttons(p, [("Yes", "ok", ""), ("Cancel", "cancel", "")]))]
            return [Reply(f"⚠️ {person.name} only owes {fmt(e.owed)}. Record {fmt(e.owed)} as repayment and {fmt(e.excess)} as a credit you owe them?", self.buttons(p, [("Yes", "ok", ""), ("Cancel", "cancel", "")]))]
        left = splits.balance(self.repo, person.id)
        applied_months = sorted({self.repo.get(Receivable, a.receivable_id).created for a in st.applied})
        late = [d for d in applied_months if (d.year, d.month) != (self.today().year, self.today().month)]
        tail = f" Applied to {late[0]:%B}, the month of the expense. This month's budget is unchanged." if late else ""
        text = f"✅ Recorded {fmt(amount)} from {person.name} into {acct.name}. " + (f"{person.name} still owes {fmt(left)}." if left > 0 else f"{person.name} owes nothing." if left == 0 else f"You now owe {person.name} {fmt(-left)}.") + tail
        return [Reply(text)]

    def writeoff(self, pid: str) -> list[Reply]:
        p = self.repo.get(Person, pid)
        owed = splits.balance(self.repo, pid)
        if owed <= 0:
            return [Reply(f"{p.name} owes you nothing.")]
        pe = self.pend("confirm", {"do": "writeoff", "args": {"pid": pid}})
        return [Reply(f"Write off {fmt(owed)} from {p.name} as personal spending?", self.buttons(pe, [("Confirm", "ok", ""), ("Cancel", "cancel", "")]))]

    def cmd_with(self, args: str) -> list[Reply]:
        today = self.today()
        if not args.strip():
            r = people_core.ranking(self.repo, start=date(today.year, 1, 1), end=date(today.year, 12, 31), limit=10)
            if not r:
                return [Reply("No outings logged yet. Add people with: dinner 45 cc with bob.")]
            return [Reply("This year: " + " | ".join(f"{i} {x.name} {fmt(x.spent, 0)}" for i, x in enumerate(r, 1)) + "\nSpent with = your own share of each entry; person totals overlap.")]
        p = find_person(self.repo, args.strip(), include_archived=True)
        if not p:
            return [Reply(f"I don't know {args.strip().title()}.")]
        ms, me = budgets.month_bounds(today.year, today.month)
        month = people_core.stats(self.repo, start=ms, end=me).get(p.id)
        year = people_core.stats(self.repo, start=date(today.year, 1, 1), end=date(today.year, 12, 31)).get(p.id)
        if not year:
            return [Reply(f"No outings with {p.name} yet.")]
        lines = [f"{p.name} ({p.relationship.value})"]
        if month:
            lines.append(f"This month: {fmt(month.spent)}, {month.outings} outings, {fmt(month.average)} each.")
        lines.append(f"This year: {fmt(year.spent)}, {year.outings} outings, {fmt(year.average)} each.")
        places = sorted(year.places.items(), key=lambda kv: -kv[1])[:3]
        if places:
            lines.append("Top places: " + ", ".join(k for k, _ in places) + ".")
        bal = splits.balance(self.repo, p.id)
        if bal > 0:
            d = splits.oldest_open_days(self.repo, p.id, today)
            lines.append(f"{self.badge().pre(owed_light(d))}Owes you {fmt(bal)} ({d} days).")
        return [Reply("\n".join(lines))]

    def cmd_people(self, args: str) -> list[Reply]:
        toks = args.split()
        if not toks:
            ppl = [p for p in self.repo.all(Person) if p.status == ACTIVE]
            return [Reply("People: " + (", ".join(f"{p.name} ({p.relationship.value})" for p in ppl) or "none yet") + "\nAdd: /people add Sam friend")]
        sub = toks[0].lower()
        try:
            if sub == "add" and len(toks) >= 2:
                rel = Relationship.FAMILY if toks[-1].lower() == "family" else Relationship.FRIEND
                name = " ".join(toks[1:-1] if toks[-1].lower() in ("friend", "family") else toks[1:])
                p = people_core.add_person(self.repo, self.now(), name, rel)
                return [Reply(f"✅ Added {p.name} as {p.relationship.value}.")]
            if sub == "rename" and len(toks) >= 3:
                p = find_person(self.repo, toks[1])
                people_core.rename_person(self.repo, self.now(), p.id, " ".join(toks[2:]))
                return [Reply("✅ Renamed.")]
            if sub == "merge":
                m = re.findall(r'"([^"]+)"|(\S+)', args)
                names = [a or b for a, b in m][1:]
                names = [n for n in names if n.lower() != "into"]
                if len(names) != 2:
                    return [Reply('Usage: /people merge "Bobby" into "Bob"')]
                drop, keep = find_person(self.repo, names[0]), find_person(self.repo, names[1])
                if not drop or not keep:
                    return [Reply(f"I don't know {names[0] if not drop else names[1]}.")]
                bal = splits.balance(self.repo, drop.id) + splits.balance(self.repo, keep.id)
                p = self.pend("confirm", {"do": "merge", "args": {"keep": keep.id, "drop": drop.id}})
                return [Reply(f"Merge {drop.name} into {keep.name}? Balances combine (total {fmt(bal)}).", self.buttons(p, [("Merge", "ok", ""), ("Cancel", "cancel", "")]))]
            if sub == "archive" and len(toks) >= 2:
                p = find_person(self.repo, toks[1])
                people_core.archive_person(self.repo, self.now(), p.id)
                return [Reply(f"✅ Archived {p.name}. History is kept.")]
        except (LedgerError, AttributeError) as e:
            return [Reply(str(e) if isinstance(e, LedgerError) else "I couldn't find that person.")]
        return [Reply("Usage: /people add Sam friend | rename Bob Robert | merge \"Bobby\" into \"Bob\" | archive Sam")]

    # ------------------------------------------------------------------ /refund
    def cmd_refund(self, args: str) -> list[Reply]:
        toks = args.split()
        if not toks:
            return [Reply("Usage: /refund 20 shopping cc   (or tap Refund under an entry)")]
        amount = _amt(toks[0])
        cat = acct = None
        for t in toks[1:]:
            cat = cat or find_category(self.repo, t)
            acct = acct or find_account(self.repo, t)
        if not acct:
            return [Reply("Which account did the refund go back to? Example: /refund 20 shopping cc")]
        try:
            r = create_refund(self.repo, self.now(), amount=amount, account_id=acct.id, on=self.today(), category_id=cat.id if cat else "")
        except LedgerError as e:
            return [Reply(str(e))]
        return [Reply(f"✅ Refunded {fmt(amount)} to {acct.name}. It lowers this month's net spend; it is not income.")]

    # ------------------------------------------------------------------ /bills
    def cmd_bills(self, args: str) -> list[Reply]:
        today = self.today()
        bs = self.repo.find(Bill, status=ACTIVE)
        if not bs:
            return [Reply("No bills yet. Add them in /setup bills.")]
        lines = []
        for b in sorted(bs, key=lambda b: bills_core.next_due(b, today)):
            d = bills_core.next_due(b, today)
            lines.append(f"{self.badge().pre(__import__('finbot.core.indicators', fromlist=['bill_light']).bill_light((d - today).days))}{b.name}: {fmt(b.amount)}{' (varies)' if b.variable else ''}, due {d:%a %-d %b} ({(d - today).days} days)")
        return [Reply("\n".join(lines))]

    def bill_callback(self, bid: str, action: str, arg: str = "") -> list[Reply]:
        b = self.repo.get(Bill, bid)
        if not b:
            return [Reply("I can't find that bill.")]
        if action == "paid":
            p = self.pend("bill_amount", {"bill_id": bid}, awaiting_text=True)
            last = b.last_amount or b.amount
            return [Reply(f"How much did you pay? Reply with the amount.", [[Button(fmt(last), f"x:billpay:{bid}:{last}")]])]
        if action == "snooze":
            bills_core.snooze(self.repo, bid, self.today())
            return [Reply("I'll remind you again tomorrow at 9:00.")]
        if action == "skip":
            bills_core.skip(self.repo, bid, self.today())
            return [Reply(f"Skipped this one. Next reminder: {bills_core.next_due(self.repo.get(Bill, bid), self.today()):%-d %b}.")]
        return [Reply("Unknown action.")]

    def bill_pay(self, bid: str, amount_text: str) -> list[Reply]:
        try:
            amount = _amt(amount_text)
            res = bills_core.mark_paid(self.repo, self.settings(), self.now(), bid, amount)
        except LedgerError as e:
            return [Reply(str(e))]
        b = self.repo.get(Bill, bid)
        if b.is_transfer:
            return [Reply(f"✅ Logged: {b.name} payment {fmt(amount)} (a transfer, not an expense).")]
        return [Reply(f"✅ Logged: {b.name} {fmt(amount)}."), *[Reply(l) for l in self._budget_lines(res.expense)]]
