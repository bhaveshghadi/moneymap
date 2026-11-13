"""Imports every feature's models so they register on Base.metadata
(used by Alembic and the tests). Add each new feature module here."""

from .modules.accounts.models import BALANCE_TYPES, Account, AccountType  # noqa: F401
from .modules.auth.models import Setting, User  # noqa: F401
from .modules.bills.models import Bill, BillRepeat  # noqa: F401
from .modules.budgets.models import Budget, BudgetLimit, BudgetMode  # noqa: F401
from .modules.categories.models import Category, Tag  # noqa: F401
from .modules.transactions.models import Transaction, TransactionType, transaction_tag  # noqa: F401
