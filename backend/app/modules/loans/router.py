import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...db import get_db
from ..accounts.models import Account, AccountType
from ..accounts.service import find_or_create_counterparty
from ..auth.security import current_user
from ..transactions.models import Transaction, TransactionType
from .actions import (
    BANK_TYPES,
    ROUNDING,
    _bad,
    _new_txn,
    change_count_mode,
    close_loan,
    link_payments,
    record_prepay,
    remove_event,
)
from .maths import Event, calc_emi, first_emi_interest, flat_emi, schedule_for
from .models import Loan, LoanEvent
from .schemas import (
    CloseIn,
    EventPatch,
    Linkable,
    LinkIn,
    LinkOut,
    LoanDetail,
    LoanDue,
    LoanIn,
    LoanOut,
    LoanPatch,
    PayIn,
    PayoffOut,
    PlanOut,
    PrepayIn,
    RateIn,
    WhatIfIn,
    WhatIfOut,
)
from .service import (
    EMI_CATEGORY,
    FEE_CATEGORY,
    INTEREST_CATEGORY,
    all_loans,
    category_id,
    loan_dues,
    loan_out,
    principal_left,
    remaining,
    schedule_with,
    supports_changes,
    to_events,
)

router = APIRouter(prefix="/loans", tags=["loans"], dependencies=[Depends(current_user)])


def _get(db: Session, account_id: int) -> Loan:
    loan = db.scalar(select(Loan).where(Loan.account_id == account_id))
    if loan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loan not found")
    return loan


def _bank(db: Session, account_id: int | None, label: str) -> Account:
    a = db.get(Account, account_id) if account_id else None
    if a is None or a.type not in BANK_TYPES:
        raise _bad(f"Choose the bank or cash account {label}.")
    return a


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _candidates(db: Session, emi: int, loan_number: str | None, lender: str | None) -> list[Linkable]:
    """Expenses from a bank or cash account that look like this loan's EMI: the
    "Loan / EMI" category, the loan number or lender in the description, or the EMI amount."""
    emi_cat = category_id(db, EMI_CATEGORY)
    num = _digits(loan_number)[-4:]
    lender_word = next(iter(re.findall(r"[a-z]{3,}", (lender or "").lower())), None)
    q = (
        select(Transaction)
        .join(Account, Transaction.source_id == Account.id)
        .where(
            Transaction.type == TransactionType.withdrawal.value,
            Account.type.in_(BANK_TYPES),
            Transaction.loan_id.is_(None),
        )
        .order_by(Transaction.date.desc())
        .limit(2000)
    )
    out = []
    for t in db.scalars(q).unique():
        text = f"{t.description} {t.destination.name}".lower()
        by_number = bool(num) and num in _digits(text)
        by_lender = bool(lender_word) and lender_word in text
        by_category = emi_cat is not None and t.category_id == emi_cat
        emi_like = abs(t.amount - emi) <= ROUNDING
        if not (by_number or by_lender or by_category or emi_like):
            continue
        out.append(
            Linkable(
                transaction_id=t.id,
                date=t.date,
                amount=t.amount,
                description=t.description,
                paid_from=t.source.name,
                category=t.category.name if t.category else None,
                emi_like=emi_like,
                suggested=emi_like and (by_number or by_lender or by_category),
            )
        )
    return out


# ---------------------------------------------------------------- list / add


@router.get("", response_model=list[LoanOut])
def list_loans(db: Session = Depends(get_db)) -> list[LoanOut]:
    return all_loans(db)


@router.get("/dues", response_model=list[LoanDue])
def dues(days: int = 30, db: Session = Depends(get_db)) -> list[LoanDue]:
    return loan_dues(db, days)


@router.get("/candidates", response_model=list[Linkable])
def candidates(
    emi: int = Query(gt=0),
    loan_number: str | None = None,
    lender: str | None = None,
    db: Session = Depends(get_db),
) -> list[Linkable]:
    """Past expenses that look like an EMI of a loan you're about to add."""
    return _candidates(db, emi, loan_number, lender)


