"""Investments: ledger entries, values, coming up, gold / silver rates."""

from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..accounts.models import Account
from ..auth.models import Setting
from ..transactions.models import Transaction
from ..transactions.schemas import TransactionIn
from ..transactions.service import apply_body, txn_out
from .models import FundTxn, Investment
from .schemas import (
    DueOut,
    FundOut,
    FundTxnOut,
    InvestmentDetail,
    InvestmentOut,
    InvestmentSummary,
    KindTotal,
    RatesIO,
)
from .values import Rates, Valued, compounding_of, maturity_of, value_of

BANK_TYPES = ("asset", "cash")
RATE_KEYS = {"gold_24k": "invest.gold_24k", "silver": "invest.silver", "date": "invest.rate_date"}
KIND_LABEL = {
    "mf": "Mutual funds",
    "fd": "Fixed deposit",
    "rd": "Recurring deposit",
    "post_office": "Post Office",
    "retirement": "PPF / EPF / NPS",
    "insurance": "Insurance",
    "lent": "Money lent",
    "chit": "Chit fund",
    "gold": "Gold & silver",
    "stocks": "Stocks & shares",
    "crypto": "Crypto",
    "property": "Property",
    "other": "Other",
}


def bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


# ---------------------------------------------------------------- rates


def get_rates(db: Session) -> Rates:
    vals = {k: db.get(Setting, key) for k, key in RATE_KEYS.items()}
    num = lambda s: int(s.value) if s and s.value else None  # noqa: E731
    d = vals["date"]
    return Rates(
        gold_24k=num(vals["gold_24k"]),
        silver=num(vals["silver"]),
        on=date.fromisoformat(d.value) if d and d.value else None,
    )


def set_rates(db: Session, body: RatesIO) -> Rates:
    on = body.date or date.today()
    for k, v in (("gold_24k", body.gold_24k), ("silver", body.silver), ("date", on.isoformat())):
        key = RATE_KEYS[k]
        s = db.get(Setting, key)
        text = "" if v is None else str(v)
        if s is None:
            db.add(Setting(key=key, value=text))
        else:
            s.value = text
    db.commit()
    return get_rates(db)


def rates_io(r: Rates) -> RatesIO:
    return RatesIO(gold_24k=r.gold_24k, silver=r.silver, date=r.on)


# ---------------------------------------------------------------- values


def _entries(inv: Investment, txns: list[Transaction]) -> list[tuple[date, int]]:
    """Money in (+) and out (-) of the investment's account, opening balance first."""
    a = inv.account
    out: list[tuple[date, int]] = []
    if a.opening_balance:
        out.append((a.opening_date or inv.start_date or date.today(), a.opening_balance))
    for t in txns:
        if t.destination_id == a.id:
            out.append((t.date, t.amount))
        elif t.source_id == a.id:
            out.append((t.date, -t.amount))
    return sorted(out, key=lambda x: x[0])


def _txns(db: Session, account_ids: list[int]) -> dict[int, list[Transaction]]:
    by: dict[int, list[Transaction]] = {i: [] for i in account_ids}
    if not account_ids:
        return by
    q = select(Transaction).where(
        or_(Transaction.source_id.in_(account_ids), Transaction.destination_id.in_(account_ids))
    )
    for t in db.scalars(q).unique():
        for side in (t.source_id, t.destination_id):
            if side in by:
                by[side].append(t)
    return by


def valued(inv: Investment, txns: list[Transaction], rates: Rates, today: date) -> Valued:
    entries = _entries(inv, txns)
    if inv.closed_on:
        v = value_of(inv, entries, min(today, inv.closed_on), rates)
        v.value, v.owed, v.dues, v.stale, v.no_price = 0, 0, [], False, False
        return v
    return value_of(inv, entries, today, rates)


def _dues(inv: Investment, v: Valued, today: date) -> list[DueOut]:
    return [
        DueOut(
            account_id=inv.account_id,
            name=inv.account.name,
            kind=inv.kind,
            date=d.date,
            what=d.what,
            amount=d.amount,
            overdue=d.date < today,
        )
        for d in v.dues
        if d.date >= today or d.what in ("matures", "due_back")
    ]


def investment_out(inv: Investment, txns: list[Transaction], rates: Rates, today: date | None = None) -> InvestmentOut:
    today = today or date.today()
    v = valued(inv, txns, rates, today)
    dues = sorted(_dues(inv, v, today), key=lambda d: d.date)
    base = v.money_in or None
    if inv.kind == "chit" and inv.payout_on and inv.instalment and v.total_count:
        base = inv.instalment * v.total_count  # gain = payout - all the instalments
    return InvestmentOut(
        id=inv.account_id,
        name=inv.account.name,
        kind=inv.kind,
        subtype=inv.subtype,
        institution=inv.institution,
        number=inv.number,
        person=inv.person,
        rate=inv.rate_bp / 100 if inv.rate_bp is not None else None,
        compounding=compounding_of(inv),
        start_date=inv.start_date,
        maturity_date=maturity_of(inv),
        months=inv.months,
        instalment=inv.instalment,
        frequency=inv.frequency,
        sum_assured=inv.sum_assured,
        maturity_amount=inv.maturity_amount,
        quantity=inv.quantity / 1000 if inv.quantity is not None else None,
        purity=inv.purity,
        unit_price=inv.unit_price,
        current_value=inv.current_value,
        payout_on=inv.payout_on,
        payout_amount=inv.payout_amount,
        pay_from_id=inv.pay_from_id,
        opening=inv.account.opening_balance,
        closed_on=inv.closed_on,
        notes=inv.notes,
        status="closed" if inv.closed_on else "active",
        money_in=v.money_in,
        money_out=v.money_out,
        invested=v.invested,
        value=v.value,
        gain=v.gain,
        gain_pct=round(v.gain * 100 / base, 2) if base else None,
        value_date=v.value_date,
        maturity_value=v.maturity_value,
        paid_count=v.paid_count,
        total_count=v.total_count,
        owed=v.owed,
        stale=v.stale,
        no_price=v.no_price,
        next_due=dues[0] if dues else None,
        fund=_fund_out(inv),
    )


