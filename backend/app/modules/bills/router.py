from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...db import get_db
from ..auth.security import current_user
from .models import Bill
from .schemas import BillIn, BillOut
from .service import all_bills, bill_out, payments

router = APIRouter(prefix="/bills", tags=["bills"], dependencies=[Depends(current_user)])


def _get(db: Session, bid: int) -> Bill:
    b = db.get(Bill, bid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    return b


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A bill with that name already exists") from None


def _clean(body: BillIn) -> dict:
    data = body.model_dump()
    data["match"] = (body.match or "").strip() or None
    data["notes"] = (body.notes or "").strip() or None
    return data


@router.get("", response_model=list[BillOut])
def list_bills(db: Session = Depends(get_db)) -> list[BillOut]:
    """Active bills first, each with its next due date and status."""
    return all_bills(db)


@router.post("", response_model=BillOut, status_code=201)
def create_bill(body: BillIn, db: Session = Depends(get_db)) -> BillOut:
    b = Bill(**_clean(body))
    db.add(b)
    _commit(db)
    db.refresh(b)
    return bill_out(b, [])


@router.get("/{bid}", response_model=BillOut)
def get_bill(bid: int, db: Session = Depends(get_db)) -> BillOut:
    b = _get(db, bid)
    return bill_out(b, payments(db, [b.id]).get(b.id, []))


@router.put("/{bid}", response_model=BillOut)
def update_bill(bid: int, body: BillIn, db: Session = Depends(get_db)) -> BillOut:
    b = _get(db, bid)
    for k, v in _clean(body).items():
        setattr(b, k, v)
    _commit(db)
    return bill_out(b, payments(db, [b.id]).get(b.id, []))


@router.delete("/{bid}", status_code=204)
def delete_bill(bid: int, db: Session = Depends(get_db)) -> None:
    """Linked expenses stay, no longer linked to the bill."""
    db.delete(_get(db, bid))
    db.commit()
