"""Property bought in parts: price paid vs the agreed price, the plan for the balance, costs on
top, and what it counts for until it's registered.

Money paid is the investment account's ledger (transfers bank -> property, from any source: a
payment recorded here, a statement, the opening amount). Costs paid through MoneyMap are also
transfers into it, so they're taken off to get the price paid. Until registration the property
counts as what you've paid; once registered, as its value (the price, or a value you enter).
"""

from datetime import date

from sqlalchemy.orm import Session

from ..piggybanks.models import PiggyBank
from .models import Investment, PropertyDeal
from .schemas import CostOut, InstalmentOut, PropertyOut
from .values import Due, Valued


def property_out(db: Session | None, inv: Investment, v: Valued, today: date) -> PropertyOut | None:
    """Works out the property side and adjusts `v` (value, dues). None for other kinds / no deal."""
    d: PropertyDeal | None = inv.deal
    if inv.kind != "property" or d is None:
        return None
    costs_total = sum(c.amount for c in d.costs)
    costs_in = sum(c.amount for c in d.costs if c.transaction_id)
    price_paid = max(0, v.invested - costs_in)
    balance = max(0, d.price - price_paid) if d.price else None

    plan, left, planned = [], price_paid, 0
    # instalments are paid oldest first from what's been paid beyond the instalments' share:
    # the plan covers the balance, so money paid so far first covers the price outside the plan
    outside = (d.price - sum(i.amount for i in d.plan)) if d.price else 0
    left = max(0, price_paid - max(0, outside))
    for i in d.plan:
        got = min(i.amount, left)
        left -= got
        planned += i.amount
        status = "paid" if got >= i.amount else "part" if got > 0 else ("overdue" if i.due_date < today else "due")
        plan.append(InstalmentOut(id=i.id, due_date=i.due_date, amount=i.amount, note=i.note, paid=got, status=status))
        if status != "paid":
            v.dues.append(Due(i.due_date, "balance", i.amount - got))

    # what it counts for: what you've paid until it's yours, then its value
    if d.status != "registered":
        v.value, v.value_date, v.stale = max(0, v.invested), None, False
    elif inv.current_value is None:
        v.value = d.price or max(0, v.invested)

    goal_saved = None
    if d.goal_id and db is not None:
        from ..piggybanks.router import saved_map

        g = db.get(PiggyBank, d.goal_id)
        if g is not None:
            goal_saved = saved_map(db).get(g.id, 0)
            if balance is not None and g.target_amount != balance and balance > 0:
                g.target_amount = balance  # the goal follows the balance still to pay
    return PropertyOut(
        price=d.price,
        size=d.size,
        location=d.location,
        survey_no=d.survey_no,
        seller=d.seller,
        agreement_date=d.agreement_date,
        status=d.status,  # type: ignore[arg-type]
        registered_on=d.registered_on,
        price_paid=price_paid,
        balance=balance,
        costs_total=costs_total,
        total_cost=price_paid + costs_total,
        plan=plan,
        unplanned=max(0, balance - (planned - sum(x.paid for x in plan))) if balance is not None and d.plan else None,
        costs=[
            CostOut(id=c.id, kind=c.kind, amount=c.amount, date=c.date, note=c.note, transaction_id=c.transaction_id)  # type: ignore[arg-type]
            for c in d.costs
        ],
        goal_id=d.goal_id,
        goal_saved=goal_saved,
    )
