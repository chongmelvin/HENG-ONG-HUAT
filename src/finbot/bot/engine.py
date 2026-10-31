"""The engine: transport-neutral brain of the bot. Telegram is only an adapter around this class.

    reply = engine.handle_text("chicken rice 5.50 paylah", update_id=123)

Everything the user can do goes through handle_text / handle_callback / handle_file, so every flow in
the test cases can be tested without Telegram.
"""
from __future__ import annotations

import difflib
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from ..core import bills as bills_core, budgets, claims as claims_core, items as items_core, people as people_core, splits, vouchers
from ..core.ids import new_id
from ..core.ledger import LedgerError, recompute_split
from ..core.pin import SENSITIVE, PinError
from ..domain.enums import ACTIVE, Persona
from ..domain.models import Account, Category, Expense, Pending, Processed, Settings
from ..domain.money import D, fmt
from ..help.registry import BY_NAME, COMMANDS, usage_text
from ..v2 import llm as llm_mod
from .base import Base
from .commands_v1 import CommandsV1
from .commands_v15 import CommandsV15
from .commands_v2 import CommandsV2
from .expense_flow import ExpenseFlow
from .setup_flow import SetupFlow
from .types import Button, Reply

SENSITIVE_CMDS = {"networth", "snapshot", "accounts", "insurance", "coverage", "invest", "export"}


