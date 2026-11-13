from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...db import get_db
from ..auth.security import current_user
from ..piggybanks.models import PiggyBank
from ..piggybanks.router import check_account, saved_map
from .models import EmergencyFund
from .schemas import EmergencyIn, EmergencyOut
from .service import compute, get_config

router = APIRouter(prefix="/emergency-fund", tags=["emergency fund"], dependencies=[Depends(current_user)])

PIGGY_NAME = "Emergency fund"


@router.get("", response_model=EmergencyOut)
def get_emergency_fund(db: Session = Depends(get_db)) -> EmergencyOut:
    """Target (typical month of essential spending × months of cover), saved, months covered, status."""
    out = compute(db)
    db.commit()  # the piggy bank's target follows the calculation
    return out


@router.put("", response_model=EmergencyOut)
def set_up_emergency_fund(body: EmergencyIn, db: Session = Depends(get_db)) -> EmergencyOut:
    """Set up the fund (creates its piggy bank in the chosen account) or change its settings."""
    check_account(db, body.account_id)
    cfg = get_config(db)
    if cfg is None:
        cfg = EmergencyFund()
        db.add(cfg)
    piggy = db.get(PiggyBank, cfg.piggy_id) if cfg.piggy_id else None
    if piggy is None:
        piggy = PiggyBank(name=PIGGY_NAME, account_id=body.account_id, target_amount=0, active=True)
        db.add(piggy)
        db.flush()
        cfg.piggy_id = piggy.id
    elif piggy.account_id != body.account_id:
        if saved_map(db).get(piggy.id, 0):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Take the saved money out before moving the emergency fund to another account",
            )
        piggy.account_id = body.account_id
    cfg.months_cover = body.months_cover
    cfg.average_months = body.average_months
    cfg.monthly_override = body.monthly_override
    db.flush()
    db.expire(piggy, ["account"])
    out = compute(db)
    db.commit()
    return out


@router.delete("", status_code=204)
def switch_off_emergency_fund(db: Session = Depends(get_db)) -> None:
    """Remove the fund and its piggy bank. The money stays in the account, just no longer set aside."""
    cfg = get_config(db)
    if cfg is None:
        return
    if cfg.piggy_id and (piggy := db.get(PiggyBank, cfg.piggy_id)) is not None:
        db.delete(piggy)
    db.delete(cfg)
    db.commit()
