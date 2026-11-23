from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...db import get_db
from ..accounts.models import Account, AccountType
from ..auth.security import current_user
from ..transactions.models import Transaction
from .matching import score
from .models import Fund, Investment, PropertyCost, PropertyDeal, PropertyInstalment
from .schemas import (
    CloseIn,
    CostIn,
    DueOut,
    GoalIn,
    InvestmentDetail,
    InvestmentIn,
    InvestmentOut,
    InvestmentPatch,
    InvestmentSummary,
    Linkable,
    LinkIn,
    LinkOut,
    MoveIn,
    PropertyIn,
    RatesIO,
)
from .service import (
    KIND_LABEL,
    all_investments,
    bad,
    bank_account,
    detail_out,
    get_rates,
    investment_dues,
    move,
    rates_io,
    set_rates,
    summary,
)
from .values import is_schedule

router = APIRouter(prefix="/investments", tags=["investments"], dependencies=[Depends(current_user)])

SUBTYPES = {
    "post_office": {"nsc", "kvp", "scss", "mis", "td", "rd"},
    "retirement": {"ppf", "epf", "nps", "ssy"},
    "insurance": {"endowment", "money_back", "ulip", "term"},
    "gold": {"jewellery", "coin", "sgb", "digital", "silver"},
    "stocks": {"stock", "etf", "esop", "rsu", "startup"},
}
SUBTYPE_LABEL = {
    "nsc": "NSC",
    "kvp": "KVP",
    "scss": "SCSS",
    "mis": "Post Office MIS",
    "td": "Post Office TD",
    "rd": "Post Office RD",
    "ppf": "PPF",
    "epf": "EPF",
    "nps": "NPS",
    "ssy": "Sukanya Samriddhi",
    "endowment": "Endowment policy",
    "money_back": "Money-back policy",
    "ulip": "ULIP",
    "term": "Term insurance",
    "jewellery": "Gold jewellery",
    "coin": "Gold coins",
    "sgb": "SGB",
    "digital": "Digital gold",
    "silver": "Silver",
    "etf": "ETF",
    "esop": "ESOPs",
    "rsu": "RSUs",
    "startup": "Startup shares",
}
PURITIES = {"24k", "22k", "18k", "14k", "999", "925"}


def _get(db: Session, account_id: int) -> Investment:
    inv = db.scalar(select(Investment).where(Investment.account_id == account_id))
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investment not found")
    return inv


def _check(inv: Investment, amount: int | None, creating: bool) -> None:
    """What each kind needs before its value can be worked out."""
    k = inv.kind
    if k in SUBTYPES and inv.subtype not in SUBTYPES[k]:
        raise bad("Choose which type it is.")
    if inv.purity and inv.purity not in PURITIES:
        raise bad("Choose the purity.")
    if inv.maturity_date and inv.start_date and inv.maturity_date <= inv.start_date:
        raise bad("The maturity date must be after the start date.")
    if is_schedule(inv):
        if not (inv.instalment and inv.start_date):
            raise bad("Enter the amount paid each time and the start date.")
        if k in ("rd", "post_office", "chit") and not inv.months:
            raise bad("Enter the number of months.")
        if k == "insurance" and not inv.frequency:
            raise bad("Choose how often the premium is paid.")
        if k == "insurance" and inv.frequency != "single" and not (inv.months or inv.maturity_date):
            raise bad("Enter the premium-paying years or the maturity date.")
        if k in ("rd", "post_office") and inv.rate_bp is None:
            raise bad("Enter the interest rate.")
        return
    if k in ("fd", "post_office") and (inv.rate_bp is None or not inv.start_date or not inv.maturity_date):
        raise bad("Enter the interest rate, the start date and the maturity date.")
    if k == "lent" and not (inv.person and inv.start_date):
        raise bad("Enter who you lent to and when.")
    if k == "mf" and creating and not inv.quantity:
        raise bad("Enter the units you hold.")
    if k in ("gold", "stocks", "crypto") and not inv.quantity:
        raise bad("Enter the quantity." if k != "gold" else "Enter the grams (or units for SGB).")
    if creating and k in ("fd", "post_office", "lent") and not amount:
        raise bad("Enter the amount.")
    # property: payments can come later from the bank (a plot booked, nothing paid yet is fine)
    if creating and k in ("other", "retirement") and not amount and inv.current_value is None:
        raise bad("Enter the amount put in or the value today.")


