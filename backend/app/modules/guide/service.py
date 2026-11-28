"""Start-up guide: the getting-started checklist, worked out from what is in MoneyMap, plus the
steps you tick or skip yourself. Shown on first sign-in until hidden or finished."""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..accounts.models import Account, AccountType
from ..auth.models import Setting
from ..bills.models import Bill
from ..budgets.models import Budget
from ..categories.models import Category
from ..emergency.models import EmergencyFund
from ..gmail.models import GmailMailbox
from ..investments.models import Investment
from ..loans.models import Loan
from ..rules.models import Rule
from ..savings.service import KEY as SAVINGS_KEY
from ..statements.models import StatementImport
from ..transactions.models import Transaction
from .schemas import GuideOut, GuideStep

KEY = "guide.state"  # {"hidden": bool, "checked": [step keys], "skipped": [step keys]}
SETUP_KEY = "setup.page"  # "pending" on a brand-new install until the setup page is finished or put off


def setup_pending(db: Session) -> bool:
    row = db.get(Setting, SETUP_KEY)
    return row is not None and row.value == "pending"


# (key, title, why, link, optional, can be ticked by hand)
STEPS: list[tuple[str, str, str, str, bool, bool]] = [
    (
        "essentials",
        "Check your Essential categories",
        "Tick Essential on the costs you can't avoid — rent, groceries, utilities, fuel, insurance, fees. The "
        "emergency fund and the needs / wants split in the savings plan are worked out from them.",
        "/categories",
        False,
        True,
    ),
    (
        "banks",
        "Add your bank accounts and cash",
        "Each with its balance on your start date and the last 4 digits of the account number, so statements "
        "find the right account by themselves.",
        "/accounts?new=asset",
        False,
        False,
    ),
    (
        "cards",
        "Add your credit cards",
        "Limit, statement day, due day, last 4 digits and what you owed on the start date. Paying the card "
        "bill is then a transfer, not spending.",
        "/credit-cards",
        True,
        False,
    ),
    (
        "loans",
        "Add your loans",
        "Easiest from the lender's statement or repayment schedule (Loans → Add from statement): amount, rate, "
        "EMI and EMIs paid are filled in. Set the bank the EMI is paid from.",
        "/loans",
        True,
        False,
    ),
    (
        "funds",
        "Import your mutual funds",
        "One CAS from CAMS or KFintech brings in all your funds. Choose per fund: with its transactions, or "
        "just today's units and value.",
        "/investments",
        True,
        False,
    ),
    (
        "investments",
        "Add other investments and property",
        "FDs, RDs, post office, PPF / EPF / NPS, gold, stocks, crypto, chits, insurance, money lent — and land "
        "or a house as Property, with what you paid and what it's worth today.",
        "/investments",
        True,
        False,
    ),
    (
        "statements",
        "Bring in your statements",
        "Connect Gmail in Settings to fetch bank, card, loan and CAS statements, or upload the PDFs. On review, "
        "card payments become transfers, EMIs link to loans and SIPs to funds.",
        "/statements",
        False,
        False,
    ),
    (
        "rules",
        "Let rules categorise for you",
        "Accept the suggested rules (Swiggy → Food Delivery …) or tick “Rule for next time” on review — the "
        "next statements fill themselves in.",
        "/rules",
        True,
        False,
    ),
    (
        "emergency",
        "Set up your emergency fund",
        "Months of essential spending kept aside. MoneyMap works out the target from your Essential categories "
        "and EMIs.",
        "/piggy-banks",
        True,
        False,
    ),
    (
        "bills",
        "Add your regular bills",
        "Rent, phone, internet, subscriptions, insurance premiums — so you see what's due and which are paid.",
        "/bills",
        True,
        False,
    ),
    (
        "plan",
        "Pick a savings rule and budgets",
        "Choose 50/30/20 or your own split on the Savings plan, then “Make budgets from this rule” for your wants.",
        "/savings-plan",
        True,
        False,
    ),
]


def _state(db: Session) -> dict:
    row = db.get(Setting, KEY)
    try:
        s = json.loads(row.value) if row else {}
    except ValueError:
        s = {}
    return {
        "hidden": bool(s.get("hidden")),
        "checked": list(s.get("checked", [])),
        "skipped": list(s.get("skipped", [])),
    }


def save_state(db: Session, s: dict) -> None:
    row = db.get(Setting, KEY) or Setting(key=KEY, value="")
    row.value = json.dumps(s)
    db.add(row)
    db.commit()


def _count(db: Session, q) -> int:
    return int(db.scalar(q) or 0)