@router.post("", response_model=LoanDetail, status_code=201)
def create_loan(body: LoanIn, db: Session = Depends(get_db)) -> LoanDetail:
    rate_bp = round(body.rate * 100) if body.rate is not None else None
    if body.method in ("reducing", "flat") and (body.principal is None or rate_bp is None):
        raise _bad("Enter the loan amount and the interest rate.")
    if body.method == "emi_only" and body.emi is None:
        raise _bad("Enter the EMI.")
    if body.count_mode == "interest_only" and body.method == "emi_only" and not body.principal:
        raise _bad("To count only the interest as spending, enter the loan amount so the EMI can be split.")
    if body.disbursed_date and body.disbursed_date > body.first_emi_date:
        raise _bad("The loan must be taken on or before the first EMI date.")
    by_days = body.method == "reducing" and body.first_interest != "month"
    if by_days and not body.disbursed_date:
        raise _bad("Enter the date the loan was taken on — the first EMI's interest is counted from it.")
    bpi = (
        first_emi_interest(body.principal, rate_bp, body.first_emi_date, body.disbursed_date, body.first_interest)
        if by_days
        else None
    )
    emi = body.emi or (
        calc_emi(body.principal, rate_bp, body.tenure, bpi)
        if body.method == "reducing"
        else flat_emi(body.principal, rate_bp, body.tenure)
    )
    try:
        rows = schedule_for(
            body.method, body.principal, rate_bp, emi, body.tenure, body.first_emi_date, bpi,
            daily=body.interest_basis == "days365",
        )  # fmt: skip
    except ValueError as e:
        raise _bad(str(e)) from e
    pay_from = _bank(db, body.pay_from_id, "the EMI is paid from") if body.pay_from_id else None

    name, n = body.name, 2
    while db.scalar(select(Account.id).where(Account.type == "loan", func.lower(Account.name) == name.lower())):
        name, n = f"{body.name} ({n})", n + 1
    acct = Account(
        name=name, type=AccountType.loan.value, account_number=body.loan_number, opening_balance=0, active=True
    )
    db.add(acct)
    db.flush()
    loan = Loan(
        account_id=acct.id,
        lender=(body.lender or "").strip() or None,
        kind=body.kind,
        loan_number=(body.loan_number or "").strip() or None,
        method=body.method,
        count_mode=body.count_mode,
        principal=body.principal,
        rate_bp=rate_bp if body.method != "emi_only" else None,
        tenure=body.tenure,
        emi=emi,
        first_emi_date=body.first_emi_date,
        disbursed_date=body.disbursed_date,
        first_interest=body.first_interest,
        interest_basis=body.interest_basis,
        pay_from_id=pay_from.id if pay_from else None,
        paid_before=0,
        notes=(body.notes or "").strip() or None,
    )
    db.add(loan)
    db.flush()
    loan.account = acct

    on = body.disbursed_date or (body.first_emi_date - timedelta(days=30))
    if body.start == "new" and body.money == "received":
        if not body.principal:
            raise _bad("Enter the loan amount to record the money received.")
        into = _bank(db, body.received_into_id, "the loan money came into")
        charges = body.charges or 0
        if charges >= body.principal:
            raise _bad("The charges must be less than the loan amount.")
        _new_txn(
            db,
            {
                "type": "transfer",
                "date": on,
                "amount": body.principal - charges,  # what reached the bank: its statement shows the same
                "description": f"Loan received: {acct.name}",
                "source_id": acct.id,
                "destination_id": into.id,
            },
            loan,
            "disbursal",
        )
        if charges:  # processing fee, GST, insurance … kept by the lender: paid out of the loan
            _new_txn(
                db,
                {
                    "type": "withdrawal",
                    "date": on,
                    "amount": charges,
                    "description": f"Loan charges: {acct.name}",
                    "source_id": acct.id,
                    "destination_name": (body.lender or acct.name).strip(),
                    "category_id": category_id(db, FEE_CATEGORY),
                },
                loan,
                "charges",
            )
    elif body.start == "new" and body.money == "seller" and body.count_mode == "interest_only":
        if not body.principal:
            raise _bad("Enter the loan amount.")
        _new_txn(
            db,
            {
                "type": "withdrawal",
                "date": on,
                "amount": body.principal,
                "description": f"Paid with loan: {acct.name}",
                "source_id": acct.id,
                "destination_name": (body.seller_name or body.lender or acct.name).strip(),
                "category_id": body.category_id,
            },
            loan,
            "disbursal",
        )

    if body.start == "existing":
        today = date.today()
        loan.paid_before = body.paid_before if body.paid_before is not None else sum(1 for r in rows if r.date < today)
    if body.link_ids:
        txns = [db.get(Transaction, i) for i in body.link_ids]
        if any(t is None for t in txns):
            raise _bad("A chosen transaction no longer exists.")
        link_payments(db, loan, txns)  # type: ignore[arg-type]
    db.commit()
    db.refresh(loan)
    return loan_out(db, loan, detail=True)  # type: ignore[return-value]


# ---------------------------------------------------------------- one loan