def _fund_out(inv: Investment) -> FundOut | None:
    f = inv.fund if inv.kind == "mf" else None
    if f is None:
        return None
    return FundOut(
        scheme=f.scheme,
        amc=f.amc,
        isin=f.isin,
        folio=f.folio,
        units=f.units / 1000,
        units_as_of=f.units_as_of,
        nav=f.nav / 10_000 if f.nav is not None else None,
        nav_date=f.nav_date,
        nav_source=f.nav_source,
        cost=f.cost,
    )


def detail_out(db: Session, inv: Investment) -> InvestmentDetail:
    txns = _txns(db, [inv.account_id])[inv.account_id]
    out = investment_out(inv, txns, get_rates(db))
    moves = sorted(txns, key=lambda t: (t.date, t.id), reverse=True)
    from .cas_service import KIND_LABEL as TXN_LABEL

    fts = db.scalars(
        select(FundTxn).where(FundTxn.account_id == inv.account_id).order_by(FundTxn.date.desc(), FundTxn.id.desc())
    )
    fund_txns = [
        FundTxnOut(
            id=f.id,
            date=f.date,
            kind=f.kind,
            kind_label=TXN_LABEL.get(f.kind, f.kind),
            description=f.description,
            amount=f.amount,
            units=f.units / 1000,
            nav=f.nav / 10_000,
            stamp_duty=f.stamp_duty,
            transaction_id=f.transaction_id,
        )
        for f in fts
    ]
    return InvestmentDetail(
        **out.model_dump(exclude={"fund"}), fund=out.fund, moves=[txn_out(t) for t in moves], fund_txns=fund_txns
    )


def _all(db: Session) -> list[Investment]:
    return list(db.scalars(select(Investment).join(Account, Investment.account_id == Account.id)).unique())


def all_investments(db: Session, today: date | None = None) -> list[InvestmentOut]:
    invs = _all(db)
    by = _txns(db, [i.account_id for i in invs])
    rates = get_rates(db)
    out = [investment_out(i, by[i.account_id], rates, today) for i in invs]
    order = list(KIND_LABEL)
    return sorted(out, key=lambda x: (x.status == "closed", order.index(x.kind), x.name.lower()))


def investment_dues(items: list[InvestmentOut], days: int = 30, today: date | None = None) -> list[DueOut]:
    """Maturities, premiums, money due back and chit instalments in the next `days` days
    (plus matured / due-back ones not closed yet)."""
    today = today or date.today()
    until = today + timedelta(days=days)
    out = [i.next_due for i in items if i.status == "active" and i.next_due and i.next_due.date <= until]
    return sorted(out, key=lambda d: d.date)  # type: ignore[arg-type, return-value]


def summary(db: Session, today: date | None = None) -> InvestmentSummary:
    items = all_investments(db, today)
    active = [i for i in items if i.status == "active"]
    kinds: dict[str, KindTotal] = {}
    for i in active:
        k = kinds.setdefault(i.kind, KindTotal(kind=i.kind, count=0, invested=0, value=0))
        k.count += 1
        k.invested += i.invested
        k.value += i.value
    invested = sum(i.invested for i in active)
    value = sum(i.value for i in active)
    return InvestmentSummary(
        invested=invested,
        value=value,
        gain=value - invested,
        owed=sum(i.owed for i in active),
        count=len(active),
        by_kind=sorted(kinds.values(), key=lambda k: -k.value),
        dues=investment_dues(items, 30, today),
        rates=rates_io(get_rates(db)),
    )


# ---------------------------------------------------------------- money in / out


def bank_account(db: Session, account_id: int | None, label: str) -> Account:
    a = db.get(Account, account_id) if account_id else None
    if a is None or a.type not in BANK_TYPES:
        raise bad(f"Choose the bank or cash account {label}.")
    return a


def move(db: Session, inv: Investment, direction: str, amount: int, on: date, bank: Account, desc: str | None) -> None:
    """A transfer bank -> investment (money in) or investment -> bank (money out)."""
    name = inv.account.name
    if not desc:
        if inv.kind == "lent":
            desc = f"Lent to {inv.person or name}" if direction == "in" else f"Repaid by {inv.person or name}"
        else:
            desc = f"Invested: {name}" if direction == "in" else f"From investment: {name}"
    src, dst = (bank, inv.account) if direction == "in" else (inv.account, bank)
    t = Transaction()
    body = TransactionIn(
        type="transfer",  # type: ignore[arg-type]
        date=on,
        amount=amount,
        description=desc,
        source_id=src.id,
        destination_id=dst.id,
        auto_match_bill=False,
    )
    apply_body(db, t, body, is_new=True)
    db.add(t)
    db.flush()