def _default_name(body: InvestmentIn) -> str:
    if body.kind == "mf" and body.fund:
        return body.fund.scheme.strip()[:110]
    sub = SUBTYPE_LABEL.get(body.subtype or "")
    if body.kind == "lent":
        return f"Lent to {(body.person or '').strip() or 'someone'}"
    label = sub or KIND_LABEL[body.kind]
    who = (body.institution or "").strip()
    return f"{who} {label}".strip() if who else label


def _apply(inv: Investment, data: dict) -> None:
    for f in (
        "subtype",
        "institution",
        "number",
        "person",
        "compounding",
        "start_date",
        "maturity_date",
        "months",
        "instalment",
        "frequency",
        "sum_assured",
        "maturity_amount",
        "purity",
        "unit_price",
        "current_value",
        "value_date",
        "payout_on",
        "payout_amount",
        "pay_from_id",
        "notes",
        "closed_on",
    ):
        if f in data:
            v = data[f]
            setattr(inv, f, (v.strip() or None) if isinstance(v, str) else v)
    if "rate" in data:
        inv.rate_bp = round(data["rate"] * 100) if data["rate"] is not None else None
    if "quantity" in data:
        inv.quantity = round(data["quantity"] * 1000) if data["quantity"] is not None else None
    if ("unit_price" in data or "current_value" in data) and "value_date" not in data:
        inv.value_date = date.today()


# ---------------------------------------------------------------- list / add


@router.get("", response_model=list[InvestmentOut])
def list_investments(db: Session = Depends(get_db)) -> list[InvestmentOut]:
    return all_investments(db)


@router.get("/summary", response_model=InvestmentSummary)
def get_summary(db: Session = Depends(get_db)) -> InvestmentSummary:
    return summary(db)


@router.get("/dues", response_model=list[DueOut])
def dues(days: int = 30, db: Session = Depends(get_db)) -> list[DueOut]:
    return investment_dues(all_investments(db), days)


@router.get("/rates", response_model=RatesIO)
def rates(db: Session = Depends(get_db)) -> RatesIO:
    return rates_io(get_rates(db))


@router.put("/rates", response_model=RatesIO)
def update_rates(body: RatesIO, db: Session = Depends(get_db)) -> RatesIO:
    return rates_io(set_rates(db, body))


@router.post("", response_model=InvestmentDetail, status_code=201)
def create_investment(body: InvestmentIn, db: Session = Depends(get_db)) -> InvestmentDetail:
    if body.kind == "mf" and body.fund is None:
        raise bad("Pick the fund (scheme).")
    inv = Investment(kind=body.kind)
    _apply(inv, body.model_dump(exclude={"kind", "name", "amount", "money"}, exclude_unset=True))
    if inv.kind == "gold" and not inv.purity:
        inv.purity = "999" if inv.subtype == "silver" else "24k" if inv.subtype in ("sgb", "digital", "coin") else "22k"
    schedule = is_schedule(inv)
    amount = None if schedule else body.amount
    _check(inv, amount, creating=True)
    pay_from = bank_account(db, body.pay_from_id, "the money came from") if body.pay_from_id else None
    if body.money == "bank" and amount and pay_from is None:
        raise bad("Choose the bank account the money came from.")

    base = (body.name or "").strip() or _default_name(body)
    name, n = base, 2
    while db.scalar(
        select(Account.id).where(Account.type == AccountType.investment.value, func.lower(Account.name) == name.lower())
    ):
        name, n = f"{base} ({n})", n + 1
    on = inv.start_date or date.today()
    acct = Account(
        name=name,
        type=AccountType.investment.value,
        account_number=inv.number,
        opening_balance=amount if amount and body.money == "already" else 0,
        opening_date=on if amount and body.money == "already" else None,
        active=True,
    )
    db.add(acct)
    db.flush()
    inv.account_id = acct.id
    db.add(inv)
    db.flush()
    inv.account = acct
    if inv.kind == "mf" and body.fund:
        f = body.fund
        db.add(
            Fund(
                account_id=acct.id,
                scheme=f.scheme.strip(),
                isin=(f.isin or "").strip().upper() or None,
                amc=f.amc,
                folio=f.folio or inv.number,
                amfi_code=f.amfi_code,
                units=inv.quantity or 0,
                nav=f.nav,
                nav_date=f.nav_date,
                nav_source="amfi" if f.nav else None,
            )
        )
        inv.quantity = None  # units live on the fund
        db.flush()
        db.refresh(inv)
    if amount and body.money == "bank":
        move(db, inv, "in", amount, on, pay_from, None)  # type: ignore[arg-type]
    db.commit()
    db.refresh(inv)
    return detail_out(db, inv)


