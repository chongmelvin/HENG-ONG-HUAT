"""First-time setup wizard (PRD 4.1, 5.6, 6.8).

Data-driven: each module is a list of steps (prompt, parser, applier). Modules for later releases
are skipped until enabled. Progress, Skip, Back and Resume are handled here once, not per module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, Optional

from ..core import bills as bills_core, budgets, insurance as ins_core, people as people_core, pin as pin_core, vouchers
from ..core.ids import new_id
from ..core.ledger import LedgerError
from ..core.lookup import find_account, find_category, norm
from ..domain.enums import ACTIVE, AccountType, AssetGroup, Bucket, Persona, Relationship, RewardType
from ..domain.models import Account, Card, Category, Pending, SetupState
from ..domain.money import D, fmt
from ..seed import DEFAULT_CATEGORIES, DEFAULT_TAGS, apply_default_categories
from .types import Button, Reply

MODULES = [
    # key, title, release
    ("basics", "Basics", "v1"), ("security", "Security", "v1"), ("access", "Access check", "v1"), ("categories", "Categories and tags", "v1"),
    ("budgets", "Budgets", "v1"), ("accounts", "Accounts", "v1"), ("income", "Income", "v1"), ("bills", "Bills and timings", "v1"),
    ("people", "People", "v1"), ("places", "Places", "v1"), ("finish", "Finish", "v1"),
    ("cards", "Credit cards", "v1.5"), ("insurance", "Insurance", "v1.5"), ("vouchers", "Vouchers", "v1.5"),
]
ENABLED_RELEASES = {"v1", "v1.5"}


class SetupError(ValueError):
    pass


def _day(text: str) -> int:
    t = re.sub(r"(st|nd|rd|th)$", "", text.strip().lower())
    if not t.isdigit() or not 1 <= int(t) <= 31:
        raise SetupError("A day must be 1 to 31. (31 means the last day of shorter months.)")
    return int(t)


def _amount(text: str) -> Decimal:
    try:
        v = D(text)
    except ValueError:
        raise SetupError("The amount must be a positive number, for example 3620.")
    if v <= 0:
        raise SetupError("The amount must be a positive number, for example 3620.")
    return v


class SetupFlow:
    def active_modules(self) -> list[tuple[str, str]]:
        return [(k, t) for k, t, rel in MODULES if rel in ENABLED_RELEASES]

    def _state(self) -> SetupState:
        st = self.repo.get(SetupState, "main")
        return st or self.repo.add(SetupState(started=self.now()))

    # ------------------------------------------------------------------ entry points
    def cmd_setup(self, args: str) -> list[Reply]:
        st = self._state()
        mods = self.active_modules()
        keys = [k for k, _ in mods]
        want = args.strip().lower()
        if want and want in keys:
            st.module, st.step, st.answers = want, 0, {}
            self.repo.update(st)
            return self._ask(st)
        if want == "pause":
            st.module = ""
            self.repo.update(st)
            return [Reply("Setup paused. Send /setup to continue.")]
        todo = [k for k in keys if k not in st.done and k not in st.skipped]
        if not todo and not want:
            return [Reply("Setup is complete. Rerun any part with /setup <module>: " + ", ".join(keys))]
        st.module = todo[0]
        st.step, st.answers = 0, {}
        self.repo.update(st)
        intro = [Reply("Welcome! Let's set things up. About 3 minutes on the minimal path. You can Skip or Back at any step.")] if not st.done else []
        return intro + self._ask(st)

    def setup_nudge_prefix(self) -> list[Reply]:
        """A gentle reminder when setup is unfinished (shown once, never blocks logging)."""
        s = self.settings()
        st = self.repo.get(SetupState, "main")
        if s.setup_complete or st is None or st.module == "" and not st.done:
            return []
        return []

    # ------------------------------------------------------------------ progress and prompting
    def _progress(self, st: SetupState) -> str:
        keys = [k for k, _ in self.active_modules()]
        return f"Step {keys.index(st.module) + 1}/{len(keys)}"

    def _nav(self, p: Pending, extra=None) -> list[list[Button]]:
        row = [Button("Skip", self.cb(p, "skip")), Button("Back", self.cb(p, "back"))]
        return [extra, row] if extra else [row]

    def _ask(self, st: SetupState) -> list[Reply]:
        fn = getattr(self, f"_setup_{st.module}")
        text, extra_buttons, awaiting = fn(st, None)
        p = self.pend("setup", {"module": st.module}, awaiting_text=awaiting)
        btns = []
        if extra_buttons:
            btns.append([Button(l, self.cb(p, "go", v)) for l, v in extra_buttons])
        btns.append([Button("Skip", self.cb(p, "skip")), Button("Back", self.cb(p, "back"))])
        return [Reply(f"{self._progress(st)} {dict(self.active_modules())[st.module]}: {text}", btns)]

    def setup_text(self, p: Pending, text: str) -> list[Reply]:
        st = self._state()
        self.drop(p)
        fn = getattr(self, f"_setup_{st.module}")
        try:
            out = fn(st, text)
        except (SetupError, LedgerError, pin_core.PinError) as e:
            return [Reply(str(e))] + self._ask(st)
        self.repo.update(st)
        return out if isinstance(out, list) else self._ask(st)

    def setup_callback(self, p: Pending, action: str, arg: str) -> list[Reply]:
        st = self._state()
        self.drop(p)
        keys = [k for k, _ in self.active_modules()]
        if action == "skip":
            st.skipped.append(st.module)
            return self._next_module(st, keys)
        if action == "back":
            i = max(keys.index(st.module) - 1, 0)
            st.module, st.step, st.answers = keys[i], 0, {}
            self.repo.update(st)
            return self._ask(st)
        if action == "go":
            fn = getattr(self, f"_setup_{st.module}")
            try:
                out = fn(st, f"@{arg}")
            except (SetupError, LedgerError) as e:
                return [Reply(str(e))] + self._ask(st)
            self.repo.update(st)
            return out if isinstance(out, list) else self._ask(st)
        return [Reply("Okay.")]

    def _finish_module(self, st: SetupState, recap: str) -> list[Reply]:
        keys = [k for k, _ in self.active_modules()]
        if st.module not in st.done:
            st.done.append(st.module)
        return [Reply(f"✅ {recap}")] + self._next_module(st, keys)

    def _next_module(self, st: SetupState, keys: list[str]) -> list[Reply]:
        remaining = [k for k in keys if k not in st.done and k not in st.skipped]
        if not remaining:
            st.module = ""
            s = self.settings()
            s.setup_complete = True
            self.save_settings(s)
            self.repo.update(st)
            skipped = ", ".join(dict(self.active_modules())[k] for k in st.skipped) or "nothing"
            return [Reply(f"✅ You're set. Skipped: {skipped}. Log your first entry any time, for example: chicken rice 5.50 paylah")]
        st.module, st.step, st.answers = remaining[0], 0, {}
        self.repo.update(st)
        return self._ask(st)

    # ------------------------------------------------------------------ modules: each returns (prompt, buttons, awaiting) when text is None
    def _setup_basics(self, st, text):
        s = self.settings()
        if text is None:
            return (f"timezone {s.timezone}, currency {s.currency}, reports at {s.report_hour}:00 on the 1st, personality {s.persona.value}, indicators {'on' if s.indicators else 'off'}.", [("Confirm", "ok")], False)
        return self._finish_module(st, "Basics saved.")

    def _setup_security(self, st, text):
        if text is None:
            return ("choose a PIN of 6 or more digits. I'll delete your message.", None, True)
        if st.step == 0:
            pin_core.validate_new_pin(text.strip())
            st.answers["pin"] = text.strip()
            st.step = 1
            return [Reply("Send it once more to confirm.", sensitive=True, delete_user_message=True)] if self._await_again("setup") else []
        if st.answers.get("pin") != text.strip():
            st.step, st.answers = 0, {}
            raise SetupError("Those didn't match. Start again with a new PIN.")
        s = self.settings()
        pin_core.set_pin(s, text.strip())
        self.save_settings(s)
        st.answers = {}
        out = self._finish_module(st, "PIN set.")
        out[0].delete_user_message = True
        return out

    def _await_again(self, kind: str) -> bool:
        self.pend(kind, {"module": "security"}, awaiting_text=True)
        return True

    def _setup_access(self, st, text):
        if text is None:
            return ("checking: allowed group, admin rights, privacy mode off, supergroup (for receipt links) and the Sheet connection. Tap Check when your group is ready.", [("Check", "check")], False)
        return self._finish_module(st, "Access check recorded. (The live check runs when the bot starts: see README.)")

    def _setup_categories(self, st, text):
        if text is None:
            cats = [c for c in self.repo.all(Category) if c.status == ACTIVE]
            if not cats:
                names = ", ".join(c[0] for c in DEFAULT_CATEGORIES)
                return (f"I suggest: {names}. Keep these, or send your own list separated by commas.", [("Keep these", "keep")], True)
            return ("your categories: " + ", ".join(c.name for c in cats) + ". Send a new name to add, or tap Done.", [("Done", "done")], True)
        if text in ("@keep", "@done"):
            if not [c for c in self.repo.all(Category) if c.status == ACTIVE]:
                apply_default_categories(self.repo, self.now(), with_limits=False)
            s = self.settings()
            s.tags = s.tags or list(DEFAULT_TAGS)
            self.save_settings(s)
            return self._finish_module(st, "Categories and tags saved.")
        added = []
        for name in [t.strip() for t in text.split(",") if t.strip()]:
            if find_category(self.repo, name):
                raise SetupError(f"{name.title()} already exists. Pick another name.")
            self.repo.add(Category(id=new_id("ca"), name=name.title()))
            added.append(name.title())
        st.step += 1
        return [Reply(f"Added {', '.join(added)}. Add more, or tap Done.", [[Button("Done", self.cb(self.pend("setup", {"module": "categories"}, awaiting_text=True), "go", "done"))]])]

    def _setup_budgets(self, st, text):
        cats = [c for c in self.repo.all(Category) if c.status == ACTIVE and c.default_bucket == Bucket.MONTHLY]
        if text is None:
            if st.step == 0:
                return ("what is your total Monthly limit? (e.g. 2000)", None, True)
            if st.step == 1:
                return ("per-category limits, one line each like: food 600, groceries 400. Or tap Skip for none.", None, True)
            return ("what is your Yearly budget? (e.g. 12000)", None, True)
        if st.step == 0:
            budgets.set_limit(self.repo, self.now(), budgets.TOTAL_M, _amount(text), date(self.today().year, 1, 1))
            st.step = 1
            return None
        if st.step == 1:
            for part in re.split(r"[,\n]", text):
                bits = part.split()
                if len(bits) >= 2:
                    c = find_category(self.repo, " ".join(bits[:-1]))
                    if not c:
                        raise SetupError(f"I don't have a category called {' '.join(bits[:-1])}.")
                    budgets.set_limit(self.repo, self.now(), f"category:{c.id}", _amount(bits[-1]), date(self.today().year, 1, 1))
            tot = budgets.limit_in_force(self.repo, budgets.TOTAL_M, self.today())
            ssum = budgets.category_limit_sum(self.repo, self.today())
            st.step = 2
            if tot and ssum > tot:
                return [Reply(f"⚠️ Category limits add up to {fmt(ssum, 0)}, above your total Monthly limit of {fmt(tot, 0)}. Kept as is.")] + self._ask(st)
            return None
        budgets.set_limit(self.repo, self.now(), budgets.TOTAL_Y, _amount(text), date(self.today().year, 1, 1))
        return self._finish_module(st, "Budgets saved.")

    def _setup_accounts(self, st, text):
        if text is None:
            have = [a.name for a in self.repo.all(Account)]
            return ("send accounts like: Cash cash, DBS Bank bank, PayLah ewallet, DBS Card credit_card. Types: " + ", ".join(t.value for t in AccountType if t != AccountType.VOUCHER)
                    + (f". Already have: {', '.join(have)}." if have else "") + " Tap Done when finished.", [("Done", "done")], True)
        if text == "@done":
            if not [a for a in self.repo.all(Account) if a.status == ACTIVE]:
                raise SetupError("Add at least one account first, for example: Cash cash")
            return self._finish_module(st, "Accounts saved. Opening balances come with your first /snapshot.")
        for part in [p.strip() for p in text.split(",") if p.strip()]:
            bits = part.split()
            typ = AccountType(bits[-1].lower()) if bits[-1].lower() in [t.value for t in AccountType] else AccountType.BANK
            name = " ".join(bits[:-1] if bits[-1].lower() in [t.value for t in AccountType] else bits)
            if find_account(self.repo, name):
                raise SetupError(f"{name} already exists.")
            self.repo.add(Account(id=new_id("ac"), name=name, type=typ, asset_group=AssetGroup.FIXED, aliases=[name.lower().replace(" ", "")]))
        st.step += 1
        return None

    def _setup_income(self, st, text):
        from ..domain.models import Bill
        if text is None:
            return ("send: name, amount, pay day, account. Example: Salary, 3620, 25th, DBS Bank. Tap Done when finished.", [("Done", "done")], True)
        if text == "@done":
            return self._finish_module(st, "Income saved.")
        bits = [b.strip() for b in text.split(",")]
        if len(bits) < 4:
            raise SetupError("Please send: name, amount, pay day, account. Example: Salary, 3620, 25th, DBS Bank")
        acct = find_account(self.repo, bits[3])
        if not acct:
            raise SetupError(f"I don't know the account {bits[3]}.")
        amount, day = _amount(bits[1]), _day(bits[2])
        st.answers.setdefault("income", []).append([bits[0], str(amount), day, acct.id])
        self.repo.add(Bill(id=new_id("bi"), name=f"{bits[0]} (income)", due_day=day, amount=amount, account_id=acct.id, kind="income", created=self.today(), lead_days=0))
        return [Reply(f"✅ {bits[0]} {fmt(amount)} on the {day}th into {acct.name}. Add another, or tap Done.")] + self._ask(st)

    def _setup_bills(self, st, text):
        from ..domain.models import Bill
        if text is None:
            return ("send: name, due day, usual amount, fixed or variable, paying account, reminder days. Example: DBS Card bill, 22nd, 800, variable, DBS Bank, 3. Tap Done when finished.", [("Done", "done")], True)
        if text == "@done":
            return self._finish_module(st, "Bills saved.")
        bits = [b.strip() for b in text.split(",")]
        if len(bits) < 4:
            raise SetupError("Please send: name, due day, usual amount, fixed or variable, account, reminder days.")
        day, amount = _day(bits[1]), _amount(bits[2])
        variable = bits[3].lower().startswith("var")
        acct = find_account(self.repo, bits[4]) if len(bits) > 4 else None
        lead = int(bits[5]) if len(bits) > 5 and bits[5].isdigit() else self.settings().default_lead_days
        cat = find_category(self.repo, "Bills")
        bills_core.create_bill(self.repo, self.now(), name=bits[0], due_day=day, amount=amount, variable=variable, account_id=acct.id if acct else "",
                               category_id=cat.id if cat else "", lead_days=lead)
        return [Reply(f"✅ {bits[0]} due on the {day}th, {'variable' if variable else 'fixed'} amount, reminder {lead} days before. Add another, or tap Done.")] + self._ask(st)

    def _setup_people(self, st, text):
        if text is None:
            return ("send names like: Bob friend, Alice friend, Mum family. Tap Done when finished.", [("Done", "done")], True)
        if text == "@done":
            return self._finish_module(st, "People saved.")
        for part in [p.strip() for p in text.split(",") if p.strip()]:
            bits = part.split()
            rel = Relationship.FAMILY if bits[-1].lower() == "family" else Relationship.FRIEND
            name = " ".join(bits[:-1] if bits[-1].lower() in ("friend", "family") else bits)
            people_core.add_person(self.repo, self.now(), name, rel)
        return [Reply("✅ Added. Add more, or tap Done.")] + self._ask(st)

    def _setup_places(self, st, text):
        if text is None:
            return ("send favourite places separated by commas, e.g. Orchard, Tampines. Tap Done when finished.", [("Done", "done")], True)
        if text == "@done":
            return self._finish_module(st, "Places saved.")
        s = self.settings()
        s.places += [p.strip().title() for p in text.split(",") if p.strip()]
        self.save_settings(s)
        return [Reply("✅ Saved. Add more, or tap Done.")] + self._ask(st)

    def _setup_finish(self, st, text):
        if text is None:
            return ("here is what you set up: " + f"{len(self.repo.all(Category))} categories, {len(self.repo.all(Account))} accounts, {len(self.repo.all(__import__('finbot.domain.models', fromlist=['Person']).Person))} people. Tap Done.", [("Done", "done")], False)
        return self._finish_module(st, "All set.")

    def _setup_cards(self, st, text):
        if text is None:
            return ("send: bank, card name, last 4 digits, statement day, due day, limit, annual fee, fee month, miles|cashback|points. Example: DBS, Altitude, 4444, 15, 22, 5000, 192, 3, miles. Tap Done when finished.", [("Done", "done")], True)
        if text == "@done":
            return self._finish_module(st, "Cards saved. Earn rules can wait until you want /bestcard.")
        if re.search(r"\d{12,}", text.replace(" ", "")):
            raise SetupError("I only need the last 4 digits, for example 4444. Please never send the full number.")
        bits = [b.strip() for b in text.split(",")]
        if len(bits) < 5:
            raise SetupError("Please send at least: bank, card name, last 4, statement day, due day.")
        if not re.fullmatch(r"\d{4}", bits[2]):
            raise SetupError("The last 4 digits must be exactly 4 numbers.")
        acct = self.repo.add(Account(id=new_id("ac"), name=f"{bits[0]} {bits[1]}", type=AccountType.CREDIT_CARD, aliases=["cc", "card"] if not [a for a in self.repo.all(Account) if a.type == AccountType.CREDIT_CARD] else []))
        self.repo.add(Card(id=new_id("cd"), account_id=acct.id, bank=bits[0], name=bits[1], last4=bits[2], statement_day=_day(bits[3]), due_day=_day(bits[4]),
                           limit=_amount(bits[5]) if len(bits) > 5 else Decimal("0"), annual_fee=D(bits[6]) if len(bits) > 6 else Decimal("0"),
                           fee_month=int(bits[7]) if len(bits) > 7 and bits[7].isdigit() else 0,
                           reward_type=RewardType(bits[8].lower()) if len(bits) > 8 and bits[8].lower() in [r.value for r in RewardType] else RewardType.MILES))
        return [Reply(f"✅ {bits[0]} {bits[1]} ending {bits[2]} saved. Add another, or tap Done.")] + self._ask(st)

    def _setup_insurance(self, st, text):
        if text is None:
            return ("send: insurer, product, type, premium, frequency (monthly|quarterly|half_yearly|yearly), next due date (YYYY-MM-DD), coverage notes. Example: Prudential, Life, Life, 900, half_yearly, 2026-11-12, S$250k sum assured. Tap Done when finished.", [("Done", "done")], True)
        if text == "@done":
            return self._finish_module(st, "Insurance saved.")
        bits = [b.strip() for b in text.split(",")]
        if len(bits) < 6:
            raise SetupError("Please send: insurer, product, type, premium, frequency, next due date.")
        try:
            due = date.fromisoformat(bits[5])
        except ValueError:
            raise SetupError("Use the date format YYYY-MM-DD, for example 2026-11-12.")
        ins, trunc = ins_core.add_policy(self.repo, self.now(), insurer=bits[0], product=bits[1], type=bits[2], premium=_amount(bits[3]), frequency=bits[4].lower(),
                                         next_due=due, coverage_notes=", ".join(bits[6:]))
        return [Reply(f"✅ {bits[0]} {bits[1]} saved. Add another, or tap Done.")] + self._ask(st)

    def _setup_vouchers(self, st, text):
        if text is None:
            return ("send each voucher like: CDC 100 exp 31 dec. Tap Done when finished.", [("Done", "done")], True)
        if text == "@done":
            return self._finish_module(st, "Vouchers saved.")
        m = re.match(r"^(\w+)\s+(\d+(?:\.\d+)?)\s+exp\s+(.+)$", text.strip(), re.I)
        if not m:
            raise SetupError("Please send it like: CDC 100 exp 31 dec")
        exp = self._parse_expiry(m.group(3))
        if exp is None:
            raise SetupError("I couldn't read that expiry date. Try 31 dec.")
        v = vouchers.add_voucher(self.repo, self.now(), m.group(1).upper(), D(m.group(2)), exp)
        return [Reply(f"✅ {v.scheme} {fmt(v.original)} expires {exp:%-d %b %Y}. Add another, or tap Done.")] + self._ask(st)
