"""Loan statements: read a lender's PDF (Statement of Account and / or repayment schedule),
pre-fill a new loan, or list what differs from a loan you already have.

Nothing is saved here: the page applies what you tick through the usual loan endpoints
(add loan, edit, rate change, part-payment)."""

import base64
import binascii
import hashlib
import re
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ..accounts.models import Account
from ..auth.security import current_user
from ..gmail.fetch import attachments_dir, provider_names
from ..gmail.models import GmailAttachment
from ..statements.router import (
    LOAN_PASSWORD_KEY,
    MAX_UPLOAD,
    _sender_key,
    password_just_used,
    unlock_pdf,
    uploads_dir,
)
from ..transactions.models import Transaction, TransactionType
from .actions import BANK_TYPES, ROUNDING
from .models import Loan
from .schemas import LoanStatementDiff, LoanStatementEvent, LoanStatementIn, LoanStatementMatch, LoanStatementOut
from .service import loan_out, supports_changes
from .statement import Found, LoanStatement, is_loan_statement, lender_of, parse_loan_statement

router = APIRouter(prefix="/loans/statement", tags=["loans"], dependencies=[Depends(current_user)])

EXTRA_LENDERS = ["Bajaj Finance", "Bajaj Finserv", "Tata Capital", "LIC Housing Finance", "Mahindra Finance",
                 "Hero FinCorp", "TVS Credit", "Cholamandalam", "Shriram Finance", "Muthoot Finance",
                 "PNB Housing", "Aditya Birla Capital", "L&T Finance", "Poonawalla Fincorp", "HDB Financial",
                 "Home First Finance", "Aavas Financiers", "Credila", "Avanse"]  # fmt: skip
FIELDS = ("loan_number", "lender", "kind", "method", "principal", "rate", "rate_now", "tenure", "emi",
          "first_emi_date", "disbursed_date", "first_interest", "last_emi_date", "outstanding", "emis_paid",
          "emis_left", "statement_date")  # fmt: skip


def _bad(msg: str, code: str = "invalid") -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": code, "message": msg})


def _lenders() -> list[str]:
    names = [n for k, n in provider_names().items() if k not in ("cams", "kfintech")]
    return sorted({*names, *EXTRA_LENDERS}, key=len, reverse=True)


def _file(db: Session, body: LoanStatementIn) -> tuple[Path, str, str, str | None, dict]:
    """(path, filename, password key, sha, source) for the PDF to read."""
    if body.attachment_id is not None:
        att = db.get(GmailAttachment, body.attachment_id)
        if att is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
        path = (attachments_dir() / att.path).resolve()
        return path, att.filename, _sender_key(att), att.sha256, {"attachment_id": att.id}
    if body.content_b64:
        try:
            data = base64.b64decode(body.content_b64, validate=True)
        except (binascii.Error, ValueError):
            raise _bad("The file couldn't be read. Try choosing it again.", "bad_file") from None
        if len(data) > MAX_UPLOAD:
            raise _bad("That file is too big (over 15 MB).", "too_big")
        if not data.startswith(b"%PDF"):
            raise _bad("Only PDF statements can be read.", "not_pdf")
        sha = hashlib.sha256(data).hexdigest()
        path = uploads_dir() / f"{sha[:16]}.pdf"
        if not path.exists():
            path.write_bytes(data)
        name = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(body.filename or "loan.pdf").name).strip() or "loan.pdf"
        return path, name, LOAN_PASSWORD_KEY, sha, {"file_ref": sha}
    if body.file_ref:
        path = uploads_dir() / f"{body.file_ref[:16]}.pdf"
        if not path.exists():
            raise _bad("That PDF is no longer on the server. Upload it again.", "missing_pdf")
        name = body.filename or "loan statement.pdf"
        return path, name, LOAN_PASSWORD_KEY, body.file_ref, {"file_ref": body.file_ref}
    raise _bad("Choose the loan statement PDF.", "no_file")


