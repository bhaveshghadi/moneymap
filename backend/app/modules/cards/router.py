import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...db import get_db
from ..accounts.models import Account, AccountType
from ..auth.security import current_user
from ..categories.models import Category
from ..statements.review import is_card_payment_text
from ..transactions.models import Transaction, TransactionType
from .models import CardCycleRule, CreditCard
from .schemas import CardDetail, CardDue, CardIn, CardOut, CardPatch, Convertible, ConvertIn, ConvertOut, EmptyCategory
from .service import add_rule, all_cards, card_dues, card_out

router = APIRouter(prefix="/cards", tags=["cards"], dependencies=[Depends(current_user)])

FAR_PAST = date(2000, 1, 1)


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def _check_due(mode: str, value: int) -> None:
    if mode == "fixed_day" and value > 31:
        raise _bad("The due day must be between 1 and 31")


def _check_unique(db: Session, name: str, exclude_id: int | None = None) -> None:
    q = select(Account.id).where(
        Account.type == AccountType.credit_card.value, func.lower(Account.name) == name.lower()
    )
    if exclude_id is not None:
        q = q.where(Account.id != exclude_id)
    if db.scalar(q) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A card named '{name}' already exists")


def _get(db: Session, account_id: int) -> CreditCard:
    card = db.scalar(select(CreditCard).where(CreditCard.account_id == account_id))
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    return card


@router.get("", response_model=list[CardOut])
def list_cards(include_inactive: bool = True, db: Session = Depends(get_db)) -> list[CardOut]:
    return all_cards(db, include_inactive)


@router.get("/dues", response_model=list[CardDue])
def dues(days: int = 30, db: Session = Depends(get_db)) -> list[CardDue]:
    return card_dues(db, days)


def _card_category_ids(db: Session) -> list[int]:
    """Expense categories that are really card bill payments (e.g. "Credit Card Bill")."""
    return [
        c.id
        for c in db.scalars(select(Category).where(Category.kind == "expense"))
        if "card" in c.name.lower() and "fee" not in c.name.lower()
    ]


@router.get("/convertible", response_model=list[Convertible])
def convertible(db: Session = Depends(get_db)) -> list[Convertible]:
    """Expenses from a bank or cash account that look like card bill payments. They
    should be transfers to the card, so they don't count as spending twice."""
    card_cats = set(_card_category_ids(db))
    cards = list(
        db.scalars(select(Account).where(Account.type == AccountType.credit_card.value, Account.active.is_(True)))
    )
    q = (
        select(Transaction)
        .join(Account, Transaction.source_id == Account.id)
        .where(Transaction.type == TransactionType.withdrawal.value, Account.type.in_(("asset", "cash")))
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    )
    out = []
    for t in db.scalars(q).unique():
        text = f"{t.description} {t.destination.name}"
        if t.category_id not in card_cats and not is_card_payment_text(text):
            continue
        suggested, why = None, None
        digits = re.sub(r"\D", " ", text)
        for c in cards:
            num = (c.account_number or "")[-4:]
            if num and re.search(rf"(?<!\d){num}(?!\d)", digits):
                suggested, why = c.id, f"Card ending {num} is in the description"
                break
        if suggested is None and len(cards) == 1:
            suggested, why = cards[0].id, "Your only credit card"
        out.append(
            Convertible(
                transaction_id=t.id,
                date=t.date,
                amount=t.amount,
                description=t.description,
                paid_from=t.source.name,
                payee=t.destination.name,
                category=t.category.name if t.category else None,
                suggested_card_id=suggested,
                why=why,
            )
        )
    return out


