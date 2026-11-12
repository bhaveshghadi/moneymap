from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...db import get_db
from ..auth.security import current_user
from ..transactions.models import Transaction
from .models import BALANCE_TYPES, Account, AccountType
from .schemas import AccountIn, AccountOut, AccountPatch
from .service import account_out, account_stats

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(current_user)])

COUNTERPARTY = (AccountType.expense, AccountType.revenue)


@router.get("", response_model=list[AccountOut])
def list_accounts(
    type: list[AccountType] | None = Query(default=None),
    include_inactive: bool = True,
    db: Session = Depends(get_db),
) -> list[AccountOut]:
    q = select(Account).order_by(Account.type, func.lower(Account.name))
    if type:
        q = q.where(Account.type.in_([t.value for t in type]))
    if not include_inactive:
        q = q.where(Account.active.is_(True))
    accounts = list(db.scalars(q))
    stats = account_stats(db, [a.id for a in accounts])
    return [account_out(a, stats.get(a.id)) for a in accounts]


def _get(db: Session, account_id: int) -> Account:
    a = db.get(Account, account_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return a


def _check_unique(db: Session, name: str, type_: str, exclude_id: int | None = None) -> None:
    q = select(Account.id).where(Account.type == type_, func.lower(Account.name) == name.lower())
    if exclude_id is not None:
        q = q.where(Account.id != exclude_id)
    if db.scalar(q) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A {type_} account named '{name}' already exists")


@router.post("", response_model=AccountOut, status_code=201)
def create_account(body: AccountIn, db: Session = Depends(get_db)) -> AccountOut:
    _check_unique(db, body.name, body.type)
    data = body.model_dump()
    if body.type in COUNTERPARTY:
        data["opening_balance"] = 0
        data["opening_date"] = None
    a = Account(**data)
    db.add(a)
    db.commit()
    return account_out(a, None)


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int, db: Session = Depends(get_db)) -> AccountOut:
    a = _get(db, account_id)
    return account_out(a, account_stats(db, [a.id]).get(a.id))


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountPatch, db: Session = Depends(get_db)) -> AccountOut:
    a = _get(db, account_id)
    data = body.model_dump(exclude_unset=True)
    new_type = data.pop("type", None) or a.type
    # Balances work the same way for bank and cash, so their transactions stay valid on a switch.
    if new_type != a.type and (a.type not in BALANCE_TYPES or new_type not in BALANCE_TYPES):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only Bank and Cash accounts can change type.")
    if data.get("name"):
        data["name"] = data["name"].strip()
    else:
        data.pop("name", None)
    if "name" in data or new_type != a.type:
        _check_unique(db, data.get("name", a.name), new_type, exclude_id=a.id)
    if new_type in COUNTERPARTY:
        data.pop("opening_balance", None)
        data.pop("opening_date", None)
    if "opening_balance" in data and data["opening_balance"] is None:
        data.pop("opening_balance")
    a.type = new_type
    for k, v in data.items():
        setattr(a, k, v)
    db.commit()
    return account_out(a, account_stats(db, [a.id]).get(a.id))


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db)) -> None:
    a = _get(db, account_id)
    used = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(or_(Transaction.source_id == a.id, Transaction.destination_id == a.id))
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This account has {used} transaction(s). Delete those first, or mark the account inactive.",
        )
    db.delete(a)
    db.commit()