@router.post("/read", response_model=LoanStatementOut)
def read_statement(body: LoanStatementIn, db: Session = Depends(get_db)) -> LoanStatementOut:
    path, filename, key, sha, source = _file(db, body)
    password = body.password or password_just_used(sha)
    candidates, _ = unlock_pdf(db, path, filename, key, password, body.remember_password)
    db.commit()  # a password to remember
    lenders = _lenders()
    best: LoanStatement | None = None
    for _, text in candidates:
        st = parse_loan_statement(text, lenders)
        if best is None or st.score() > best.score():
            best = st
    texts = [t for _, t in candidates]
    if best is not None and "lender" not in best.values:  # one way of reading the PDF may keep the name whole
        who = next((w for t in texts if (w := lender_of(t, lenders))), None)
        if who:
            best.values["lender"] = who
            best.from_labels.add("lender")
    if best is None or (not any(is_loan_statement(t) for t in texts) and best.score() < 9):
        raise _bad(
            "This doesn't look like a loan statement or repayment schedule — no loan details were found in it.",
            "not_loan",
        )
    loan = _target(db, body.account_id, best)
    out = LoanStatementOut(
        filename=filename,
        file_ref=source.get("file_ref"),
        attachment_id=source.get("attachment_id"),
        fields={k: _field(best, k) for k in FIELDS if best.get(k) is not None},
        schedule_rows=len(best.schedule),
        check=best.check,
        events=[_event(db, f, loan) for f in best.found],
    )
    if loan is not None:
        out.match = _compare(db, loan, best, out.events)
    return out


def _field(st: LoanStatement, k: str) -> dict:
    v = st.get(k)
    if k in ("rate", "rate_now"):
        v = int(v) / 100  # type: ignore[arg-type]
    elif isinstance(v, date):
        v = v.isoformat()
    return {"value": v, "source": "statement" if k in st.from_labels else "worked_out"}


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _target(db: Session, account_id: int | None, st: LoanStatement) -> Loan | None:
    """The loan this statement is for: the one you opened it from, or the same loan number."""
    if account_id is not None:
        loan = db.scalar(select(Loan).where(Loan.account_id == account_id))
        if loan is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Loan not found")
        return loan
    num = _digits(str(st.get("loan_number") or ""))
    if len(num) < 4:
        return None
    for loan in db.scalars(select(Loan)):
        mine = _digits(loan.loan_number)
        if len(mine) >= 4 and (num.endswith(mine) or mine.endswith(num)):
            return loan
    return None


def _event(db: Session, f: Found, loan: Loan | None) -> LoanStatementEvent:
    recorded = False
    if loan is not None:
        for e in loan.events:
            if e.kind != f.kind or abs((e.date - f.date).days) > 45:
                continue
            if f.kind == "prepay" and e.amount is not None and abs(e.amount - (f.amount or 0)) <= 100 * ROUNDING:
                recorded = True
            if f.kind == "rate" and e.rate_bp is not None and abs(e.rate_bp - (f.rate_bp or 0)) <= 5:
                recorded = True
    txn = _payment_for(db, f, loan) if f.kind == "prepay" and not recorded else None
    if txn is not None and loan is not None and txn.loan_id == loan.id:
        recorded, txn = True, None
    return LoanStatementEvent(
        kind=f.kind,
        date=f.date,
        amount=f.amount,
        rate=f.rate_bp / 100 if f.rate_bp is not None else None,
        mode=f.mode,
        source=f.source,
        text=f.text or None,
        already_recorded=recorded,
        transaction_id=txn.id if txn else None,
        transaction=f"{txn.date:%d %b %Y} · {txn.description} · from {txn.source.name}" if txn else None,
    )


def _payment_for(db: Session, f: Found, loan: Loan | None) -> Transaction | None:
    """The bank payment that is this part-payment: same amount (₹1), within a week, from a bank
    or cash account, not already a different loan's."""
    if not f.amount:
        return None
    q = (
        select(Transaction)
        .join(Account, Transaction.source_id == Account.id)
        .where(
            Transaction.type.in_([TransactionType.withdrawal.value, TransactionType.transfer.value]),
            Account.type.in_(BANK_TYPES),
            Transaction.amount.between(f.amount - ROUNDING, f.amount + ROUNDING),
            Transaction.date.between(f.date - timedelta(days=7), f.date + timedelta(days=7)),
        )
        .order_by(Transaction.date)
    )
    for t in db.scalars(q).unique():
        if t.loan_id is None and t.type == TransactionType.withdrawal.value:
            return t
        if loan is not None and t.loan_id == loan.id:
            return t
    return None