# ---------------------------------------------------------------- one investment


@router.get("/{account_id}", response_model=InvestmentDetail)
def get_investment(account_id: int, db: Session = Depends(get_db)) -> InvestmentDetail:
    return detail_out(db, _get(db, account_id))


@router.patch("/{account_id}", response_model=InvestmentDetail)
def update_investment(account_id: int, body: InvestmentPatch, db: Session = Depends(get_db)) -> InvestmentDetail:
    inv = _get(db, account_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name"):
        name = data["name"].strip()
        clash = db.scalar(
            select(Account.id).where(
                Account.type == AccountType.investment.value,
                func.lower(Account.name) == name.lower(),
                Account.id != account_id,
            )
        )
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, f"An investment named '{name}' already exists")
        inv.account.name = name
    if data.get("pay_from_id"):
        bank_account(db, data["pay_from_id"], "the money comes from")
    _apply(inv, {k: v for k, v in data.items() if k not in ("name", "amount")})
    if inv.kind == "mf" and "quantity" in data:
        fund = db.get(Fund, inv.account_id)
        if fund is not None and data["quantity"] is not None:
            fund.units = round(data["quantity"] * 1000)
        inv.quantity = None
    if "amount" in data and not is_schedule(inv):
        inv.account.opening_balance = data["amount"] or 0
        inv.account.opening_date = inv.account.opening_date or inv.start_date or date.today()
    if "number" in data:
        inv.account.account_number = inv.number
    _check(inv, None, creating=False)
    inv.account.active = inv.closed_on is None
    db.commit()
    db.refresh(inv)
    return detail_out(db, inv)


@router.post("/{account_id}/move", response_model=InvestmentDetail)
def add_move(account_id: int, body: MoveIn, db: Session = Depends(get_db)) -> InvestmentDetail:
    """Put money in (bank -> investment) or take it out (investment -> bank)."""
    inv = _get(db, account_id)
    bank = bank_account(db, body.bank_id, "the money " + ("comes from" if body.direction == "in" else "goes to"))
    move(db, inv, body.direction, body.amount, body.date, bank, (body.description or "").strip() or None)
    if inv.kind == "chit" and body.direction == "out" and not inv.payout_on:
        inv.payout_on, inv.payout_amount = body.date, body.amount  # the chit payout
    db.commit()
    db.refresh(inv)
    return detail_out(db, inv)


@router.post("/{account_id}/close", response_model=InvestmentDetail)
def close(account_id: int, body: CloseIn, db: Session = Depends(get_db)) -> InvestmentDetail:
    """Matured, sold, repaid or surrendered: optionally record the money received."""
    inv = _get(db, account_id)
    if body.amount:
        bank = bank_account(db, body.bank_id, "the money went to")
        move(db, inv, "out", body.amount, body.date, bank, None)
    inv.closed_on = body.date
    inv.account.active = False
    db.commit()
    db.refresh(inv)
    return detail_out(db, inv)