class Engine(ExpenseFlow, CommandsV1, CommandsV15, CommandsV2, SetupFlow, Base):
    def __init__(self, repo, clock, *, guide_url: str = "", guide_pdf=None, **kw) -> None:
        Base.__init__(self, repo, clock, **kw)
        self.guide_url, self.guide_pdf = guide_url, guide_pdf

    # ================================================================== text
    def handle_text(self, text: str, *, update_id: Optional[int] = None) -> list[Reply]:
        if update_id is not None:                      # Telegram redelivers on timeouts: never process twice
            if self.repo.get(Processed, str(update_id)):
                return []
            self.repo.add(Processed(id=str(update_id), at=self.now()))
        text = text.strip()
        if not text:
            return []
        aw = self.awaiting()
        if aw and not text.startswith("/"):
            return self._await_text(aw, text)
        if text.startswith("/"):
            name, _, args = text[1:].partition(" ")
            name = name.split("@")[0].lower()
            return self.run_command(name, args.strip())
        m = re.match(r"^\+(\w+)\s+(\d+(?:\.\d+)?)\s*(?:exp(?:ires)?\s+(.+))?$", text, re.I)   # +CDC 100 exp 31 dec
        if m:
            return self.voucher_quick_add(m.group(1), m.group(2), m.group(3))
        out = self.setup_nudge_prefix()
        if self.llm and llm_mod.looks_like_question(text):
            return out + [Reply(self.llm.answer(text))]
        return out + self.log_text(text)

    def _await_text(self, p: Pending, text: str) -> list[Reply]:
        kind = p.kind
        if kind == "pin":
            return self.pin_text(p, text)
        if kind == "draft":
            return self.draft_text(p, text)
        if kind == "edit":
            return self.edit_text(p, text)
        if kind == "bill_amount":
            out = self.bill_pay(p.payload["bill_id"], text)
            if not (out and out[0].text.startswith("I need a number")):
                self.drop(p)                      # a bad amount keeps the question open
            return out
        if kind == "snapshot":
            return self.snapshot_text(p, text)
        if kind == "setup":
            return self.setup_text(p, text)
        if kind == "receipt_name":
            return self.item_name_text(p, text)
        if kind == "voucher_expiry":
            return self.voucher_expiry_text(p, text)
        if kind == "income_amount":
            self.drop(p)
            from ..domain.models import Bill
            try:
                return [self._income_from_template(self.repo.get(Bill, p.payload["bill_id"]), D(text))]
            except ValueError:
                self.pend("income_amount", p.payload, awaiting_text=True)
                return [Reply("I need a number, for example 3620.")]
        self.drop(p)
        return self.handle_text(text)

    # ================================================================== commands
    def run_command(self, name: str, args: str) -> list[Reply]:
        if name == "start":
            return self.cmd_setup("")
        if name in SENSITIVE_CMDS and not self.gate.is_unlocked(self.now()):
            return self.need_pin(name, args)
        fn = getattr(self, f"cmd_{name}", None)
        if fn is None:
            close = difflib.get_close_matches(name, list(BY_NAME), n=1, cutoff=0.6)
            return [Reply("I don't know that one." + (f" Did you mean /{close[0]}?" if close else " Try /help."))]
        try:
            return fn(args)
        except LedgerError as e:
            return [Reply(str(e))]

    # ---- PIN (plain wording always)
    def need_pin(self, cmd: str, args: str) -> list[Reply]:
        s = self.settings()
        if not s.pin_hash:
            return [Reply("You haven't set a PIN yet. Run /setup security first.")]
        if self.gate.is_locked(self.now()):
            return [Reply("Sensitive commands are locked for a few minutes after too many wrong PINs. Normal logging still works.")]
        self.pend("pin", {"cmd": cmd, "args": args}, awaiting_text=True)
        return [Reply("This needs your PIN. Send it now. I will delete your message right away.", sensitive=True)]

    def pin_text(self, p: Pending, pin: str) -> list[Reply]:
        ok, state = self.gate.try_pin(self.settings(), pin.strip(), self.now())
        if ok:
            self.drop(p)
            cmd, args = p.payload["cmd"], p.payload["args"]
            if cmd == "expense_action":
                eid, action, arg = (args.split("|") + ["", ""])[:3]
                body = self.expense_action(eid, action, arg)
            elif cmd == "undo":
                body = self.cmd_undo("")
            else:
                body = self.run_command(cmd, args)
            return [Reply("Unlocked for 15 minutes.", delete_user_message=True)] + body
        if state == "locked":
            self.drop(p)
            return [Reply("Wrong PIN. Sensitive commands are locked for 15 minutes. Normal logging still works.", delete_user_message=True)]
        return [Reply(f"Wrong PIN. {state} {'try' if state == '1' else 'tries'} left.", delete_user_message=True)]

    # ---- /help
    def cmd_help(self, args: str) -> list[Reply]:
        if args.strip():
            u = usage_text(args)
            return [Reply(u or f"I don't know a command called {args.strip()}. Send /help for the list.")]
        intro = self.msg.say("help_intro")
        body = (f"{intro}\nLog: just type, e.g. chicken rice 5.50 paylah\n/add guided entry   /undo   /search\n/budget   /owed   /settle   /refund   /with\n"
                "/report   /calendar   /review   /setup\nFull guide with examples of every flow (PDF):")
        btn = [[Button("Open guide (PDF)", f"url:{self.guide_url}")]] if self.guide_url else []
        files = []
        if not self.guide_url and self.guide_pdf:
            files = [("finance-bot-help-guide.pdf", self.guide_pdf())]
        return [Reply(body, btn, files=files)]

    # ---- /settings
    def cmd_settings(self, args: str) -> list[Reply]:
        toks = args.split()
        s = self.settings()
        if not toks:
            return [Reply("Settings: /settings persona | indicators | reports | category add|rename|archive | account add | place add",
                          [[Button("Personality", "x:set:persona"), Button("Indicators", "x:set:indicators"), Button("Report sections", "x:set:reports")]])]
        sub = toks[0].lower()
        if sub == "persona":
            return [Reply("Personality:", [[Button("Off", "x:persona:off"), Button("Light", "x:persona:light"), Button("Scold off", "x:persona:scold_off")]])]
        if sub == "indicators":
            return [Reply("Traffic lights:", [[Button("On", "x:indicators:on"), Button("Off", "x:indicators:off")]])]
        if sub == "reports":
            names = ["people", "subscriptions", "fees", "vouchers", "cards", "insurance", "projection"]
            return [Reply("Optional report sections (tap to hide or show):", [[Button(f"{n} {'(hidden)' if n in s.hidden_sections else '(shown)'}", f"x:section:{n}") for n in names[i:i + 2]] for i in range(0, len(names), 2)])]
        if sub == "category" and len(toks) >= 3:
            return self.settings_category(toks[1].lower(), toks[2:])
        if sub == "account" and len(toks) >= 3 and toks[1].lower() == "add":
            from ..domain.enums import AccountType
            typ = AccountType(toks[-1].lower()) if toks[-1].lower() in [t.value for t in AccountType] else AccountType.EWALLET
            name = " ".join(toks[2:-1] if toks[-1].lower() in [t.value for t in AccountType] else toks[2:])
            a = self.repo.add(Account(id=new_id("ac"), name=name, type=typ))
            self.audit("create", "accounts", a.id, name)
            return [Reply(f"✅ Added account {name} ({typ.value}).")]
        if sub == "place" and len(toks) >= 3 and toks[1].lower() == "add":
            s.places.append(" ".join(toks[2:]).title())
            self.save_settings(s)
            return [Reply("✅ Saved place.")]
        return [Reply("I didn't understand that. Try /settings.")]

    def settings_category(self, op: str, toks: list[str]) -> list[Reply]:
        from ..domain.enums import Bucket
        from ..core.lookup import find_category
        if op == "add":
            name = toks[0].title()
            bucket = Bucket.YEARLY if "yearly" in [t.lower() for t in toks] else Bucket.MONTHLY
            amt = next((D(t) for t in toks[1:] if re.match(r"^\d+(\.\d+)?$", t)), None)
            if find_category(self.repo, name):
                return [Reply(f"{name} already exists.")]
            c = self.repo.add(Category(id=new_id("ca"), name=name, default_bucket=bucket))
            if amt and bucket == Bucket.MONTHLY:
                budgets.set_limit(self.repo, self.now(), f"category:{c.id}", amt)
            self.audit("create", "categories", c.id, name)
            return [Reply(f"✅ Added {name}" + (f" with a {fmt(amt, 0)} monthly limit." if amt else "."))]
        c = find_category(self.repo, toks[0])
        if not c:
            return [Reply(f"I don't have a category called {toks[0]}.")]
        if op == "rename" and len(toks) >= 2:
            c.name = " ".join(toks[1:]).title()
            self.repo.update(c)
            self.audit("rename", "categories", c.id, c.name)
            return [Reply(f"✅ Renamed. History keeps the same category under its new name.")]
        if op == "archive":
            c.status = "archived"
            self.repo.update(c)
            self.audit("archive", "categories", c.id)
            return [Reply(f"✅ Archived {c.name}. It stays in past reports as \"{c.name} (archived)\".")]
        return [Reply("Usage: /settings category add Pets monthly 80 | rename Fun Entertainment | archive Gifts")]

    # ================================================================== callbacks
    def handle_callback(self, data: str) -> list[Reply]:
        parts = data.split(":")
        kind = parts[0]
        if kind == "p" and len(parts) >= 3:
            p = self.repo.get(Pending, parts[1])
            if p is None:
                return [Reply("That button has expired. Please send it again.")]
            return self.dispatch_pending(p, parts[2], ":".join(parts[3:]))
        if kind == "e" and len(parts) >= 3:
            return self.expense_action(parts[1], parts[2], ":".join(parts[3:]))
        if kind == "x":
            return self.misc_callback(parts[1:])
        return [Reply("Unknown button.")]

    def dispatch_pending(self, p: Pending, action: str, arg: str) -> list[Reply]:
        k = p.kind
        if k in ("draft", "trip_ended"):
            return self.draft_callback(p, action, arg) if k == "draft" else self.draft_callback_trip(p, action, arg)
        if k == "bigticket":
            return self.bigticket_callback(p, action, arg)
        if k == "confirm":
            return self.do_confirm(p, action, arg)
        if k == "income_acct":
            self.drop(p)
            d = p.payload
            from ..domain.money import ZERO
            return [self._save_income(D(d["amount"]), d["source"], arg, D(d["gross"]) if d["gross"] else None, D(d["deductions"]) if d["deductions"] else None)]
        if k == "setup":
            return self.setup_callback(p, action, arg)
        if k == "snapshot":
            return self.snapshot_callback(p, action, arg)
        if k == "review":
            return self.review_callback(p, action, arg)
        self.drop(p)
        return [Reply("Done.")]

    def draft_callback_trip(self, p, action, arg):
        from ..v2 import trips
        text = p.payload.get("text", "")
        self.drop(p)
        if arg == "no":
            trips.end_trip(self.repo, self.settings(), self.now())
        else:
            t = self.repo.get(trips.Trip, self.settings().active_trip_id)
            if t and t.end and t.end < self.today():
                t.end = None
                self.repo.update(t)
        return self.log_text(text)

    def do_confirm(self, p: Pending, action: str, arg: str) -> list[Reply]:
        self.drop(p)
        if action == "cancel":
            return [Reply("Cancelled. Nothing changed.")]
        do, a = p.payload["do"], p.payload["args"]
        if do == "income":
            amount = D(arg) if action == "alt" else D(a["amount"])
            return [self._save_income(amount, a["source"], a["account"] or self._default_account(), D(a["gross"]) if a.get("gross") not in (None, "None") else None,
                                      D(a["deductions"]) if a.get("deductions") not in (None, "None") else None)]
        if do == "writeoff":
            owed = splits.write_off(self.repo, self.now(), a["pid"])
            return [Reply(f"✅ Written off {fmt(owed)}. It stays in your spending as personal spending.")]
        if do == "merge":
            k = people_core.merge_people(self.repo, self.now(), a["keep"], a["drop"])
            return [Reply(f"✅ Merged. {k.name} now holds the combined history.")]
        if do == "settle_credit":
            return self.cmd_settle(a["args"], confirm=True)
        if do == "resplit":
            recompute_split(self.repo, self.now(), a["eid"], D(a["amount"]))
            return [Reply("✅ Updated and shares recalculated.")]
        if do == "newcat":
            r = self.settings_category("add", [a["name"], a["amount"]])
            return r
        if do == "snapshot_writeoff":
            return self.snapshot_finish(a, write_off=True)
        if do == "claim_excess":
            return self.claim_pay(a["claimant"], D(a["amount"]), a["account"], confirm=True)
        if do == "expire_voucher":
            lost = vouchers.mark_expired(self.repo, self.now(), a["vid"])
            return [Reply(f"Marked as expired unused: {fmt(lost)}. It is noted separately and not counted as spending.")]
        return [Reply("Done.")]

    def _default_account(self) -> str:
        a = next((x for x in self.repo.all(Account) if x.status == ACTIVE), None)
        return a.id if a else ""

    def misc_callback(self, parts: list[str]) -> list[Reply]:
        k = parts[0]
        if k == "noop":
            return [Reply("Okay.")]
        if k == "persona":
            s = self.settings()
            s.persona = Persona(parts[1])
            self.save_settings(s)
            return [Reply("Okay. Plain wording from now on." if s.persona == Persona.OFF else "✅ Personality updated.")]
        if k == "indicators":
            s = self.settings()
            s.indicators = parts[1] == "on"
            self.save_settings(s)
            return [Reply("✅ Traffic lights are on." if s.indicators else "Okay. Plain figures from now on, with no colours. The numbers stay.")]
        if k == "section":
            s = self.settings()
            if parts[1] in s.hidden_sections:
                s.hidden_sections.remove(parts[1])
            else:
                s.hidden_sections.append(parts[1])
            self.save_settings(s)
            return [Reply(f"✅ {parts[1].title()} is now {'hidden from' if parts[1] in s.hidden_sections else 'shown in'} future reports.")]
        if k == "set":
            return self.cmd_settings(parts[1])
        if k == "writeoff":
            return self.writeoff(parts[1])
        if k == "settlehelp":
            return [Reply(f"Send: /settle {self.person_name(parts[1]).lower()} <amount> <account>")]
        if k in ("billpaid", "billsnooze", "billskip"):
            return self.bill_callback(parts[1], k[4:])
        if k == "billpay":
            return self.bill_pay(parts[1], parts[2])
        if k in ("voucher",):
            return self.voucher_callback(parts[1], parts[2], parts[3] if len(parts) > 3 else "")
        if k == "claim":
            return self.claim_callback(parts[1], parts[2])
        if k == "review":
            return self.review_step(int(parts[1]))
        if k in ("incconfirm", "incskip", "incdiff"):
            return self.income_template(parts[1], k)
        if k == "itemfile":
            it = self.repo.get(items_core.Item, parts[1])
            return [Reply(f"{it.name}: here is the file.", file_ids=[it.file_id])] if it and it.file_id else [Reply("I don't have a file saved for that item.")]
        if k == "retrypdf":
            y, m = parts[1].split("-")
            return self.monthly_report(int(y), int(m))
        if k in ("tripend", "trippause"):
            return self.cmd_trip("end" if k == "tripend" else "pause")
        return [Reply("Unknown button.")]

    def income_template(self, bill_id: str, action: str) -> list[Reply]:
        from ..domain.models import Bill
        b = self.repo.get(Bill, bill_id)
        if action == "incskip":
            b.last_paid = bills_core.next_due(b, self.today())
            self.repo.update(b)
            return [Reply("Skipped. Nothing recorded.")]
        if action == "incdiff":
            self.pend("income_amount", {"bill_id": bill_id}, awaiting_text=True)
            return [Reply("How much did you receive?")]
        return [self._income_from_template(b, b.amount)]

    def _income_from_template(self, b, amount) -> Reply:
        from ..core.ledger import create_income as ci
        inc = ci(self.repo, self.now(), amount=amount, source=b.name.replace(" (income)", ""), account_id=b.account_id, on=self.today(), recurring=True)
        b.last_paid = bills_core.next_due(b, self.today())
        self.repo.update(b)
        return Reply(f"✅ Saved income: {fmt(amount)}, {inc.source}, into {self.acct_name(b.account_id)}, today.")

    def run_jobs(self) -> list[Reply]:
        from .jobs import run_daily
        return run_daily(self)
