from reportlab.platypus import SimpleDocTemplate, Spacer, PageBreak, KeepTogether, Paragraph, Table, TableStyle
import io
from datetime import date

from ..reports.pdf_common import *  # noqa: F401,F403
from ..reports.pdf_common import (CW, MARGIN, A4, F_BOLD, F_REG, GREEN, AMBER, RED, TEAL, base, cell, cellb, colors, h1, h2, make_footer, mm, note, small, table, title_block, ParagraphStyle)
from .registry import COMMANDS

VERSION = "Guide for build v2"

G = '<font color="#2E7D32">&#9679;</font>'
Y = '<font color="#F2A900">&#9679;</font>'
R = '<font color="#C62828">&#9679;</font>'


def fmt(t):
    t = t.replace(":g:", G).replace(":y:", Y).replace(":r:", R)
    t = t.replace(":ok:", '<font color="#2E7D32">&#10004;</font>').replace(":w:", '<font color="#F2A900">&#9888;</font>')
    t = t.replace("&", "&amp;").replace("&amp;#", "&#").replace("&amp;amp;", "&amp;")
    t = t.replace("<", "&lt;").replace(">", "&gt;")
    # restore markup we inserted
    for a, b in [("&lt;font color=", "<font color="), ("&lt;/font&gt;", "</font>")]:
        t = t.replace(a, b)
    t = t.replace('"&gt;&#9679;', '">&#9679;').replace('"&gt;&#10004;', '">&#10004;').replace('"&gt;&#9888;', '">&#9888;')
    import re
    t = re.sub(r"\[([^\]\n]{1,28})\]", r'<font color="#0F4C5C"><b>[\1]</b></font>', t)
    return t.replace("\n", "<br/>")


chat_you = ParagraphStyle("cy", parent=base, fontSize=8, leading=10.6)
chat_bot = ParagraphStyle("cb", parent=base, fontSize=8, leading=10.6)
tag_style = ParagraphStyle("tg", parent=base, fontSize=7.5, leading=9, textColor=colors.white, fontName=F_BOLD)
BADGE = {"Happy": GREEN, "Unhappy": RED, "Edge": AMBER, "Tip": TEAL}