@router.post("/{account_id}/reopen", response_model=InvestmentDetail)
def reopen(account_id: int, db: Session = Depends(get_db)) -> InvestmentDetail:
    inv = _get(db, account_id)
    inv.closed_on = None
    inv.account.active = True
    db.commit()
    db.refresh(inv)
    return detail_out(db, inv)


# ---------------------------------------------------------------- past payments


def _linkable_query():
    """Bank / cash expenses and income not tied to a loan or card EMI."""
    from ..accounts.models import Account as A

    return (
        select(Transaction)
        .where(
            Transaction.loan_id.is_(None),
            Transaction.emi_id.is_(None),
            or_(
                (Transaction.type == "withdrawal")
                & Transaction.source_id.in_(select(A.id).where(A.type.in_(("asset", "cash")))),
                (Transaction.type == "deposit")
                & Transaction.destination_id.in_(select(A.id).where(A.type.in_(("asset", "cash")))),
            ),
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(5000)
    )


@router.get("/{account_id}/linkable", response_model=list[Linkable])
def linkable(account_id: int, db: Session = Depends(get_db)) -> list[Linkable]:
    """Past payments that look like money into (or back out of) this investment: its number
    or name in the description, a word for its kind, or its instalment amount."""
    inv = _get(db, account_id)
    out = []
    for t in db.scalars(_linkable_query()).unique():
        out_of_bank = t.type == "withdrawal"
        bank, other = (t.source, t.destination) if out_of_bank else (t.destination, t.source)
        text = f"{t.description} {other.name}"
        hit = score(inv, text, t.amount if out_of_bank else -t.amount)
        same_amount = bool(out_of_bank and inv.instalment and abs(t.amount - inv.instalment) <= 100)
        if hit is None and not same_amount:
            continue
        out.append(
            Linkable(
                transaction_id=t.id,
                date=t.date,
                amount=t.amount,
                direction="in" if out_of_bank else "out",
                description=t.description,
                account=bank.name,
                counterparty=other.name,
                category=t.category.name if t.category else None,
                suggested=hit is not None,
                why=hit.why if hit else "same amount as the instalment",
            )
        )
    return out


@router.post("/{account_id}/link", response_model=LinkOut)
def link(account_id: int, body: LinkIn, db: Session = Depends(get_db)) -> LinkOut:
    """Turn past bank expenses into transfers bank -> investment (and income into
    transfers investment -> bank). They stop counting as spending / income."""
    inv = _get(db, account_id)
    allowed = set(db.scalars(_linkable_query().with_only_columns(Transaction.id).limit(None)))
    put_in = 0
    for tid in body.ids:
        t = db.get(Transaction, tid)
        if t is None or tid not in allowed:
            raise bad("A chosen payment can't be moved here (it changed or belongs to a loan or card EMI).")
        if t.type == "withdrawal":
            t.destination_id = inv.account_id
            put_in += t.amount
        else:
            t.source_id = inv.account_id
            put_in -= t.amount
        t.type = "transfer"
        t.category_id = t.budget_id = t.bill_id = None
    if body.lower_opening and put_in > 0:
        inv.account.opening_balance = max(0, inv.account.opening_balance - put_in)
    db.commit()
    db.refresh(inv)
    return LinkOut(linked=len(body.ids), investment=detail_out(db, inv))


@router.delete("/{account_id}", status_code=204)
def delete_investment(account_id: int, db: Session = Depends(get_db)) -> None:
    """Remove an investment and its money in / out entries (transfers to and from it)."""
    inv = _get(db, account_id)
    for t in db.scalars(
        select(Transaction).where(or_(Transaction.source_id == account_id, Transaction.destination_id == account_id))
    ).unique():
        db.delete(t)
    a = inv.account
    db.delete(inv)
    db.flush()
    db.delete(a)
    db.commit()


# ---------------------------------------------------------------- property bought in parts


def _property(db: Session, account_id: int) -> Investment:
    inv = _get(db, account_id)
    if inv.kind != "property":
        raise bad("Only property has a purchase plan.")
    return inv


@router.put("/{account_id}/property", response_model=InvestmentDetail)
def save_property(account_id: int, body: PropertyIn, db: Session = Depends(get_db)) -> InvestmentDetail:
    """The deal: agreed price, details, status and the plan for the balance (replaces the plan)."""
    inv = _property(db, account_id)
    if body.status == "registered" and body.registered_on is None:
        raise bad("Enter the date it was registered in your name.")
    d = db.get(PropertyDeal, account_id) or PropertyDeal(account_id=account_id)
    for k in ("price", "agreement_date", "status", "registered_on"):
        setattr(d, k, getattr(body, k))
    for k in ("size", "location", "survey_no", "seller"):
        setattr(d, k, (getattr(body, k) or "").strip() or None)
    if body.status != "registered":
        d.registered_on = None
    d.plan = [
        PropertyInstalment(due_date=i.due_date, amount=i.amount, note=(i.note or "").strip() or None) for i in body.plan
    ]
    db.add(d)
    db.commit()
    db.refresh(inv)
    return detail_out(db, inv)


@router.post("/{account_id}/property/costs", response_model=InvestmentDetail)
def add_cost(account_id: int, body: CostIn, db: Session = Depends(get_db)) -> InvestmentDetail:
    """Stamp duty, registration, lawyer, broker … — paid now from a bank (a transfer into the property)
    or noted as paid already."""
    inv = _property(db, account_id)
    d = db.get(PropertyDeal, account_id)
    if d is None:
        d = PropertyDeal(account_id=account_id)
        db.add(d)
        db.flush()
    txn_id = None
    if body.bank_id:
        bank = bank_account(db, body.bank_id, "the cost is paid from")
        label = {"stamp_duty": "Stamp duty", "registration": "Registration fee", "legal": "Legal fees",
                 "broker": "Brokerage", "other": "Cost"}[body.kind]  # fmt: skip
        txn_id = move(db, inv, "in", body.amount, body.date, bank, f"{label}: {inv.account.name}").id
    d.costs.append(PropertyCost(kind=body.kind, amount=body.amount, date=body.date,
                                note=(body.note or "").strip() or None, transaction_id=txn_id))  # fmt: skip
    db.commit()
    db.refresh(inv)
    return detail_out(db, inv)


@router.delete("/{account_id}/property/costs/{cost_id}", response_model=InvestmentDetail)
def remove_cost(account_id: int, cost_id: int, db: Session = Depends(get_db)) -> InvestmentDetail:
    """Remove a cost, and its payment when it was paid through MoneyMap."""
    inv = _property(db, account_id)
    c = db.get(PropertyCost, cost_id)
    if c is None or c.account_id != account_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cost not found")
    if c.transaction_id and (t := db.get(Transaction, c.transaction_id)) is not None:
        db.delete(t)
    d = db.get(PropertyDeal, account_id)
    if d is not None and c in d.costs:
        d.costs.remove(c)  # delete-orphan
    else:
        db.delete(c)
    db.commit()
    db.refresh(inv)
    return detail_out(db, inv)


@router.post("/{account_id}/property/goal", response_model=InvestmentDetail)
def make_goal(account_id: int, body: GoalIn, db: Session = Depends(get_db)) -> InvestmentDetail:
    """A piggy bank for the balance still to pay, by the last planned date; it follows the balance."""
    from ..piggybanks.models import PiggyBank

    inv = _property(db, account_id)
    d = db.get(PropertyDeal, account_id)
    detail = detail_out(db, inv)
    bal = detail.property.balance if detail.property else None
    if d is None or not bal:
        raise bad("Enter the agreed price first — the goal is the balance still to pay.")
    if d.goal_id and db.get(PiggyBank, d.goal_id):
        raise bad("This property already has a goal.")
    bank = bank_account(db, body.account_id, "the money is set aside in")
    g = PiggyBank(name=f"{inv.account.name} — balance"[:120], account_id=bank.id, target_amount=bal,
                  target_date=max((i.due_date for i in d.plan), default=None))  # fmt: skip
    db.add(g)
    db.flush()
    d.goal_id = g.id
    db.commit()
    db.refresh(inv)
    return detail_out(db, inv)
