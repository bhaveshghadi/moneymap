from pydantic import BaseModel

from ..accounts.schemas import AccountOut
from ..bills.schemas import BillDue
from ..budgets.schemas import BudgetOut
from ..cards.schemas import CardDue
from ..emergency.schemas import EmergencySummary
from ..investments.schemas import DueOut
from ..loans.schemas import LoanDue
from ..transactions.schemas import TransactionOut


class CategorySpend(BaseModel):
    id: int | None  # None = uncategorised
    name: str
    icon: str
    color: str
    amount: int


class Overview(BaseModel):
    month: str  # YYYY-MM
    net_worth: int  # bank + cash + investments' value today, minus what you owe on cards and loans
    cards_owed: int = 0  # outstanding on active credit cards, EMIs included
    loans_owed: int = 0  # what's left on active loans
    investments_value: int = 0  # active investments, value today (a chit's owed instalments subtracted)
    investments_invested: int = 0
    investments_count: int = 0
    income: int  # the month's income
    spending: int  # the month's expenses
    accounts: list[AccountOut]  # active bank and cash accounts
    by_category: list[CategorySpend]  # the month's spending per category, largest first
    recent: list[TransactionOut]  # latest 8 transactions (any month)
    transaction_count: int  # all transactions, to tell a new install from an empty month
    investment_dues: list[DueOut] = []  # maturities, premiums, money due back, chit instalments; current month
    loan_dues: list[LoanDue] = []  # next loan EMIs, overdue or in the next 30 days; current month only
    card_dues: list[CardDue] = []  # card statements overdue or due in the next 30 days; current month only
    upcoming_bills: list[BillDue] = []  # overdue + due in the next 30 days; current month only (F7)
    budgets: list[BudgetOut] = []
    emergency: EmergencySummary | None = (
        None  # once the emergency fund is set up  # the month's active budgets that have an amount or spending (F6)
    )