@router.post("/convert", response_model=ConvertOut)
def convert(body: ConvertIn, db: Session = Depends(get_db)) -> ConvertOut:
    """Turn the chosen expenses into transfers bank -> card (same date, amount and
    description; category, budget and bill are cleared — transfers have none)."""
    converted = 0
    touched: set[int] = set()
    for item in body.items:
        t = db.get(Transaction, item.transaction_id)
        if t is None or t.type != TransactionType.withdrawal.value or t.source.type not in ("asset", "cash"):
            raise _bad(f"Transaction {item.transaction_id} is not an expense from a bank or cash account")
        card = db.get(Account, item.card_id)
        if card is None or card.type != AccountType.credit_card.value:
            raise _bad("Choose one of your credit cards")
        if t.category_id:
            touched.add(t.category_id)
        t.type = TransactionType.transfer.value
        t.destination_id = card.id
        t.category_id = None
        t.budget_id = None
        t.bill_id = None
        converted += 1
    db.flush()
    empty = []
    for cid in sorted(touched):
        left = db.scalar(select(func.count(Transaction.id)).where(Transaction.category_id == cid))
        cat = db.get(Category, cid)
        if not left and cat is not None and cid in _card_category_ids(db):
            empty.append(EmptyCategory(id=cat.id, name=cat.name))
    db.commit()
    return ConvertOut(converted=converted, empty_categories=empty)


@router.post("", response_model=CardDetail, status_code=201)
def create_card(body: CardIn, db: Session = Depends(get_db)) -> CardDetail:
    _check_due(body.due_mode, body.due_value)
    _check_unique(db, body.name)
    a = Account(
        name=body.name,
        type=AccountType.credit_card.value,
        account_number=body.last4,
        opening_balance=-body.opening_owed,
        opening_date=body.opening_date,
        active=body.active,
        notes=(body.notes or "").strip() or None,
    )
    db.add(a)
    db.flush()
    card = CreditCard(
        account_id=a.id,
        bank=(body.bank or "").strip() or None,
        last4=body.last4,
        network=body.network,
        credit_limit=body.credit_limit,
        min_due_pct=body.min_due_pct,
        color=body.color,
    )
    card.rules.append(
        CardCycleRule(
            effective_from=FAR_PAST,
            statement_day=body.statement_day,
            due_mode=body.due_mode,
            due_value=body.due_value,
        )
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card_out(db, card, detail=True)  # type: ignore[return-value]


@router.get("/{account_id}", response_model=CardDetail)
def get_card(account_id: int, db: Session = Depends(get_db)) -> CardDetail:
    return card_out(db, _get(db, account_id), detail=True)  # type: ignore[return-value]


@router.patch("/{account_id}", response_model=CardDetail)
def update_card(account_id: int, body: CardPatch, db: Session = Depends(get_db)) -> CardDetail:
    card = _get(db, account_id)
    a = card.account
    data = body.model_dump(exclude_unset=True)
    if data.get("name"):
        name = data["name"].strip()
        _check_unique(db, name, exclude_id=a.id)
        a.name = name
    if "last4" in data:
        card.last4 = data["last4"]
        a.account_number = data["last4"]
    for k in ("network", "color"):
        if data.get(k) is not None or (k == "network" and "network" in data):
            setattr(card, k, data[k])
    if "bank" in data:
        card.bank = (data["bank"] or "").strip() or None
    for k in ("credit_limit", "min_due_pct"):
        if data.get(k) is not None:
            setattr(card, k, data[k])
    if data.get("opening_owed") is not None:
        a.opening_balance = -data["opening_owed"]
    if "opening_date" in data:
        a.opening_date = data["opening_date"]
    if data.get("active") is not None:
        a.active = data["active"]
    if "notes" in data:
        a.notes = (data["notes"] or "").strip() or None
    cur = card.rules[-1]
    sd = data.get("statement_day") or cur.statement_day
    mode = data.get("due_mode") or cur.due_mode
    value = data.get("due_value") or cur.due_value
    _check_due(mode, value)
    db.flush()
    add_rule(db, card, sd, mode, value, date.today())
    db.commit()
    db.refresh(card)
    return card_out(db, card, detail=True)  # type: ignore[return-value]


@router.delete("/{account_id}", status_code=204)
def delete_card(account_id: int, db: Session = Depends(get_db)) -> None:
    card = _get(db, account_id)
    used = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(or_(Transaction.source_id == account_id, Transaction.destination_id == account_id))
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This card has {used} transaction(s). Delete those first, or mark the card inactive.",
        )
    a = card.account
    db.delete(card)
    db.delete(a)
    db.commit()
