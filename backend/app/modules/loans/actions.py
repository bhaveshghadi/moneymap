"""Recording things on a loan: past EMIs, part-payments, and re-recording EMIs when
the way the loan counts as spending changes. Shared by the loans API and statement import."""

import re
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..accounts.models import BALANCE_TYPES, Account, AccountType
from ..accounts.service import find_or_create_counterparty
from ..transactions.models import Transaction, TransactionType
from ..transactions.schemas import TransactionIn
from ..transactions.service import apply_body
from .models import Loan, LoanEvent
from .service import EMI_CATEGORY, FEE_CATEGORY, INTEREST_CATEGORY, category_id, loan_out, paid_numbers, schedule

ROUNDING = 100  # an EMI matches within ₹1
NEAR_DAYS = 20  # a payment belongs to the EMI dated within this many days
BANK_TYPES = tuple(str(t) for t in BALANCE_TYPES)


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def _new_txn(db: Session, body: dict, loan: Loan, part: str, n: int | None = None) -> Transaction:
    t = Transaction()
    apply_body(db, t, TransactionIn(**{"auto_match_bill": False, **body}), is_new=True)
    t.loan_id, t.loan_part, t.loan_n = loan.id, part, n
    db.add(t)
    db.flush()
    return t


def link_payments(db: Session, loan: Loan, txns: list[Transaction]) -> int:
    """Past EMI payments (expenses) become this loan's EMIs: each is matched to the EMI
    dated nearest to it (or the next unpaid one). whole_emi: the expense stays, now in
    "Loan / EMI" and linked; interest_only: it becomes the principal transfer bank ->
    loan plus an interest expense, split as in the schedule."""
    rows = {r.n: r for r in schedule(loan)}
    linked = set(
        db.scalars(select(Transaction.loan_n).where(Transaction.loan_id == loan.id, Transaction.loan_n.is_not(None)))
    )
    emi_cat, int_cat = category_id(db, EMI_CATEGORY), category_id(db, INTEREST_CATEGORY)
    count = 0
    for t in sorted(txns, key=lambda x: (x.date, x.id)):
        if t.type != TransactionType.withdrawal.value or t.source.type not in BANK_TYPES or t.loan_id is not None:
            raise _bad(f"“{t.description}” on {t.date:%d %b %Y} is not an unlinked expense from a bank account.")
        free = [r for r in rows.values() if r.n not in linked]
        emis = {loan.emi, *(r.emi for r in free)}  # the EMI changes after part-payments / rate changes
        if all(abs(t.amount - e) > ROUNDING for e in emis):
            raise _bad(
                f"“{t.description}” on {t.date:%d %b %Y} isn't an EMI amount — record it as a part-payment instead."
            )
        near = [r for r in free if abs((r.date - t.date).days) <= NEAR_DAYS]
        paid = paid_numbers(db, loan) | linked
        row = (
            min(near, key=lambda r: abs((r.date - t.date).days))
            if near
            else next((r for r in free if r.n not in paid), None)
        )
        if row is None:
            raise _bad("All EMIs of this loan are already paid.")
        linked.add(row.n)
        if loan.count_mode == "whole_emi":
            t.loan_id, t.loan_part, t.loan_n = loan.id, "emi", row.n
            t.category_id = emi_cat
        else:
            interest = min(row.interest, t.amount)
            source_id = t.source_id
            t.type = TransactionType.transfer.value
            t.destination_id = loan.account_id
            t.amount = t.amount - interest
            t.category_id = t.budget_id = t.bill_id = None
            t.loan_id, t.loan_part, t.loan_n = loan.id, "principal", row.n
            if interest > 0:
                payee = find_or_create_counterparty(
                    db, f"{loan.lender or loan.account.name} interest", AccountType.expense
                )
                it = Transaction(
                    type=TransactionType.withdrawal.value,
                    date=t.date,
                    amount=interest,
                    description=f"Interest · EMI {row.n}/{loan.tenure} · {loan.account.name}",
                    source_id=source_id,
                    destination_id=payee.id,
                    category_id=int_cat,
                    loan_id=loan.id,
                    loan_part="interest",
                    loan_n=row.n,
                )
                db.add(it)
        count += 1
    db.flush()
    return count