def _d(d: date | None) -> str:
    return f"{d:%d %b %Y}" if d else "—"


def _compare(db: Session, loan: Loan, st: LoanStatement, events: list[LoanStatementEvent]) -> LoanStatementMatch:
    """What the statement says that the loan doesn't: one tick box each (terms go in one edit)."""
    cur = loan_out(db, loan)
    v = st.values
    diffs: list[LoanStatementDiff] = []

    def add(field: str, label: str, kind: str, now, theirs, patch: dict | None, note: str | None = None) -> None:
        """`kind` says how the page shows the values: money (paise, hidden when amounts are), date, rate, text."""
        if isinstance(now, date):
            now = now.isoformat()
        if isinstance(theirs, date):
            theirs = theirs.isoformat()
        diffs.append(
            LoanStatementDiff(
                field=field, label=label, kind=kind, current=now, statement=theirs, patch=patch, note=note
            )
        )

    if v.get("loan_number") and not _digits(loan.loan_number):
        add(
            "loan_number",
            "Loan number",
            "text",
            None,
            str(v["loan_number"]),
            {"loan_number": str(v["loan_number"])[-32:]},
        )
    if v.get("lender") and not loan.lender:
        add("lender", "Lender", "text", None, str(v["lender"]), {"lender": v["lender"]})
    if v.get("kind") and loan.kind in ("personal", "other") and v["kind"] != loan.kind:
        add("kind", "Type", "kind", loan.kind, str(v["kind"]), {"kind": v["kind"]})
    # terms (the EMI at the start: the schedule's first row, or the statement's EMI when nothing changed)
    start_emi = st.schedule[0].emi if st.schedule and st.schedule[0].n == 1 else None
    if start_emi is None and v.get("emi") and not st.found and not loan.events:
        start_emi = int(v["emi"])  # type: ignore[arg-type]
    terms: dict = {}
    p = v.get("principal")
    if p and loan.principal != p and abs((loan.principal or 0) - int(p)) > ROUNDING:  # type: ignore[arg-type]
        add("principal", "Loan amount", "money", loan.principal, int(p), {"principal": p})  # type: ignore[arg-type]
        terms["principal"] = p
    # the starting rate: the schedule's; a statement's rate only when nothing changed (else it's today's)
    start_rate = v.get("rate_start") or (v.get("rate") if not (st.found or loan.events) else None)
    if start_rate is not None and loan.method != "emi_only" and loan.rate_bp != start_rate:
        add("rate", "Interest rate at the start", "rate", (loan.rate_bp or 0) / 100, int(start_rate) / 100,
            {"rate": int(start_rate) / 100})  # type: ignore[arg-type]  # fmt: skip
        terms["rate"] = int(start_rate) / 100  # type: ignore[arg-type]
    if loan.method == "emi_only" and start_rate is not None and v.get("method") in ("reducing", "flat"):
        # "EMI only" can't split an EMI; the statement has the rate (and a schedule's split) to do it
        patch = {"method": v["method"], "rate": int(start_rate) / 100, "emi": start_emi or loan.emi}  # type: ignore[arg-type]
        if v["method"] == "reducing" and v.get("first_interest"):
            patch["first_interest"] = v["first_interest"]
            if v["first_interest"] != "month" and v.get("disbursed_date"):
                patch["disbursed_date"] = v["disbursed_date"].isoformat()  # type: ignore[union-attr]
        add("method", "How each EMI is split", "method", loan.method, str(v["method"]), patch,
            f"At {int(start_rate) / 100:g}% a year — each EMI's principal and interest as the lender works them out.")  # type: ignore[arg-type]  # fmt: skip
    if v.get("tenure") and v["tenure"] != loan.tenure and not (st.found or loan.events):
        add("tenure", "Number of EMIs", "count", loan.tenure, v["tenure"], {"tenure": v["tenure"]})
        terms["tenure"] = v["tenure"]
    if v.get("first_emi_date") and v["first_emi_date"] != loan.first_emi_date:
        add("first_emi_date", "First EMI", "date", loan.first_emi_date, v["first_emi_date"],  # type: ignore[arg-type]
            {"first_emi_date": v["first_emi_date"].isoformat()})  # type: ignore[union-attr]  # fmt: skip
    if v.get("disbursed_date") and v["disbursed_date"] != loan.disbursed_date:
        add("disbursed_date", "Taken on", "date", loan.disbursed_date, v["disbursed_date"],  # type: ignore[arg-type]
            {"disbursed_date": v["disbursed_date"].isoformat()})  # type: ignore[union-attr]  # fmt: skip
    if v.get("first_interest") and v["first_interest"] != loan.first_interest and loan.method == "reducing":
        patch = {"first_interest": v["first_interest"]}
        if v["first_interest"] != "month" and not loan.disbursed_date and v.get("disbursed_date"):
            patch["disbursed_date"] = v["disbursed_date"].isoformat()  # type: ignore[union-attr]
        add("first_interest", "Interest in the first EMI", "first_interest", loan.first_interest,
            str(v["first_interest"]), patch)  # fmt: skip
    if start_emi and abs(start_emi - loan.emi) > ROUNDING:
        add("emi", "EMI at the start", "money", loan.emi, start_emi, {"emi": start_emi})
    if terms and start_emi:
        for d in diffs:  # a new amount / rate / tenure would work the EMI out again: keep the lender's
            if d.patch and d.field in terms:
                d.patch["emi"] = start_emi
    # today's rate: a change from the statement date, unless a found change already says so
    now_rate = v.get("rate_now") or (v.get("rate") if "rate" in st.from_labels else None)
    if (
        now_rate is not None
        and cur.current_rate is not None
        and abs(cur.current_rate * 100 - int(now_rate)) > 1  # type: ignore[arg-type]
        and supports_changes(loan)
        and not any(e.kind == "rate" and e.rate is not None and abs(e.rate * 100 - int(now_rate)) <= 5 for e in events)  # type: ignore[arg-type]
        and "rate" not in terms
    ):
        on = v.get("statement_date") or date.today()
        events.append(
            LoanStatementEvent(
                kind="rate",
                date=on,
                rate=int(now_rate) / 100,
                mode="reduce_tenure",
                source="statement",  # type: ignore[arg-type]
                text=f"Rate on the statement: {int(now_rate) / 100:g}% (MoneyMap has {cur.current_rate:g}%). "  # type: ignore[arg-type]
                "The date it changed isn't on the statement — set it if you know it.",
                already_recorded=False,
                date_unknown=True,
            )  # fmt: skip
        )
    paid = v.get("emis_paid")
    if paid is not None and int(paid) > cur.paid_count:  # type: ignore[arg-type]
        add("emis_paid", "EMIs paid", "count", cur.paid_count, paid, {"paid_before": int(paid)})  # type: ignore[arg-type]
    elif paid is not None and int(paid) < cur.paid_count:  # type: ignore[arg-type]
        add("emis_paid", "EMIs paid", "count", cur.paid_count, paid, None,
            "MoneyMap counts more EMIs as paid than the lender — check the EMIs on the loan page.")  # fmt: skip
    out = v.get("outstanding")
    if out is not None and abs(cur.outstanding - int(out)) > 100 * ROUNDING:  # type: ignore[arg-type]
        on = v.get("statement_date")
        add("outstanding", f"Left to pay{' on ' + _d(on) if on else ''}", "money", cur.outstanding, int(out), None,  # type: ignore[arg-type]
            "Worked out from the schedule — it follows once the changes above are applied.")  # fmt: skip
    return LoanStatementMatch(account_id=loan.account_id, name=loan.account.name, differences=diffs)
