from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.money import fmt_inr
from ...db import get_db
from ..accounts.models import BALANCE_TYPES, Account
from ..accounts.service import account_out, account_stats
from ..auth.security import current_user
from .models import PiggyBank, PiggyEvent
from .schemas import PiggyEventIn, PiggyEventOut, PiggyIn, PiggyOut, PiggyPatch

router = APIRouter(prefix="/piggy-banks", tags=["piggy banks"], dependencies=[Depends(current_user)])


def _saved_map(db: Session) -> dict[int, int]:
    """piggy bank id -> amount currently saved in it."""
    return {
        pid: int(total)
        for pid, total in db.execute(
            select(PiggyEvent.piggy_id, func.sum(PiggyEvent.amount)).group_by(PiggyEvent.piggy_id)
        )
    }


def _account_balance(db: Session, account: Account) -> int:
    return account_out(account, account_stats(db, [account.id]).get(account.id)).balance


def _set_aside_on(db: Session, account_id: int, saved: dict[int, int]) -> int:
    ids = db.scalars(select(PiggyBank.id).where(PiggyBank.account_id == account_id))
    return sum(saved.get(i, 0) for i in ids)


def monthly_needed(target_amount: int, saved: int, target_date: date | None, today: date | None = None) -> int | None:
    """Amount to set aside each month (rounded up) to reach the target by its date.
    None without a target date or when the target is reached; the whole rest when the date has come."""
    if target_date is None or saved >= target_amount:
        return None
    today = today or date.today()
    months = (target_date.year - today.year) * 12 + target_date.month - today.month
    remaining = target_amount - saved
    return remaining if months <= 0 else -(-remaining // months)


def piggy_out(db: Session, p: PiggyBank, saved: dict[int, int]) -> PiggyOut:
    out = PiggyOut.model_validate(p)
    out.saved = saved.get(p.id, 0)
    out.account_balance = _account_balance(db, p.account)
    out.account_available = out.account_balance - _set_aside_on(db, p.account_id, saved)
    out.monthly_needed = monthly_needed(p.target_amount, out.saved, p.target_date)
    return out


def _get(db: Session, pid: int) -> PiggyBank:
    p = db.get(PiggyBank, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Piggy bank not found")
    return p


def _check_account(db: Session, account_id: int) -> Account:
    a = db.get(Account, account_id)
    if a is None or a.type not in BALANCE_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a bank or cash account for the piggy bank")
    return a


@router.get("", response_model=list[PiggyOut])
def list_piggies(db: Session = Depends(get_db)) -> list[PiggyOut]:
    """Active piggy banks first, each with what's saved and what the account has left."""
    saved = _saved_map(db)
    q = select(PiggyBank).order_by(PiggyBank.active.desc(), func.lower(PiggyBank.name))
    return [piggy_out(db, p, saved) for p in db.scalars(q)]


@router.post("", response_model=PiggyOut, status_code=201)
def create_piggy(body: PiggyIn, db: Session = Depends(get_db)) -> PiggyOut:
    _check_account(db, body.account_id)
    data = body.model_dump()
    data["notes"] = (body.notes or "").strip() or None
    p = PiggyBank(**data)
    db.add(p)
    db.commit()
    db.refresh(p)
    return piggy_out(db, p, _saved_map(db))


@router.patch("/{pid}", response_model=PiggyOut)
def update_piggy(pid: int, body: PiggyPatch, db: Session = Depends(get_db)) -> PiggyOut:
    p = _get(db, pid)
    data = body.model_dump(exclude_unset=True)
    if data.get("account_id") is not None and data["account_id"] != p.account_id:
        _check_account(db, data["account_id"])
        saved = _saved_map(db).get(p.id, 0)
        if saved:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Take the saved money out before moving this piggy bank to another account",
            )
    for k, v in data.items():
        if k == "name" and v is not None:
            v = v.strip()
            if not v:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")
        if k == "notes":
            v = (v or "").strip() or None
        if k in ("target_date", "notes") or v is not None:
            setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return piggy_out(db, p, _saved_map(db))


@router.delete("/{pid}", status_code=204)
def delete_piggy(pid: int, db: Session = Depends(get_db)) -> None:
    """The money stays in the account; it is just no longer set aside."""
    db.delete(_get(db, pid))
    db.commit()


@router.get("/{pid}/events", response_model=list[PiggyEventOut])
def list_events(pid: int, db: Session = Depends(get_db)) -> list[PiggyEventOut]:
    _get(db, pid)
    q = select(PiggyEvent).where(PiggyEvent.piggy_id == pid).order_by(PiggyEvent.date.desc(), PiggyEvent.id.desc())
    return [PiggyEventOut.model_validate(e) for e in db.scalars(q)]


@router.post("/{pid}/events", response_model=PiggyOut, status_code=201)
def add_event(pid: int, body: PiggyEventIn, db: Session = Depends(get_db)) -> PiggyOut:
    """Set money aside (+amount) or take it out (−amount). The money stays in the
    linked account; you can't set aside more than it has left after other piggy banks."""
    p = _get(db, pid)
    if body.amount == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Amount can't be zero")
    saved = _saved_map(db)
    current = saved.get(p.id, 0)
    if body.amount < 0 and -body.amount > current:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "You can't take out more than is saved")
    if body.amount > 0:
        available = _account_balance(db, p.account) - _set_aside_on(db, p.account_id, saved)
        if body.amount > available:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{p.account.name} only has {fmt_inr(max(available, 0))} not already set aside",
            )
    note = (body.note or "").strip() or None
    db.add(PiggyEvent(piggy_id=p.id, date=body.date or date.today(), amount=body.amount, note=note))
    db.commit()
    return piggy_out(db, p, _saved_map(db))