@router.get("/{account_id}", response_model=LoanDetail)
def get_loan(account_id: int, db: Session = Depends(get_db)) -> LoanDetail:
    return loan_out(db, _get(db, account_id), detail=True)  # type: ignore[return-value]


@router.patch("/{account_id}", response_model=LoanDetail)
def update_loan(account_id: int, body: LoanPatch, db: Session = Depends(get_db)) -> LoanDetail:
    loan = _get(db, account_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name"):
        loan.account.name = data["name"].strip()
    if "lender" in data:
        loan.lender = (data["lender"] or "").strip() or None
    if data.get("kind"):
        loan.kind = data["kind"]
    if "loan_number" in data:
        loan.loan_number = (data["loan_number"] or "").strip() or None
        loan.account.account_number = loan.loan_number
    if "pay_from_id" in data:
        loan.pay_from_id = _bank(db, data["pay_from_id"], "the EMI is paid from").id if data["pay_from_id"] else None
    if "notes" in data:
        loan.notes = (data["notes"] or "").strip() or None
    if "closed_on" in data:
        loan.closed_on = data["closed_on"]
    terms = (
        "method", "principal", "rate", "tenure", "emi", "first_emi_date", "disbursed_date", "first_interest",
        "interest_basis",
    )  # fmt: skip
    if any(k in data for k in terms):
        method = data.get("method") or loan.method
        principal = data.get("principal", loan.principal)
        rate_bp = round(data["rate"] * 100) if data.get("rate") is not None else loan.rate_bp
        tenure = data.get("tenure") or loan.tenure
        first = data.get("first_emi_date") or loan.first_emi_date
        taken_on = data.get("disbursed_date", loan.disbursed_date)
        first_mode = data.get("first_interest") or loan.first_interest
        basis = data.get("interest_basis") or loan.interest_basis
        if taken_on and taken_on > first:
            raise _bad("The loan must be taken on or before the first EMI date.")
        by_days = method == "reducing" and first_mode != "month"
        if by_days and not taken_on:
            raise _bad("Enter the date the loan was taken on — the first EMI's interest is counted from it.")
        bpi = first_emi_interest(principal, rate_bp, first, taken_on, first_mode) if by_days else None
        emi = data.get("emi")
        # the EMI is worked out again when the amount, rate, months or method change (unless given);
        # a new date or first-EMI interest keeps the EMI you have (often the lender's own)
        rework = any(k in data for k in ("method", "principal", "rate", "tenure"))
        if emi is None and method != "emi_only" and (rework or "emi" in data):
            if principal is None or rate_bp is None:
                raise _bad("Enter the loan amount and the interest rate.")
            if method == "reducing":
                emi = calc_emi(principal, rate_bp, tenure, bpi)
            else:
                emi = flat_emi(principal, rate_bp, tenure)
        emi = emi or loan.emi
        try:
            schedule_for(method, principal, rate_bp, emi, tenure, first, bpi, daily=basis == "days365")
        except ValueError as e:
            raise _bad(str(e)) from e
        loan.method, loan.principal, loan.tenure, loan.emi, loan.first_emi_date = method, principal, tenure, emi, first
        loan.disbursed_date, loan.first_interest, loan.interest_basis = taken_on, first_mode, basis
        loan.rate_bp = rate_bp if method != "emi_only" else None
        if not supports_changes(loan) and loan.events:
            raise _bad("Remove the part-payments and rate changes first — they need a reducing-balance loan.")
        try:
            schedule_with(loan, to_events(loan.events))
        except ValueError as e:
            raise _bad(str(e)) from e
    if data.get("paid_before") is not None:
        loan.paid_before = data["paid_before"]
    if data.get("count_mode"):
        change_count_mode(db, loan, data["count_mode"])
    db.commit()
    db.refresh(loan)
    return loan_out(db, loan, detail=True)  # type: ignore[return-value]


# ---------------------------------------------------------------- part-payments, rate changes


def _plan(rows, after) -> PlanOut:
    return PlanOut(**remaining(rows, after))


@router.post("/{account_id}/what-if", response_model=WhatIfOut)
def what_if(account_id: int, body: WhatIfIn, db: Session = Depends(get_db)) -> WhatIfOut:
    """What a part-payment or a rate change would do to the EMIs still to come."""
    loan = _get(db, account_id)
    if not supports_changes(loan):
        raise _bad("Part-payments and rate changes work on reducing-balance loans (with an amount and a rate).")
    on = body.date or date.today()
    current = to_events(loan.events)
    if body.kind == "prepay":
        if not body.amount:
            raise _bad("Enter the amount.")
        extra = Event(on, "prepay", body.mode, amount=body.amount)
    else:
        if body.rate is None:
            raise _bad("Enter the new interest rate.")
        extra = Event(on, "rate", body.mode, rate_bp=round(body.rate * 100))
    before_rows, _ = schedule_with(loan, current)
    try:
        after_rows, _ = schedule_with(loan, [*current, extra])
    except ValueError as e:
        raise _bad(str(e)) from e
    before, after = _plan(before_rows, on), _plan(after_rows, on)
    out = loan_out(db, loan)
    return WhatIfOut(
        outstanding=out.outstanding,
        before=before,
        after=after,
        interest_saved=before.interest - after.interest,
        months_saved=before.months - after.months,
        paid_off=after.months == 0,
    )


@router.post("/{account_id}/prepay", response_model=LoanDetail)
def prepay(account_id: int, body: PrepayIn, db: Session = Depends(get_db)) -> LoanDetail:
    loan = _get(db, account_id)
    if not supports_changes(loan):
        raise _bad("Part-payments work on reducing-balance loans (with an amount and a rate).")
    existing = db.get(Transaction, body.transaction_id) if body.transaction_id else None
    if body.transaction_id and existing is None:
        raise _bad("That transaction no longer exists.")
    src = None
    if existing is None and body.record_payment:
        src = (
            db.get(Account, body.from_account_id or loan.pay_from_id)
            if (body.from_account_id or loan.pay_from_id)
            else None
        )
    record_prepay(db, loan, body.date, body.amount, body.mode, src, existing, body.fee, body.record_payment)
    db.commit()
    db.refresh(loan)
    return loan_out(db, loan, detail=True)  # type: ignore[return-value]


@router.post("/{account_id}/rate", response_model=LoanDetail)
def rate_change(account_id: int, body: RateIn, db: Session = Depends(get_db)) -> LoanDetail:
    """A floating-rate change from `date`: EMIs already due keep their figures."""
    loan = _get(db, account_id)
    if not supports_changes(loan):
        raise _bad("Rate changes work on reducing-balance loans (with an amount and a rate).")
    ev = LoanEvent(kind="rate", date=body.date, mode=body.mode, rate_bp=round(body.rate * 100))
    try:
        schedule_with(loan, [*to_events(loan.events), Event(ev.date, "rate", ev.mode, rate_bp=ev.rate_bp)])
    except ValueError as e:
        raise _bad(str(e)) from e
    loan.events.append(ev)
    db.commit()
    db.refresh(loan)
    return loan_out(db, loan, detail=True)  # type: ignore[return-value]


def _event(loan: Loan, event_id: int) -> LoanEvent:
    ev = next((e for e in loan.events if e.id == event_id), None)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change not found")
    return ev


@router.get("/{account_id}/payoff", response_model=PayoffOut)
def payoff(account_id: int, on: date = Query(...), db: Session = Depends(get_db)) -> PayoffOut:
    """What was left to repay on a day — the most a payment closing the loan clears."""
    loan = _get(db, account_id)
    if not supports_changes(loan):
        raise _bad("Closing early works on reducing-balance loans (with an amount and a rate).")
    return PayoffOut(date=on, left=principal_left(loan, on))


@router.post("/{account_id}/close", response_model=LoanDetail)
def close(account_id: int, body: CloseIn, db: Session = Depends(get_db)) -> LoanDetail:
    """The loan paid off early (foreclosed) with one payment."""
    loan = _get(db, account_id)
    if not supports_changes(loan):
        raise _bad("Closing early works on reducing-balance loans (with an amount and a rate).")
    existing = db.get(Transaction, body.transaction_id) if body.transaction_id else None
    if body.transaction_id and existing is None:
        raise _bad("That transaction no longer exists.")
    src = None
    if existing is None:
        src = db.get(Account, body.from_account_id or loan.pay_from_id or -1)
    close_loan(db, loan, body.date, body.amount, from_account=src, existing=existing)
    db.commit()
    db.refresh(loan)
    return loan_out(db, loan, detail=True)  # type: ignore[return-value]


@router.patch("/{account_id}/events/{event_id}", response_model=LoanDetail)
def change_event(account_id: int, event_id: int, body: EventPatch, db: Session = Depends(get_db)) -> LoanDetail:
    """Switch a part-payment / rate change between keeping the EMI and keeping the end date."""
    loan = _get(db, account_id)
    ev = _event(loan, event_id)
    if ev.mode == "close":
        raise _bad("A loan closed early has no EMIs left to switch.")
    old = ev.mode
    ev.mode = body.mode
    try:
        schedule_with(loan, to_events(loan.events))
    except ValueError as e:
        ev.mode = old
        raise _bad(str(e)) from e
    db.commit()
    db.refresh(loan)
    return loan_out(db, loan, detail=True)  # type: ignore[return-value]


@router.delete("/{account_id}/events/{event_id}", response_model=LoanDetail)
def delete_event(account_id: int, event_id: int, db: Session = Depends(get_db)) -> LoanDetail:
    loan = _get(db, account_id)
    remove_event(db, loan, _event(loan, event_id))
    db.commit()
    db.refresh(loan)
    return loan_out(db, loan, detail=True)  # type: ignore[return-value]


@router.post("/{account_id}/pay", response_model=LoanDetail)
def record_emi(account_id: int, body: PayIn, db: Session = Depends(get_db)) -> LoanDetail:
    """Record the next EMI as paid, split the way this loan counts as spending."""
    loan = _get(db, account_id)
    out = loan_out(db, loan)
    if out.next is None:
        raise _bad("This loan has no EMIs left to pay.")
    row = out.next
    src = _bank(db, body.from_account_id or loan.pay_from_id, "the EMI is paid from")
    on = body.date or row.date
    label = f"EMI {row.n}/{loan.tenure} · {loan.account.name}"
    who = loan.lender or loan.account.name
    if loan.count_mode == "whole_emi":
        _new_txn(
            db,
            {
                "type": "withdrawal",
                "date": on,
                "amount": row.emi,
                "description": label,
                "source_id": src.id,
                "destination_name": f"{who} EMI",
                "category_id": category_id(db, EMI_CATEGORY),
            },
            loan,
            "emi",
            row.n,
        )
    else:
        _new_txn(
            db,
            {
                "type": "transfer",
                "date": on,
                "amount": row.principal,
                "description": f"{label} (principal)",
                "source_id": src.id,
                "destination_id": loan.account_id,
            },
            loan,
            "principal",
            row.n,
        )
        if row.interest > 0:
            _new_txn(
                db,
                {
                    "type": "withdrawal",
                    "date": on,
                    "amount": row.interest,
                    "description": f"Interest · {label}",
                    "source_id": src.id,
                    "destination_name": f"{who} interest",
                    "category_id": category_id(db, INTEREST_CATEGORY),
                },
                loan,
                "interest",
                row.n,
            )
    db.commit()
    db.refresh(loan)
    return loan_out(db, loan, detail=True)  # type: ignore[return-value]


@router.get("/{account_id}/linkable", response_model=list[Linkable])
def linkable(account_id: int, db: Session = Depends(get_db)) -> list[Linkable]:
    loan = _get(db, account_id)
    return _candidates(db, loan.emi, loan.loan_number, loan.lender)


@router.post("/{account_id}/link", response_model=LinkOut)
def link(account_id: int, body: LinkIn, db: Session = Depends(get_db)) -> LinkOut:
    loan = _get(db, account_id)
    txns = [db.get(Transaction, i) for i in body.transaction_ids]
    if any(t is None for t in txns):
        raise _bad("A chosen transaction no longer exists.")
    n = link_payments(db, loan, txns)  # type: ignore[arg-type]
    db.commit()
    db.refresh(loan)
    return LinkOut(linked=n, loan=loan_out(db, loan, detail=True))  # type: ignore[arg-type]


@router.delete("/{account_id}", status_code=204)
def delete_loan(account_id: int, db: Session = Depends(get_db)) -> None:
    """Remove a loan. The money-received / purchase entry it made is deleted; EMIs stay
    as expenses ("Loan / EMI"), no longer linked. Interest-only principal transfers turn
    back into expenses."""
    loan = _get(db, account_id)
    emi_cat = category_id(db, EMI_CATEGORY)
    payee = None
    for t in db.scalars(select(Transaction).where(Transaction.loan_id == loan.id)).unique():
        if t.loan_part in ("disbursal", "charges"):
            db.delete(t)
            continue
        if t.loan_part == "principal":
            payee = payee or find_or_create_counterparty(
                db, f"{loan.lender or loan.account.name} EMI", AccountType.expense
            )
            t.type, t.destination_id, t.category_id = TransactionType.withdrawal.value, payee.id, emi_cat
        t.loan_id = t.loan_part = t.loan_n = None
    db.flush()
    used = db.scalar(
        select(func.count(Transaction.id)).where(
            or_(Transaction.source_id == account_id, Transaction.destination_id == account_id)
        )
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{used} other transaction(s) use this loan's account — change or delete them first.",
        )
    a = loan.account
    db.delete(loan)
    db.flush()
    db.delete(a)
    db.commit()
