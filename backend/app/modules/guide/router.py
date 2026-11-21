from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ..auth.security import current_user
from ..savings.service import bad
from .schemas import GuideMark, GuideOut
from .service import STEPS, guide, mark

router = APIRouter(prefix="/guide", tags=["guide"], dependencies=[Depends(current_user)])


@router.get("", response_model=GuideOut)
def read_guide(db: Session = Depends(get_db)) -> GuideOut:
    """The getting-started checklist, worked out from what's in MoneyMap."""
    return guide(db)


@router.post("", response_model=GuideOut)
def update_guide(body: GuideMark, db: Session = Depends(get_db)) -> GuideOut:
    """Tick, skip or undo a step; hide or show the whole guide."""
    if body.action in ("check", "skip", "undo") and body.step not in {s[0] for s in STEPS}:
        raise bad("Unknown step.")
    return mark(db, body.step or "", body.action)