def flow(fid, title, kind, lines, note_text=None):
    rows = []
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    head = Table([[Paragraph(f'<b>{fid}</b>  {title}', ParagraphStyle("fh", parent=base, fontName=F_BOLD, fontSize=8.6, textColor=TEAL)),
                   Paragraph(kind.upper(), tag_style)]], colWidths=[CW - 24 * mm, 20 * mm])
    head.setStyle(TableStyle([("BACKGROUND", (1, 0), (1, 0), BADGE[kind]), ("ALIGN", (1, 0), (1, 0), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (0, 0), 0)]))
    for i, (who, text) in enumerate(lines):
        if who == "You":
            rows.append([Paragraph("<b>You</b>", chat_you), Paragraph(fmt(text), chat_you)])
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#E8F1FA")))
        elif who == "Bot":
            rows.append([Paragraph("<b>Bot</b>", chat_bot), Paragraph(fmt(text), chat_bot)])
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F3F4F5")))
        else:
            rows.append([Paragraph("<i>note</i>", small), Paragraph(fmt(text), small)])
    t = Table(rows, colWidths=[11 * mm, CW - 11 * mm])
    t.setStyle(TableStyle(st + [("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.white)]))
    parts = [head, t]
    if note_text:
        parts.append(Paragraph(note_text, small))
    parts.append(Spacer(1, 8))
    return KeepTogether(parts)




def build_guide(today: date | None = None) -> bytes:
    """Build the help PDF. Holds no personal data: every example is sample data."""
    TODAY = (today or date.today()).strftime("%a %-d %b %Y")
    story = []
    # ---------------- cover
    story.append(title_block("Finance Bot Help Guide", f"{VERSION}  |  Generated {TODAY}  |  All amounts and names are sample data"))
    story.append(Spacer(1, 10))
    story.append(Paragraph("What this guide is", h2))
    story.append(Paragraph("Everything the bot can do, with a short chat for each flow, showing the happy path and what happens when something goes wrong. "
                           "It holds no personal data: every figure and name below is sample data. Send <b>/help</b> in your group to get the link again, "
                           "or <b>/help add</b> (any command name) for a quick reminder inside the chat.", base))
    story.append(Paragraph("How to read the examples", h2))
    rows = [["You", "A message you send in the private group."], ["Bot", "The bot's reply."], ["[Button]", "A button you tap."],
            ["Happy / Unhappy / Edge", "The normal path, what happens when input is wrong or something fails, and unusual-but-valid situations."],
            [G + " " + Y + " " + R, "Traffic lights. In Telegram they appear as green, yellow and red circles. The number or percentage is always written too."]]
    t = table([[Paragraph(fmt(a) if a in ("You", "Bot", "[Button]") else a, cellb), Paragraph(b, cell)] for a, b in rows], [42 * mm, CW - 42 * mm], header=False, zebra=True)
    story.append(t)
    story.append(Paragraph("Traffic light rules", h2))
    rows = [["Item", "Green", "Yellow", "Red"],
            ["Budget used (category, Monthly total)", "under 80%", "80% to 99%", "100% or more"],
            ["Yearly pace", "under pace", "within 10% of pace", "more than 10% ahead"],
            ["Savings rate (monthly report)", "30% or more", "15% to 29%", "under 15%"],
            ["Bill reminder", "paid", "due in 1 to 3 days", "due today or overdue"],
            ["Money owed to you (days outstanding)", "under 7", "7 to 14", "over 14"],
            ["Voucher, rewards or warranty expiry", "over 60 days", "31 to 60 days", "30 days or less"],
            ["Reconciliation", "balanced", "none", "gap"]]
    story.append(table([[Paragraph(c, cell) for c in r] for r in rows], [62 * mm, 36 * mm, 40 * mm, CW - 138 * mm], font=7.8))
    story.append(Paragraph("Thresholds can be changed in /settings indicators, which can also switch them off. Indicators never appear on security or error messages.", note))

    story.append(Paragraph("Quick start", h2))
    for i, t_ in enumerate([
        "Create a private group with only you and the bot. Make the bot an admin with permission to delete messages, and turn privacy mode off in BotFather.",
        "Send /start. The setup wizard asks for the basics, a PIN of 6 or more digits, your categories and budgets, accounts, income, bills and the people you spend with.",
        "Log your first entry by typing it, for example: chicken rice 5.50 paylah.",
        "Check /budget to see what is left in each category, and /owed to see what friends owe you.",
        "On the 1st of the month at 9:00 am you get your report. Tap Start monthly review to tidy up and confirm your balances.",
    ], start=1):
        story.append(Paragraph(f"<b>{i}.</b>&nbsp; {t_}", base))
        story.append(Spacer(1, 2))
    story.append(PageBreak())

    # ---------------- command reference
    story.append(Paragraph("1. Commands", h1))
    story.append(Paragraph("Live now", h2))
    live = [[u, w, e, r] for _, u, w, e, r in COMMANDS if r in ("v1", "v1.5")]
    story.append(table([["Command", "What it does", "Example", "From"]] + [[Paragraph(c, cellb), Paragraph(w, cell), Paragraph(e, cell), r] for c, w, e, r in live],
                       [46 * mm, 64 * mm, 54 * mm, 14 * mm], font=7.4))
    story.append(Paragraph("Coming later", h2))
    later = [[u, w, e, r] for _, u, w, e, r in COMMANDS if r == "v2"]
    story.append(table([["Command", "What it does", "Example", "From"]] + [[Paragraph(c, cellb), Paragraph(w, cell), Paragraph(e, cell), r] for c, w, e, r in later],
                       [46 * mm, 64 * mm, 54 * mm, 14 * mm], font=7.4))
    story.append(PageBreak())

    # ---------------- flows
    story.append(Paragraph("2. Example flows", h1))
    story.append(Paragraph("2.1 Logging an expense", h2))
    story.append(flow("L1", "Type it in plain words", "Happy", [
        ("You", "chicken rice 5.50 paylah"),
        ("Bot", ":ok: Saved: S$5.50, Food, PayLah, Alone, today.\n:g: Monthly budget left: S$1,240 of S$2,000. :g: Food left: S$310 of S$600.\n[Edit] [Delete] [Move to Yearly]")]))
    story.append(flow("L2", "With people and a place", "Happy", [
        ("You", "grab 12 cc with bob orchard"),
        ("Bot", ":ok: Saved: S$12.00, Transport, DBS Card, with Bob, Orchard, today.\n:g: Monthly budget left: S$1,228 of S$2,000. :y: Transport left: S$188 of S$200 (94% used).")]))
    story.append(flow("L3", "Guided entry", "Happy", [
        ("You", "/add"), ("Bot", "How much?"), ("You", "24.80"),
        ("Bot", "Category? [Food] [Groceries] [Transport] [Shopping] [More]"), ("You", "(taps Groceries)"),
        ("Bot", "Which account? [Cash] [PayLah] [PayNow] [DBS Card]"), ("You", "(taps PayNow)"),
        ("Bot", "With whom? [Alone] [Bob] [Alice] [Mum] [Someone new]"), ("You", "(taps Alone)"),
        ("Bot", ":ok: Saved: S$24.80, Groceries, PayNow, Alone, today.")]))
    story.append(flow("L4", "Count it as Yearly instead of Monthly", "Happy", [
        ("You", "laptop bag 89 cc"),
        ("Bot", "Shopping S$89.00 on DBS Card. Count this toward Monthly or Yearly? [Monthly] [Yearly]"), ("You", "(taps Yearly)"),
        ("Bot", ":ok: Saved. :g: Yearly bucket left: S$11,911 of S$12,000 (pace: on track).")]))
    story.append(flow("L5", "Edit and undo", "Happy", [
        ("You", "(taps Edit under an entry)"), ("Bot", "What do you want to change? [Amount] [Category] [Account] [With] [Location] [Date]"),
        ("You", "(taps Account, then PayLah)"), ("Bot", ":ok: Updated: S$12.00, Transport, PayLah."),
        ("You", "/undo"), ("Bot", ":ok: Removed your last entry: S$24.80, Groceries. [Restore]")]))
    story.append(flow("L6", "You forgot the amount", "Unhappy", [
        ("You", "chicken rice paylah"), ("Bot", "Sorry, cannot catch the amount. How much was it?"), ("You", "5.5"), ("Bot", ":ok: Saved: S$5.50, Food, PayLah.")]))
    story.append(flow("L7", "An account the bot does not know", "Unhappy", [
        ("You", "lunch 8 grabpay"),
        ("Bot", "I don't know an account called \"grabpay\". [Cash] [PayLah] [PayNow] [DBS Card] [Add GrabPay]")]))
    story.append(flow("L8", "A new word, then remembered", "Unhappy", [
        ("You", "bubble tea 6.20 paylah"), ("Bot", "Which category is \"bubble tea\"? [Food] [Groceries] [Transport] [Shopping] [More]"),
        ("You", "(taps Food)"), ("Bot", ":ok: Saved. I'll file \"bubble tea\" under Food from now on.")]))
    story.append(flow("L9", "Two amounts, a bad amount, a possible duplicate", "Unhappy", [
        ("You", "dinner 45 55 cc"), ("Bot", "I see two amounts (45 and 55). Which one is the total? [S$45] [S$55] [Cancel]"),
        ("You", "lunch -5 cash"), ("Bot", "The amount must be more than 0. Try again, for example: lunch 5 cash"),
        ("You", "chicken rice 5.50 paylah  (90 seconds after the same entry)"),
        ("Bot", ":w: This looks the same as an entry from 90 seconds ago. Save anyway? [Save] [Skip]")]))
    story.append(flow("L10", "A large amount and a failed save", "Edge", [
        ("You", "laptop 25000 cc"), ("Bot", ":w: That is above S$5,000. Please confirm: S$25,000.00 on DBS Card. [Confirm] [Fix amount]"),
        ("You", "lunch 8 cash  (the Sheet is briefly unavailable)"),
        ("Bot", "Got it. I couldn't save just now, so I've queued it and will retry.\n(minutes later) :ok: Saved: S$8.00, Food, Cash. It was queued.")]))

    story.append(Paragraph("2.2 Backdating", h2))
    story.append(flow("B1", "Yesterday, two days ago, a date", "Happy", [
        ("You", "y chicken rice 5.50 paylah"), ("Bot", ":ok: Saved, spent Sat 17 Oct (entered today)."),
        ("You", "-2d grab 12 cc"), ("Bot", ":ok: Saved, spent Fri 16 Oct."),
        ("You", "12 oct dinner 45 cc"), ("Bot", ":ok: Saved, spent Mon 12 Oct.")]))
    story.append(flow("B2", "Into a month that was already reported", "Edge", [
        ("You", "28 sep dinner 40 cc"),
        ("Bot", ":ok: Saved, spent Mon 28 Sep.\nThe September report was sent on 1 Oct. [Regenerate report] [Leave as is]")]))
    story.append(flow("B3", "A future or impossible date", "Unhappy", [
        ("You", "25 dec lunch 6 cash"), ("Bot", "25 Dec is in the future. Did you mean 25 Dec 2025? [25 Dec 2025] [Cancel]"),
        ("You", "31 feb lunch 6 cash"), ("Bot", "I couldn't read \"31 feb\" as a date. Try y, -2d, or 12 oct.")]))

    story.append(Paragraph("2.3 Income", h2))
    story.append(flow("I1", "Log income and confirm salary day", "Happy", [
        ("You", "/income 3500 salary dbs"), ("Bot", ":ok: Saved income: S$3,500.00, Salary, into DBS Bank."),
        ("Bot", "(25 Oct, 9:00) Salary S$3,500 is expected today into DBS Bank. [Confirm] [Different amount] [Skip]")]))
    story.append(flow("I2", "Payslip numbers do not add up", "Unhappy", [
        ("You", "/income 4500 salary dbs gross 5200 deductions 1000"),
        ("Bot", ":w: Gross minus deductions is S$4,200, but you entered S$4,500 received. Which is right? [Received S$4,500] [Received S$4,200] [Edit]")]))

    story.append(Paragraph("2.4 Budgets and traffic lights", h2))
    story.append(flow("U1", "Warning at 80%, then over the limit", "Happy", [
        ("You", "dinner 70 cc"),
        ("Bot", ":ok: Saved: S$70.00, Food, DBS Card.\n:g: Monthly budget left: S$1,170 of S$2,000. :y: Food left: S$120 of S$600 (80% used). Eh, slow down a bit."),
        ("You", "dinner 130 cc"),
        ("Bot", ":ok: Saved: S$130.00, Food, DBS Card.\n:r: Food: S$610 of S$600. Aiyo, over by S$10 leh. Stop whack so much food lah."),
        ("You", "coffee 5 cash"), ("Bot", ":ok: Saved. :r: Food: still over by S$15.")],
        "Exempt categories (default: Bills, Fixed, Insurance), claimable items and trip spend within its limit are never scolded."))
    story.append(flow("U2", "Change a limit", "Happy", [
        ("You", "/budget set food 650"), ("Bot", ":ok: Food monthly limit is now S$650. Total Monthly limit unchanged at S$2,000."),
        ("You", "/budget set shopping 1500"), ("Bot", ":w: Category limits now add up to S$2,950, above your total Monthly limit of S$2,000. Keep it? [Keep] [Cancel]"),
        ("You", "/budget set food abc"), ("Bot", "I need a number, for example: /budget set food 650")]))

    story.append(Paragraph("2.5 People, splits and money owed", h2))
    story.append(flow("S1", "Split a dinner equally", "Happy", [
        ("You", "dinner 120 cc split bob alice"),
        ("Bot", ":ok: Saved: Dinner S$120.00 on DBS Card, Food, today. Split equally (3): your share S$40.00.\n:g: Bob owes S$40.00. :g: Alice owes S$40.00.\n:g: Monthly budget left: S$1,120 of S$2,000 (full amount counts until repaid).")]))
    story.append(flow("S2", "Custom amounts and treats", "Happy", [
        ("You", "dinner 120 cc bob 30 alice 40"), ("Bot", ":ok: Saved: S$120.00. Bob owes S$30, Alice owes S$40, your share S$50."),
        ("You", "dinner 120 cc treat bob alice"), ("Bot", ":ok: Saved, tagged Treating. No one owes you.")]))
    story.append(flow("S3", "See what is owed and record a repayment", "Happy", [
        ("You", "/owed"), ("Bot", ":y: Bob S$70.00 (oldest 12 days)  :y: Alice S$40.00 (oldest 12 days)\nTotal owed to you: S$110.00"),
        ("You", "/settle bob 40 paynow"), ("Bot", ":ok: Recorded S$40.00 from Bob into PayNow (applied to the oldest debt). Bob still owes S$30.00.")]))
    story.append(flow("S4", "A name the bot does not know", "Unhappy", [
        ("You", "dinner 90 cc with sam"), ("Bot", "I don't know Sam. [Friend] [Family] [Cancel]"), ("You", "(taps Friend)"),
        ("Bot", ":ok: Added Sam as a friend. Saved: S$90.00, with Sam.")]))
    story.append(flow("S5", "Shares that do not add up, overpayment, rounding", "Unhappy", [
        ("You", "dinner 120 cc bob 80 alice 60"), ("Bot", "Bob S$80 + Alice S$60 is S$140, more than the S$120 total. Fix the amounts? [Edit] [Cancel]"),
        ("You", "/settle bob 100 paynow  (Bob owes S$40)"), ("Bot", ":w: Bob only owes S$40.00. Record S$40 as repayment and S$60 as a credit you owe him? [Yes] [Change amount]"),
        ("You", "taxi 100 cc split bob alice"), ("Bot", ":ok: Saved. Bob owes S$33.33, Alice owes S$33.33, your share S$33.34.")]))
    story.append(flow("S6", "Write off a debt, or a late repayment", "Edge", [
        ("You", "(taps Write off on Bob's S$30)"), ("Bot", "Write off S$30.00 as personal spending in October? [Confirm] [Cancel]"),
        ("You", "/settle bob 40 paynow  (in November, for an October dinner)"),
        ("Bot", ":ok: Recorded S$40.00 from Bob. Applied to October, the month of the dinner. November's budget is unchanged.")]))
    story.append(flow("P1", "Who you spend time with", "Happy", [
        ("You", "/with bob"),
        ("Bot", "Bob (friend)\nThis month: S$140.00, 3 outings, S$46.67 each.\nThis year: S$3,420.00, 38 outings, S$90.00 each.\nTop places: Orchard, Tampines. :y: Owes you S$30.00 (14 days)."),
        ("You", "/with"), ("Bot", "This year: 1 Bob S$3,420 | 2 Alice S$2,860 | 3 Mum S$2,310 | 4 Dad S$1,740 | 5 Chloe S$1,380")],
        "Spent with counts your own share of every entry the person is on (not what you paid for them), so person totals overlap and can add up to more than the group total."))
    story.append(flow("P2", "Rename, merge and unnamed groups", "Edge", [
        ("You", "/people merge \"Bobby\" into \"Bob\""), ("Bot", "Merge Bobby into Bob? Balances combine (Bob S$30 + Bobby S$20 = S$50). [Merge] [Cancel]"),
        ("You", "lunch 12 cash with friends"), ("Bot", ":ok: Saved under Other friends. Want to name them? [Name them] [Not now]")]))

    story.append(Paragraph("2.6 Bills and reminders", h2))
    story.append(flow("R1", "Reminder, then Paid", "Happy", [
        ("Bot", ":y: Reminder: DBS Card bill is due Thu 22 Oct (in 3 days). Last amount: S$842.10. [Paid] [Snooze] [Skip]"),
        ("You", "(taps Paid)"), ("Bot", "How much did you pay? [S$842.10] [Type amount]"), ("You", "912.40"),
        ("Bot", ":ok: Logged: DBS Card payment S$912.40 from DBS Bank (a transfer, not an expense).")]))
    story.append(flow("R2", "Bad amount or double tap", "Unhappy", [
        ("Bot", "How much did you pay?"), ("You", "around 40"), ("Bot", "I need a number, for example 40.00."),
        ("You", "(taps Paid twice)"), ("Bot", "Already logged. [Undo]")]))

    story.append(Paragraph("2.7 Reports, calendar and the monthly review", h2))
    story.append(flow("M1", "Monthly report message", "Happy", [
        ("Bot", ":ok: October report is here. Net worth S$85,853 :g: up S$1,643.\nIncome S$3,620 | Net spend S$3,052 | Saved S$568 (:y: savings rate 16%)\n:y: Monthly budget: S$1,812 of S$2,000 (91%). :y: Food S$590 of S$600.\n:g: Yearly bucket: S$6,970 of S$12,000 (under pace).\nMost time with: Bob (S$140, 3 outings).\nWaiting on you: :r: Alice S$40 (20 days), :y: Bob S$30 (14 days) | claim S$25\n[Open PDF] [Start monthly review]")]))
    story.append(flow("M2", "Calendar and one day", "Happy", [
        ("You", "/calendar"), ("Bot", "(image) October 2026. Heaviest day: 5 Oct S$661. No-entry days: 3, 4, 20. [Net spend] [Cash view]"),
        ("You", "/day 11"), ("Bot", "Sat 11 Oct: Dinner with Bob and Alice S$120 (net S$80), ...")]))
    story.append(flow("M3", "Report problems", "Unhappy", [
        ("Bot", "October report (summary). The PDF didn't generate. I'll retry in 5 minutes. [Retry now]"),
        ("Bot", "(5 minutes later) Here is the October PDF. (file)"),
        ("You", "/report 2026-13"), ("Bot", "I couldn't read that month. Try /report 2026-09.")]))
    story.append(flow("M4", "Monthly review", "Happy", [
        ("Bot", "Monthly review. About 5 minutes. [Start] [Later]"), ("You", "(taps Start)"),
        ("Bot", "1/11 Missing entries: no entries on 3, 4 and 20 Oct. [Add expense] [Nothing those days] [Skip]"),
        ("You", "(taps Nothing those days)"), ("Bot", "2/11 Report highlights ...  (steps with nothing to do are skipped)"),
        ("Bot", "11/11 Done. 2 entries added, Bob's S$30 written off, 1 gap of S$3.20 written off. Next review: 1 Dec.")]))

    story.append(Paragraph("2.8 Net worth and balances", h2))
    story.append(flow("N1", "Monthly snapshot reconciles", "Happy", [
        ("You", "/networth"), ("Bot", ":w: This needs your PIN. Send it now. I will delete your message right away."),
        ("You", "482913  (the bot deletes this message)"),
        ("Bot", ":ok: Unlocked for 15 minutes. Net worth S$85,853 :g: up S$1,643. Fixed S$31,813 | Variable S$54,040")]))
    story.append(flow("N2", "A gap, then fixed", "Unhappy", [
        ("Bot", ":r: Fixed assets: expected S$31,450, you entered S$31,412.60. Gap: -S$37.40.\nBiggest movers: Cash -S$30.00, PayLah -S$7.40.\n[Add an expense] [Add income] [Add a forgotten transfer] [Leave it]"),
        ("You", "(adds: coffee beans 30 cash, then: top up 7.40 paylah)"), ("Bot", ":ok: Gap is S$0.00. Reconciled."),
        ("Bot", "(if S$3.20 remained) Write it off as an unexplained adjustment? [Write off] [Keep looking]")]))
    story.append(flow("N3", "Moving money is not spending", "Edge", [
        ("You", "/transfer 200 dbs cash"), ("Bot", ":ok: Transferred S$200 from DBS Bank to Cash. Fixed assets unchanged. Cash balance S$440.")]))

    story.append(Paragraph("2.9 Cards, insurance, claims and refunds", h2))
    story.append(flow("C1", "Card summary and a statement mismatch", "Happy", [
        ("You", "/cards"), ("Bot", "DBS Card (cycle 15 Oct to 14 Nov): spent S$612.30. Statement 15 Nov, due 22 Nov. Utilisation 18% of S$5,000."),
        ("You", "/cards statement dbs 1042.10"), ("Bot", ":w: You logged S$842.10 for this cycle. Statement says S$1,042.10. Missing S$200.00. [Add an expense] [Add as unexplained] [Ignore]")]))
    story.append(flow("C2", "Insurance summary and coverage", "Happy", [
        ("You", "/insurance"), ("Bot", ":w: This needs your PIN."), ("You", "482913  (deleted)"),
        ("Bot", ":ok: Annual premiums S$3,480 (S$290 a month). Next due: :y: Prudential Life S$900 on 12 Nov (in 3 days)."),
        ("You", "/coverage prudential"), ("Bot", "Prudential Life: sum assured S$250,000, critical illness rider S$100,000 (from your notes).")]))
    story.append(flow("X1", "A claim from start to finish", "Happy", [
        ("You", "taxi 25 cc #claim acme"), ("Bot", ":ok: Saved. Claim: Acme, Unclaimed."),
        ("You", "/claim paid acme 25"), ("Bot", ":ok: Reimbursement S$25.00 recorded into DBS Bank, linked to the taxi. October net spend down S$25.")]))
    story.append(flow("X2", "Claim problems", "Unhappy", [
        ("You", "/claim paid acme 40  (claim was S$25)"), ("Bot", ":w: The open claim is only S$25.00. Record S$25 and treat S$15 as other money? [Yes] [Change amount]"),
        ("You", "(taps Rejected on a claim)"), ("Bot", "Treat the S$25.00 as your own spending in October? [Confirm] [Cancel]")]))
    story.append(flow("X3", "Refund and delete", "Edge", [
        ("You", "(taps Refund on Shirt S$60, then Full)"), ("Bot", ":ok: Refunded S$60.00 to DBS Card, applied to October."),
        ("You", "(deletes a dinner Bob already part-repaid)"),
        ("Bot", ":w: This dinner has a receivable from Bob and a S$40.00 repayment. Deleting it removes the receivable and keeps S$40.00 as a credit you owe Bob. [Delete] [Cancel]")]))

    story.append(Paragraph("2.10 Vouchers, big purchases and receipts", h2))
    story.append(flow("V1", "Add a voucher and spend part of it", "Happy", [
        ("You", "+CDC 100 exp 31 dec"), ("Bot", ":ok: Added CDC voucher: S$100.00, expires 31 Dec 2026."),
        ("You", "lunch 12 voucher cdc 8 paynow 4"), ("Bot", ":ok: Saved. Paid: CDC voucher S$8.00 + PayNow S$4.00. CDC remaining S$92.00."),
        ("Bot", ":y: CDC voucher: S$92.00 left, expires 31 Dec (45 days). [Used] [Snooze] [Extended]")]))
    story.append(flow("V2", "More than the voucher holds, or expired", "Unhappy", [
        ("You", "groceries 30 voucher cdc  (S$8 left)"), ("Bot", ":w: CDC has only S$8.00 left. Use S$8 and pay S$22 with another account? [Cash] [PayLah] [PayNow] [DBS Card]"),
        ("Bot", ":r: CDC voucher S$8.00 expired on 31 Dec. Mark it as expired unused? [Confirm] [It was extended]")]))
    story.append(flow("T1", "Track a big purchase with its receipt", "Happy", [
        ("You", "standing desk 399 cc"), ("Bot", ":ok: Saved. Track as a big-ticket item? [Yes] [Skip]"), ("You", "(taps Yes, then 2 yrs)"),
        ("Bot", "Send the receipt or warranty now (photo or PDF)."), ("You", "(sends photo)"),
        ("Bot", ":ok: Saved. Warranty ends 18 Oct 2028. Receipt link saved in the group."),
        ("You", "/item desk"), ("Bot", "Standing desk, S$399, warranty to 18 Oct 2028. [Send file]")]))
    story.append(flow("T2", "Cheap item, odd file", "Edge", [
        ("You", "headphones 59 cc #big"), ("Bot", ":ok: Saved. Tracking as big-ticket. Send the receipt? [Skip]"),
        ("You", "(sends a photo with no caption)"), ("Bot", "Which item is this receipt for? [Standing desk] [Headphones] [Not an item]")]))
    story.append(PageBreak())

    story.append(Paragraph("2.11 Setup, settings and security", h2))
    story.append(flow("Z1", "First-time setup, minimal path", "Happy", [
        ("You", "/start"),
        ("Bot", "Welcome. Step 1/11 Basics: timezone Asia/Singapore, currency SGD, report at 9:00 am on the 1st. [Confirm] [Change]"),
        ("You", "(taps Confirm)"), ("Bot", "Step 2/11 Security: choose a PIN of 6 or more digits. I'll delete your message."),
        ("You", "482913"), ("Bot", ":ok: PIN set. Step 3/11 Access check: group, admin rights, privacy mode and Sheet all OK."),
        ("Bot", "Step 4/11 Categories: Food, Groceries, Transport, Shopping, Bills, Fixed, Fun, Gifts, Travel, Insurance. [Keep these] [Edit]"),
        ("You", "(taps Keep these)"), ("Bot", "Step 5/11 Budgets: total Monthly limit? Per-category limits? Yearly budget?"),
        ("Bot", "... (accounts, income, bills, people, places) ..."),
        ("Bot", ":ok: Step 11/11 Finish: here is everything you set up. [Edit] [Done]. Log your first entry any time.")],
        "Defaults are pre-filled, so a minimal path takes about 3 minutes. Steps for later releases appear once those releases ship."))
    story.append(flow("Z2", "Bills and income", "Happy", [
        ("Bot", "Step 8 Income: name, amount, pay day, account?"), ("You", "Salary, 3620, 25th, DBS Bank"),
        ("Bot", ":ok: Salary S$3,620 on the 25th into DBS Bank. Bonus months? [None] [Add]"),
        ("Bot", "Step 9 Bills: name, due day, usual amount, fixed or variable, account, reminder days?"), ("You", "DBS Card bill, 22nd, around 800, variable, DBS Bank, 3 days"),
        ("Bot", ":ok: DBS Card bill due on the 22nd, variable amount, reminder 3 days before. [Edit] [Next]")]))
    story.append(flow("Z3", "Setup input problems", "Unhappy", [
        ("You", "123456  (as a PIN)"), ("Bot", "That PIN is too easy. Choose a different one of 6 or more digits."),
        ("You", "(bill due day) 32"), ("Bot", "A day must be 1 to 31 (31 means the last day of shorter months)."),
        ("You", "(card digits) 4111222233334444"), ("Bot", "I only need the last 4 digits, for example 4444."),
        ("You", "(category) food"), ("Bot", "Food already exists. [Edit it] [Pick another name]"),
        ("You", "(salary) -3620"), ("Bot", "The amount must be a positive number, for example 3620.")]))
    story.append(flow("Z4", "Leave and come back, or redo one part", "Edge", [
        ("You", "(stops at step 6, sends a message a day later)"), ("Bot", "Welcome back. Setup is 55% done. Resume at step 7 Credit cards? [Resume] [Later]"),
        ("You", "/setup bills"), ("Bot", "Your bills: DBS Card bill (22nd), Phone (23rd). [Add] [Edit] [Archive]")]))
    story.append(flow("Z5", "Setup check failures", "Unhappy", [
        ("Bot", ":w: Access check: privacy mode is on, so I can't read normal messages. Turn it off in BotFather, remove me and add me again."),
        ("Bot", ":w: Access check: this group is not a supergroup, so I can't create receipt links. I'll send files instead.")]))
    story.append(flow("Z6", "Personality, indicators and PIN problems", "Happy", [
        ("You", "/settings persona"), ("Bot", "Personality: [Off] [Light] [Scold off]"), ("You", "(taps Off)"), ("Bot", "Okay. Plain wording from now on."),
        ("You", "/networth"), ("Bot", "This needs your PIN."), ("You", "111111"), ("Bot", "Wrong PIN. 2 tries left."),
        ("You", "(two more wrong tries)"), ("Bot", "Wrong PIN. Sensitive commands are locked for 15 minutes. Normal logging still works.")]))
    story.append(flow("Z7", "Someone else in the group", "Unhappy", [
        ("You", "(a stranger sends: lunch 8 cash)"), ("Bot", "(no reply, nothing is logged)")],
        "The bot answers only your Telegram account in your own private group. Everyone else is ignored silently."))

    story.append(Paragraph("2.12 Help", h2))
    story.append(flow("H1", "Ask for help", "Happy", [
        ("You", "/help"),
        ("Bot", "Need help ah? Quick list:\nLog: just type, e.g. chicken rice 5.50 paylah\n/add guided entry   /undo   /edit   /search\n/budget   /owed   /settle   /refund   /with\n/report   /calendar   /review   /setup\nFull guide with examples of every flow (PDF):\n[Open guide (PDF)]"),
        ("You", "/help settle"), ("Bot", "/settle <person> <amount> <account>. Records money a friend paid back. Example: /settle bob 40 paynow")]))
    story.append(flow("H2", "Link problems or unknown command", "Unhappy", [
        ("Bot", "(the guide link can't be reached) I'll attach the guide here instead. (file)"),
        ("You", "/hepl"), ("Bot", "I don't know that one. Did you mean /help?")]))

    story.append(PageBreak())
    story.append(Paragraph("3. Coming later", h1))
    story.append(Paragraph("These flows arrive with release v2. They are shown so you know what is planned.", note))
    story.append(Spacer(1, 4))
    story.append(flow("F1", "A trip in foreign currency", "Happy", [
        ("You", "/trip start Japan 20 Nov to 27 Nov"), ("Bot", ":ok: Trip mode on: Japan, JPY. Trip spend counts under your Yearly bucket. Optional trip budget? [Set one] [Skip]"),
        ("You", "ramen 1200 yen sgd 11.40 cash"), ("Bot", ":ok: [Japan] Saved: 1,200 yen = S$11.40 (rate from your numbers), Food, Cash.\n:g: Yearly bucket left: S$11,300 of S$12,000.")]))
    story.append(flow("F2", "Trip problems", "Unhappy", [
        ("You", "ramen 1200 yen cash"), ("Bot", ":ok: Saved: 1,200 yen is about S$11.52 (today's rate). Add the exact SGD later with Edit."),
        ("You", "lunch 8 cash  (28 Nov, trip ended 27 Nov)"), ("Bot", "Your Japan trip ended 27 Nov. Is this a trip expense or back home? [Japan] [Back home, end trip]"),
        ("You", "ramen 1200 xyz cash"), ("Bot", "I don't know the currency \"xyz\". [JPY] [SGD] [Type a code]")]))
    story.append(flow("F3", "Investments", "Happy", [
        ("Bot", "(1 Dec snapshot) Variable assets (prices fetched): S$54,081, :g: up S$41."),
        ("Bot", ":w: Couldn't fetch Bitcoin. Using the 30 Nov price (S$8,200), marked stale. Reconciliation is unaffected.")]))
    story.append(flow("F4", "Best card for the next purchase", "Happy", [
        ("You", "/bestcard grab 20"), ("Bot", "1) DBS Altitude: about 4 mpd on online spend. Cap used S$620 of S$1,000. 2) UOB One: 1.2 mpd. (Rules last verified 12 Aug.)"),
        ("You", "/bestcard hair salon 80"), ("Bot", ":w: None of your cards has a rule for salons. Likely default: DBS Altitude at 1.2 mpd. [Add rule]")]))
    story.append(flow("F5", "Ask a question about your own data", "Happy", [
        ("You", "how much did I spend in Korea 3 years ago?"), ("Bot", "Trip \"Korea\" (Oct 2023): S$2,340. Filters: trip = Korea, 2023. By category: Hotel S$900, Food S$610, ..."),
        ("You", "log lunch 8 cash"), ("Bot", "I can only answer questions in this mode. To log, send: lunch 8 cash.")],
        "Question mode is read-only. It never writes or changes data."))
    story.append(PageBreak())

    # ---------------- glossary & troubleshooting
    story.append(Paragraph("4. Glossary", h1))
    gl = [
        ["Net spend", "What you paid, minus what friends have repaid and claims paid back. The full amount counts until repaid. Budgets, reports and the calendar use net spend."],
        ["Monthly bucket", "Everyday spending. Resets on the 1st with no rollover. Has per-category limits and a total."],
        ["Yearly bucket", "Lumpy or annual spending: travel, insurance, gifts, big purchases. One budget for the whole year."],
        ["Fixed assets", "Cash, bank accounts, e-wallets, money owed to you, less credit card balances. Used for reconciliation."],
        ["Variable assets", "Anything whose price changes by itself: stocks, ETFs, crypto. Prices are fetched automatically."],
        ["Reconciliation", "A monthly check that fixed assets match income, spending and transfers. Any gap is flagged. Only the gap left after review is written off."],
        ["Spent with", "Your own share of every entry a person is on, counted in full for each person present. Person totals overlap."],
        ["Outings", "The number of distinct days you spent with a person."],
        ["Receivable", "Money a friend owes you after you paid for them."],
        ["Savings buckets", "Virtual goals (house, car, retirement) that float across your combined assets."],
        ["Liquid runway", "Bank, cash and e-wallet balances divided by your average monthly net spend, in months."],
    ]
    story.append(table([[Paragraph(a, cellb), Paragraph(b, cell)] for a, b in gl], [36 * mm, CW - 36 * mm], header=False))
    story.append(Paragraph("5. Troubleshooting", h1))
    tr = [
        ["The bot ignores my messages", "Check you are in the allowed group and that privacy mode is off or the bot is an admin. Only your own account is answered."],
        ["It cannot read plain text, only commands", "Privacy mode is on. Turn it off in BotFather, then remove the bot from the group and add it again."],
        ["The PIN message stayed in the chat", "The bot needs admin rights with permission to delete messages. Without it, the bot refuses to take a PIN."],
        ["Receipt links do not work", "Message links only work in a supergroup. Otherwise the bot sends the file itself when you ask."],
        ["A save failed", "The bot queues it and retries. You are told once it is saved. Nothing is saved twice."],
        ["A number looks wrong in a report", "Net spend counts the full amount until repayment. Use /day and /search to see the entries behind a figure. Backdated entries offer to regenerate the report."],
        ["The report has a gap", "Run the monthly review. Add the missing expense, income or transfer. Only the gap left afterwards is written off."],
        ["I want plainer messages", "/settings persona Off for plain wording. /settings indicators switches the traffic lights off."],
    ]
    story.append(table([["Problem", "What to do"]] + [[Paragraph(a, cellb), Paragraph(b, cell)] for a, b in tr], [58 * mm, CW - 58 * mm]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"{VERSION}  |  Generated {TODAY}  |  Rebuilt on every deploy from the same flow definitions as the test cases.", note))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=14 * mm, bottomMargin=17 * mm, title="Finance Bot Help Guide", author="Finance Bot")
    fn = make_footer("Help guide")
    doc.build(story, onFirstPage=fn, onLaterPages=fn)
    return buf.getvalue()