def record_prepay(
    db: Session,
    loan: Loan,
    on: date,
    amount: int,
    mode: str,
    from_account: Account | None = None,
    existing: Transaction | None = None,
    fee: int | None = None,
    payment: bool = True,
) -> LoanEvent:
    """A part-payment: what's left drops by `amount`; then either the EMI stays and the
    loan ends sooner (reduce_tenure) or the end date stays and the EMI drops (reduce_emi).
    whole_emi loans count it as spending ("Loan / EMI"); interest_only loans as a
    transfer bank -> loan. `existing`: an expense that already is this payment.
    `payment=False`: only the change to the loan (a part-payment from before you tracked it)."""
    who = loan.lender or loan.account.name
    if existing is not None:
        if existing.type != TransactionType.withdrawal.value or existing.source.type not in BANK_TYPES:
            raise _bad("That transaction isn't an expense from a bank or cash account.")
        if existing.loan_id is not None:
            raise _bad("That transaction is already linked to a loan.")
        t = existing
        if loan.count_mode == "interest_only":
            t.type = TransactionType.transfer.value
            t.destination_id = loan.account_id
            t.category_id = t.budget_id = t.bill_id = None
        else:
            t.category_id = category_id(db, EMI_CATEGORY)
        t.loan_id, t.loan_part, t.loan_n = loan.id, "prepay", None
        amount, on, created = t.amount, t.date, False
    elif not payment:
        t, created = None, False
    else:
        if from_account is None or from_account.type not in BANK_TYPES:
            raise _bad("Choose the bank or cash account the part-payment was paid from.")
        body = {"date": on, "amount": amount, "source_id": from_account.id}
        if loan.count_mode == "interest_only":
            body |= {
                "type": "transfer",
                "description": f"Part-payment · {loan.account.name}",
                "destination_id": loan.account_id,
            }
        else:
            body |= {
                "type": "withdrawal",
                "description": f"Part-payment · {loan.account.name}",
                "destination_name": f"{who} EMI",
                "category_id": category_id(db, EMI_CATEGORY),
            }
        t = _new_txn(db, body, loan, "prepay")
        created = True
    ev = LoanEvent(kind="prepay", date=on, mode=mode, amount=amount, txn_id=t.id if t else None, txn_created=created)
    if fee and (from_account or t):
        src = from_account or t.source  # type: ignore[union-attr]
        f = _new_txn(
            db,
            {
                "type": "withdrawal",
                "date": on,
                "amount": fee,
                "description": f"Part-payment charge · {loan.account.name}",
                "source_id": src.id,
                "destination_name": who,
                "category_id": category_id(db, FEE_CATEGORY),
            },
            loan,
            "fee",
        )
        ev.fee_txn_id = f.id
    loan.events.append(ev)
    db.flush()
    if loan_out(db, loan).outstanding == 0 and loan.closed_on is None:
        loan.closed_on = on  # paid off
    return ev


def remove_event(db: Session, loan: Loan, ev: LoanEvent) -> None:
    """Undo a part-payment / rate change. A payment made here is deleted; one that was an
    existing expense goes back to being a plain expense."""
    if ev.kind == "prepay" and ev.txn_id:
        t = db.get(Transaction, ev.txn_id)
        if t is not None and ev.txn_created:
            db.delete(t)
        elif t is not None:
            if t.type == TransactionType.transfer.value:
                payee = find_or_create_counterparty(db, f"{loan.lender or loan.account.name} EMI", AccountType.expense)
                t.type, t.destination_id = TransactionType.withdrawal.value, payee.id
                t.category_id = category_id(db, EMI_CATEGORY)
            t.loan_id = t.loan_part = None
    if ev.fee_txn_id and (f := db.get(Transaction, ev.fee_txn_id)) is not None:
        db.delete(f)
    if ev.kind == "prepay" and loan.closed_on == ev.date:
        loan.closed_on = None
    loan.events.remove(ev)
    db.flush()