def _progress(db: Session) -> dict[str, tuple[bool, str]]:
    """step key -> (done from your data, what's there)."""
    n_essential = _count(db, select(func.count(Category.id)).where(Category.essential.is_(True)))
    banks = _count(
        db,
        select(func.count(Account.id)).where(
            Account.type.in_([AccountType.asset.value, AccountType.cash.value]), Account.active.is_(True)
        ),
    )
    cards = _count(db, select(func.count(Account.id)).where(Account.type == AccountType.credit_card.value))
    loans = _count(db, select(func.count(Loan.account_id)))
    kinds = dict(db.execute(select(Investment.kind, func.count()).group_by(Investment.kind)).all())
    funds = int(kinds.get("mf", 0))
    others = sum(int(v) for k, v in kinds.items() if k != "mf")
    prop = int(kinds.get("property", 0))
    imported = _count(db, select(func.count(StatementImport.id)).where(StatementImport.status == "imported"))
    gmail = db.scalar(select(GmailMailbox.id).where(GmailMailbox.token_enc.is_not(None)).limit(1)) is not None
    txns = _count(db, select(func.count(Transaction.id)))
    rules = _count(db, select(func.count(Rule.id)))
    emergency = db.scalar(select(EmergencyFund.id).limit(1)) is not None
    bills = _count(db, select(func.count(Bill.id)))
    budgets = _count(db, select(func.count(Budget.id)))
    plan = db.get(Setting, SAVINGS_KEY) is not None

    def n(x: int, one: str, many: str) -> str:
        return f"{x} {one if x == 1 else many}"

    return {
        "essentials": (False, f"{n(n_essential, 'category', 'categories')} marked Essential"),
        "banks": (banks > 0, n(banks, "account", "accounts") + " added" if banks else "None yet"),
        "cards": (cards > 0, n(cards, "card", "cards") + " added" if cards else "None yet"),
        "loans": (loans > 0, n(loans, "loan", "loans") + " added" if loans else "None yet"),
        "funds": (funds > 0, n(funds, "fund", "funds") + " added" if funds else "None yet"),
        "investments": (
            others > 0,
            (n(others, "investment", "investments") + (f" (incl. {n(prop, 'property', 'properties')})" if prop else ""))
            if others
            else "None yet",
        ),
        "statements": (
            imported > 0,
            (n(imported, "statement", "statements") + " imported" if imported else "None imported yet")
            + (" · Gmail connected" if gmail else "")
            + (f" · {n(txns, 'transaction', 'transactions')}" if txns else ""),
        ),
        "rules": (rules > 0, n(rules, "rule", "rules") if rules else "None yet"),
        "emergency": (emergency, "Set up" if emergency else "Not set up yet"),
        "bills": (bills > 0, n(bills, "bill", "bills") if bills else "None yet"),
        "plan": (
            plan and budgets > 0,
            ("Rule chosen" if plan else "No rule chosen yet")
            + (f" · {n(budgets, 'budget', 'budgets')}" if budgets else ""),
        ),
    }


def guide(db: Session) -> GuideOut:
    s = _state(db)
    prog = _progress(db)
    steps = []
    for key, title, why, href, optional, manual in STEPS:
        auto, detail = prog[key]
        checked, skipped = key in s["checked"], key in s["skipped"]
        steps.append(
            GuideStep(
                key=key,
                title=title,
                why=why,
                href=href,
                optional=optional,
                manual=manual,
                detail=detail,
                done=auto or checked,
                skipped=skipped and not (auto or checked),
            )
        )
    finished = all(x.done or x.skipped for x in steps)
    return GuideOut(
        steps=steps,
        done=sum(1 for x in steps if x.done),
        total=len(steps),
        hidden=s["hidden"],
        finished=finished,
        show_first=not s["hidden"] and not finished,
        setup_page=setup_pending(db),
    )


def mark(db: Session, key: str, what: str) -> GuideOut:
    """what: check | skip | undo — for one step; hide | show — for the whole guide."""
    if what == "setup_done":
        row = db.get(Setting, SETUP_KEY)
        if row is not None:
            row.value = "done"
            db.commit()
        return guide(db)
    s = _state(db)
    if what == "hide":
        s["hidden"] = True
    elif what == "show":
        s["hidden"] = False
    else:
        s["checked"] = [k for k in s["checked"] if k != key]
        s["skipped"] = [k for k in s["skipped"] if k != key]
        if what == "check":
            s["checked"].append(key)
        elif what == "skip":
            s["skipped"].append(key)
    save_state(db, s)
    return guide(db)
