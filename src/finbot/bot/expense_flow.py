"""Logging an expense from free text, with the clarifying questions from the test cases (PRD 4.2)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from ..core import bills as bills_core, budgets, items as items_core, vouchers
from ..core.indicators import GREEN, RED, YELLOW
from ..core.ledger import ExpenseInput, LedgerError, active_expenses, create_expense, create_refund, delete_expense, last_expense, links_of, recompute_split
from ..core.lookup import find_account, find_category, find_person, norm
from ..core import people as people_core
from ..domain.enums import ACTIVE, AccountType, Bucket, Relationship
from ..domain.models import Account, Category, Expense, Payment, Person
from ..domain.money import ZERO, fmt
from ..parsing.expense import Parsed, parse_expense
from ..v2 import fx as fx_core, trips
from .types import Button, Reply


class ExpenseFlow:
    # ------------------------------------------------------------------ entry point
    def log_text(self, text: str) -> list[Reply]:
        s = self.settings()
        trip = trips.active_trip(self.repo, s)
        p = parse_expense(self.repo, s, text, self.today(), trip_currency=trip.currency if trip else "")
        if trip:
            state = trips.check_state(self.repo, trip, self.today())
            if state == "ended":
                d = self.pend("trip_ended", {"text": text})
                return [Reply(f"Your {trip.name} trip ended {trip.end:%-d %b}. Is this a trip expense or back home?",
                              self.buttons(d, [(trip.name, "trip", "yes"), ("Back home, end trip", "trip", "no")]))]
        draft = self.draft_from_parsed(p, trip)
        return self.advance(draft)

    # ------------------------------------------------------------------ drafts
    def draft_from_parsed(self, p: Parsed, trip) -> dict:
        return {
            "raw": p.raw, "amount": str(p.amount) if p.amount is not None else None,
            "ambiguous": [str(a) for a in p.ambiguous_amounts], "description": p.description,
            "category_id": p.category.id if p.category else "", "unknown_words": p.unknown_words,
            "account_id": p.account.id if p.account else "", "unknown_account": p.unknown_account or "",
            "payments": [[a.id, str(v)] for a, v in p.payments], "people": [x.id for x in p.people],
            "unknown_people": p.unknown_people, "person_suggestion": p.person_suggestion.id if p.person_suggestion else "",
            "unnamed": [r.value for r in p.unnamed], "location": p.location, "tags": p.tags,
            "date": p.spend_date.isoformat(), "date_error": p.date_error,
            "date_suggestion": p.date_suggestion.isoformat() if p.date_suggestion else "",
            "split_mode": p.split_mode, "split_values": {k: str(v) for k, v in p.split_values.items()},
            "claimable": p.claimable, "claimant": p.claimant, "big": p.big,
            "currency": p.currency, "foreign": str(p.foreign_amount) if p.foreign_amount is not None else "",
            "home": str(p.home_amount) if p.home_amount is not None else "",
            "trip_id": trip.id if trip else "", "bucket": "", "confirmed_large": False, "confirmed_dup": False, "asked_bucket": False,
        }

    def advance(self, d: dict) -> list[Reply]:
        """Work out the next question, or save when everything is known."""
        repo = self.repo
        pend = self.pend("draft", d)
        pid = pend.id

        def ask(text, rows_=None, awaiting=False, field_=None) -> list[Reply]:
            if awaiting:
                self.drop(pend)
                pend2 = self.pend("draft", {**d, "waiting": field_}, awaiting_text=True)
                return [Reply(text)]
            return [Reply(text, self.buttons(pend, *rows_) if rows_ else [])]

        if d["date_error"]:
            sug = d["date_suggestion"]
            if sug:
                sd = date.fromisoformat(sug)
                return ask(f"{d['date_error']} Did you mean {sd:%-d %b %Y}?", [[(f"{sd:%-d %b %Y}", "date", sug), ("Cancel", "cancel", "")]])
            return ask(d["date_error"], [[("Cancel", "cancel", "")]])
        if d["ambiguous"]:
            return ask("I see two amounts (" + " and ".join(d["ambiguous"]) + "). Which one is the total?",
                       [[(f"S${a}", "amount", a) for a in d["ambiguous"]] + [("Cancel", "cancel", "")]])
        if d["amount"] is None and not d["home"]:
            return ask("How much?" if d.get("guided") else self.msg.say("missing_amount"), awaiting=True, field_="amount")
        if d["unknown_people"]:
            name = d["unknown_people"][0]
            hint = f" Did you mean {self.person_name(d['person_suggestion'])}?" if d["person_suggestion"] else ""
            rowsx = [[("Friend", "newperson", f"friend|{name}"), ("Family", "newperson", f"family|{name}"), ("Cancel", "cancel", "")]]
            if d["person_suggestion"]:
                rowsx.insert(0, [(self.person_name(d["person_suggestion"]), "useperson", d["person_suggestion"])])
            return ask(f"I don't know {name.title()}.{hint}", rowsx)
        if d["unknown_account"]:
            accts = [a for a in repo.all(Account) if a.status == ACTIVE and a.type != AccountType.VOUCHER]
            rowsx = [[(a.name, "account", a.id) for a in accts[i:i + 3]] for i in range(0, len(accts), 3)]
            rowsx.append([(f'Add "{d["unknown_account"].title()}"', "newaccount", d["unknown_account"])])
            return ask(f'I don\'t know an account called "{d["unknown_account"]}".', rowsx)
        if not d["category_id"]:
            cats = [c for c in repo.all(Category) if c.status == ACTIVE]
            rowsx = [[(c.name, "cat", c.id) for c in cats[i:i + 3]] for i in range(0, len(cats), 3)]
            word = d["description"] or "this"
            return ask(f'Which category is "{word}"?', rowsx)
        if not d["account_id"] and not d["payments"]:
            accts = [a for a in repo.all(Account) if a.status == ACTIVE and a.type != AccountType.VOUCHER]
            rowsx = [[(a.name, "account", a.id) for a in accts[i:i + 3]] for i in range(0, len(accts), 3)]
            return ask("Which account?", rowsx)
        if d.get("guided") and not d.get("people_done"):
            ppl = [p for p in repo.all(Person) if p.status == ACTIVE]
            chosen = ", ".join(self.person_name(x) for x in d["people"])
            rowsx = [[("Alone" if not d["people"] else "Done", "peopledone", "")]] + [[(p.name, "addperson", p.id) for p in ppl[i:i + 3] if p.id not in d["people"]] for i in range(0, len(ppl), 3)]
            rowsx = [r for r in rowsx if r] + [[("Someone new", "newguided", "")]]
            return ask("With whom?" + (f" So far: {chosen}." if chosen else ""), rowsx)
        if d.get("guided") and not d.get("place_done"):
            places = self.settings().places
            rowsx = [[(pl, "place", pl) for pl in places[i:i + 3]] for i in range(0, len(places), 3)] + [[("Skip", "place", "")]]
            return ask("Location?", rowsx)
        cat = repo.get(Category, d["category_id"])
        if not d["bucket"]:
            if d["trip_id"]:
                d["bucket"] = Bucket.YEARLY.value
            elif cat.ask_me and not d["asked_bucket"]:
                amt = d["home"] or d["amount"]
                return ask(f"{cat.name} S${amt}. Count this toward Monthly or Yearly?", [[("Monthly", "bucket", "monthly"), ("Yearly", "bucket", "yearly")]])
            else:
                d["bucket"] = cat.default_bucket.value
        total = Decimal(d["home"] or d["amount"])
        if total > self.settings().large_amount and not d["confirmed_large"]:
            return ask(f"⚠️ That is above {fmt(self.settings().large_amount, 0)}. Please confirm: {fmt(total)}.", [[("Confirm", "large", ""), ("Fix amount", "fix", ""), ("Cancel", "cancel", "")]])
        if not d["confirmed_dup"] and self._looks_duplicate(d, total):
            return ask("⚠️ This looks the same as an entry from a moment ago. Save anyway?", [[("Save", "dup", ""), ("Skip", "cancel", "")]])
        self.drop(pend)
        return self.save_draft(d)

    def _looks_duplicate(self, d: dict, total: Decimal) -> bool:
        window = timedelta(seconds=self.settings().dup_window_s)
        for e in active_expenses(self.repo):
            if e.created_at and self.now() - e.created_at <= window and e.amount == total \
                    and e.description.lower() == d["description"].lower() and e.spend_date.isoformat() == d["date"]:
                return True
        return False

    # ------------------------------------------------------------------ saving
    def save_draft(self, d: dict) -> list[Reply]:
        repo, s = self.repo, self.settings()
        total = Decimal(d["amount"]) if d["amount"] else Decimal(d["home"])
        currency, foreign, rate = "SGD", None, None
        if d["currency"]:
            trip = repo.get(trips.Trip, d["trip_id"]) if d["trip_id"] else None
            try:
                sgd, rate, src = fx_core.to_home(Decimal(d["foreign"]), currency=d["currency"], home_amount=Decimal(d["home"]) if d["home"] else None,
                                                 on=date.fromisoformat(d["date"]), manual_rate=trip.manual_rate if trip else None, provider=self.fx)
            except fx_core.FxError:
                pend = self.pend("draft", {**d, "waiting": "home"}, awaiting_text=True)
                return [Reply(f"I couldn't get a {d['currency']} rate right now. How much was that in SGD?")]
            currency, foreign, total = d["currency"], Decimal(d["foreign"]), sgd
        payments = [Payment(a, Decimal(v)) for a, v in d["payments"]] or [Payment(d["account_id"], total)]
        people_ids = list(d["people"])
        for rel in d["unnamed"]:
            people_ids.append(people_core.ensure_group_person(repo, self.now(), Relationship(rel)).id)
        inp = ExpenseInput(
            amount=total, category_id=d["category_id"], bucket=Bucket(d["bucket"]), payments=payments, spend_date=date.fromisoformat(d["date"]),
            description=d["description"], people=people_ids, location=d["location"], tags=d["tags"], split_mode=d["split_mode"],
            split_values={k: Decimal(v) for k, v in d["split_values"].items()}, claimable=d["claimable"], claimant=d["claimant"],
            trip_id=d["trip_id"], currency=currency, foreign_amount=foreign, fx_rate=rate)
        try:
            res = create_expense(repo, s, inp, self.now())
        except vouchers.InsufficientVoucher as e:
            pend = self.pend("draft", d)
            accts = [a for a in repo.all(Account) if a.status == ACTIVE and a.type != AccountType.VOUCHER]
            return [Reply(f"⚠️ {e.scheme} has only {fmt(e.left)} left. Use it and pay the rest with another account?",
                          self.buttons(pend, *[[(a.name, "voucherrest", f"{a.id}|{e.left}") for a in accts[i:i + 3]] for i in range(0, len(accts), 3)], [("Cancel", "cancel", "")]))]
        except LedgerError as e:
            return [Reply(str(e))]
        # remember a new alias if the user taught us a category word
        return [self.saved_reply(res, d)] + self._followups(res, d)

    def saved_reply(self, res, d: dict) -> Reply:
        e, s, b = res.expense, self.settings(), self.badge()
        cat = self.cat_name(e.category_id)
        accts = " + ".join(f"{self.acct_name(p.account_id)} {fmt(p.amount)}" if len(e.payments) > 1 else self.acct_name(p.account_id) for p in e.payments)
        who = ", ".join(self.person_name(p) for p in e.people) or "Alone"
        when = "today" if e.spend_date == e.entry_date else f"spent {e.spend_date:%a %-d %b} (entered today)"
        if e.currency != "SGD":
            amt = f"{e.foreign_amount:,.0f} {e.currency} = {fmt(e.amount)}"
        else:
            amt = fmt(e.amount)
        trip_tag = f"[{self.repo.get(trips.Trip, e.trip_id).name}] " if e.trip_id else ""
        lead = self.msg.say("saved")
        head = f"✅ {trip_tag}{lead} {amt}, {cat}, {accts}, {who}, {when}." if lead.endswith(".") else f"✅ {trip_tag}{lead} {amt}, {cat}, {accts}, {who}, {when}."
        lines = [head]
        if res.receivables:
            owed = " ".join(f"{b.pre(self._owed_light(0))}{self.person_name(r.person_id)} owes {fmt(r.amount)}." for r in res.receivables)
            lines.append(f"Split {'equally' if e.split_mode == 'equal' else e.split_mode} ({len(e.people) + 1}): your share {fmt(e.my_share)}. {owed}")
        elif e.split_mode == "treat":
            lines.append("Tagged Treating. No one owes you.")
        lines += self._budget_lines(e)
        buttons = [[Button("Edit", f"e:{e.id}:menu"), Button("Delete", f"e:{e.id}:del")]]
        if e.bucket == Bucket.MONTHLY:
            buttons[0].append(Button("Move to Yearly", f"e:{e.id}:yearly"))
        elif not e.trip_id:
            buttons[0].append(Button("Move to Monthly", f"e:{e.id}:monthly"))
        if res.receivables or e.claimable:
            pass
        return Reply("\n".join(lines), buttons)

    def _owed_light(self, days: int) -> str:
        from ..core.indicators import owed_light
        return owed_light(days)

    def _budget_lines(self, e: Expense) -> list[str]:
        s, b = self.settings(), self.badge()
        out = []
        ls = budgets.lines_for(self.repo, e)
        for l in ls:
            if l.label == "Yearly bucket":
                pace = budgets.yearly_pace(self.repo, e.spend_date)
                tail = f" (pace: {'on track' if pace and pace[2] == GREEN else 'a bit ahead' if pace and pace[2] == YELLOW else 'ahead of pace'})" if pace else ""
                out.append(f"{b.pre(l.light)}Yearly bucket left: {fmt(l.left, 0)} of {fmt(l.limit, 0)}{tail}.")
            else:
                word = "Monthly budget" if l.label == "Monthly budget" else l.label
                note = f" ({l.used_pct:.0f}% used)" if l.light == YELLOW else ""
                out.append(f"{b.pre(l.light)}{word} left: {fmt(l.left, 0)} of {fmt(l.limit, 0)}{note}." if l.left >= 0 else f"{b.pre(l.light)}{word}: {fmt(l.spent, 0)} of {fmt(l.limit, 0)}.")
        breach = budgets.check_breach(self.repo, s, e)
        if breach:
            if breach.kind == "still":
                out.append(self.msg.say("breach_still", label=breach.label, over=fmt(breach.over_by, 0)))
            else:
                ls_ = next((l for l in ls if l.label == breach.label), None)
                out.append(f"{b.pre(RED)}" + self.msg.say("breach_first" if breach.kind == "first" else "breach_firm", scold=True, label=breach.label,
                                                           over=fmt(breach.over_by, 0), spent=fmt(ls_.spent, 0) if ls_ else "", limit=fmt(ls_.limit, 0) if ls_ else "", n=breach.months_in_row))
        else:
            for l in ls:
                if l.light == YELLOW and 80 <= l.used_pct < 100:
                    out.append(self.msg.say("warn80", label=l.label, pct=f"{l.used_pct:.0f}"))
                    break
        return out

    def _followups(self, res, d: dict) -> list[Reply]:
        e, s = res.expense, self.settings()
        out = []
        if items_core.should_prompt(s, e, d["big"]):
            p = self.pend("bigticket", {"expense_id": e.id})
            out.append(Reply("Track this as a big-ticket item?", self.buttons(p, [("Yes", "bt", "yes"), ("Skip", "bt", "no")])))
        if res.claim:
            out.append(Reply(f"Claim: {res.claim.claimant}, status Unclaimed. Use /claims to submit."))
        return out

    # ------------------------------------------------------------------ callbacks for drafts
    def draft_callback(self, p, action: str, arg: str) -> list[Reply]:
        d = p.payload
        self.drop(p)
        if action == "cancel":
            return [Reply("Cancelled. Nothing saved.")]
        if action == "amount":
            d["amount"], d["ambiguous"] = arg, []
        elif action == "date":
            d["date"], d["date_error"], d["date_suggestion"] = arg, "", ""
        elif action == "account":
            d["account_id"], d["unknown_account"] = arg, ""
        elif action == "newaccount":
            from ..domain.models import Account as A
            from ..core.ids import new_id
            a = self.repo.add(A(id=new_id("ac"), name=arg.title(), type=AccountType.EWALLET, aliases=[arg.lower()]))
            self.audit("create", "accounts", a.id, a.name)
            d["account_id"], d["unknown_account"] = a.id, ""
        elif action == "cat":
            d["category_id"] = arg
            word = " ".join(d.get("unknown_words") or [])
            if word:
                c = self.repo.get(Category, arg)
                if word not in [norm(x) for x in c.aliases] and len(word.split()) <= 3:
                    c.aliases.append(word)
                    self.repo.update(c)
        elif action == "bucket":
            d["bucket"], d["asked_bucket"] = arg, True
        elif action == "newperson":
            rel, name = arg.split("|", 1)
            try:
                person = people_core.add_person(self.repo, self.now(), name, Relationship(rel))
            except LedgerError as e:
                return [Reply(str(e))]
            d["people"].append(person.id)
            d["unknown_people"] = [n for n in d["unknown_people"] if n.lower() != name.lower()]
        elif action == "useperson":
            d["people"].append(arg)
            d["unknown_people"] = d["unknown_people"][1:]
        elif action == "addperson":
            d["people"].append(arg)
        elif action == "peopledone":
            d["people_done"] = True
        elif action == "newguided":
            return [Reply("Add them with /people add <name> friend, then run /add again.")]
        elif action == "place":
            d["location"], d["place_done"] = arg, True
        elif action == "large":
            d["confirmed_large"] = True
        elif action == "dup":
            d["confirmed_dup"] = True
        elif action == "fix":
            d["amount"] = None
            d["home"] = ""
        elif action == "trip":
            trip = self.repo.get(trips.Trip, self.settings().active_trip_id)
            if arg == "no":
                trips.end_trip(self.repo, self.settings(), self.now())
            return self.log_text(d["text"]) if "text" in d else []
        elif action == "voucherrest":
            aid, left = arg.split("|")
            acct_v = next(a for a in self.repo.all(Account) if a.type == AccountType.VOUCHER)
            total = Decimal(d["amount"] or d["home"])
            d["payments"] = [[acct_v.id, left], [aid, str(total - Decimal(left))]]
        return self.advance(d)

    def draft_text(self, p, text: str) -> list[Reply]:
        """Free text answering a pending question (an amount or an SGD figure)."""
        d = p.payload
        self.drop(p)
        w = d.get("waiting")
        try:
            val = Decimal(text.strip().replace("S$", "").replace("$", "").replace(",", ""))
        except Exception:
            return [Reply("I need a number, for example 5.50.")] + self._reawait(d)
        if val <= 0:
            return [Reply("The amount must be more than 0. Try again.")] + self._reawait(d)
        if w == "amount":
            d["amount"] = str(val)
            if d["currency"]:
                d["foreign"] = str(val)
        elif w == "home":
            d["home"] = str(val)
        d.pop("waiting", None)
        return self.advance(d)

    def _reawait(self, d: dict) -> list[Reply]:
        self.pend("draft", d, awaiting_text=True)
        return []