def change_count_mode(db: Session, loan: Loan, new_mode: str) -> None:
    """Re-record the linked EMIs the other way: whole EMI expenses are split into a
    principal transfer + interest expense, or the two are merged back into one expense."""
    if new_mode == loan.count_mode:
        return
    rows = {r.n: r for r in schedule(loan)}
    emi_cat, int_cat = category_id(db, EMI_CATEGORY), category_id(db, INTEREST_CATEGORY)
    linked = list(db.scalars(select(Transaction).where(Transaction.loan_id == loan.id)).unique())
    who = loan.lender or loan.account.name
    if new_mode == "interest_only":
        if loan.method == "emi_only" and not loan.principal:
            raise _bad("To count only the interest, enter the loan amount so the EMI can be split.")
        for t in linked:
            if t.loan_part == "emi" and t.loan_n in rows:
                row = rows[t.loan_n]
                interest = min(row.interest, t.amount)
                src = t.source_id
                t.type, t.destination_id, t.amount = (
                    TransactionType.transfer.value,
                    loan.account_id,
                    t.amount - interest,
                )
                t.category_id = t.budget_id = t.bill_id = None
                t.loan_part = "principal"
                if interest:
                    payee = find_or_create_counterparty(db, f"{who} interest", AccountType.expense)
                    db.add(
                        Transaction(
                            type=TransactionType.withdrawal.value,
                            date=t.date,
                            amount=interest,
                            description=f"Interest · EMI {t.loan_n}/{loan.tenure} · {loan.account.name}",
                            source_id=src,
                            destination_id=payee.id,
                            category_id=int_cat,
                            loan_id=loan.id,
                            loan_part="interest",
                            loan_n=t.loan_n,
                        )
                    )
            elif t.loan_part == "prepay" and t.type == TransactionType.withdrawal.value:
                t.type, t.destination_id, t.category_id = TransactionType.transfer.value, loan.account_id, None
    else:
        payee = find_or_create_counterparty(db, f"{who} EMI", AccountType.expense)
        interest = {t.loan_n: t for t in linked if t.loan_part == "interest"}
        for t in linked:
            if t.loan_part == "principal":
                it = interest.pop(t.loan_n, None)
                t.type, t.destination_id, t.category_id = TransactionType.withdrawal.value, payee.id, emi_cat
                t.loan_part = "emi"
                if it is not None:
                    t.amount += it.amount
                    db.delete(it)
            elif t.loan_part == "prepay" and t.type == TransactionType.transfer.value:
                t.type, t.destination_id, t.category_id = TransactionType.withdrawal.value, payee.id, emi_cat
        for it in interest.values():  # interest without its principal row: keep as one expense
            it.loan_part = "emi"
            it.category_id = emi_cat
    loan.count_mode = new_mode
    db.flush()


# ---------------------------------------------------------------- bank statements

LOAN_WORDS_RE = re.compile(r"\b(emi|loan|nach|ach|ecs|mandate|si)\b", re.I)


def match_loan(raw: str, amount: int, loans: list[tuple[Loan, int]]) -> tuple[Loan, str] | None:
    """A bank statement row (money out, `amount` > 0) that is a loan's EMI or a part-payment
    on it. `loans`: active loans with their current EMI. Matched by the loan number in the
    text, the lender's name with "loan / EMI", or the EMI amount with "EMI / NACH / ECS".
    Returns (loan, "emi" | "prepay")."""
    digits = re.sub(r"\D", " ", raw)
    text = raw.lower()
    loan_words = bool(LOAN_WORDS_RE.search(raw))
    for loan, emi in loans:
        num = re.sub(r"\D", "", loan.loan_number or "")[-4:]
        by_number = len(num) == 4 and re.search(rf"\d*{num}(?!\d)", digits) is not None
        lender = next(iter(re.findall(r"[a-z]{3,}", (loan.lender or "").lower())), None)
        by_lender = bool(lender) and lender in text and loan_words
        emi_like = abs(amount - emi) <= ROUNDING or abs(amount - loan.emi) <= ROUNDING
        if emi_like and (by_number or by_lender or loan_words):
            return loan, "emi"
        if (by_number or by_lender) and amount > emi:
            return loan, "prepay"
    return None
