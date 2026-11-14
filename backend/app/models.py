"""Imports every feature's models so they register on Base.metadata
(used by Alembic and the tests). Add each new feature module here."""

from .modules.accounts.models import BALANCE_TYPES, Account, AccountType  # noqa: F401
from .modules.auth.models import Setting, User  # noqa: F401
from .modules.bills.models import Bill, BillRepeat  # noqa: F401
from .modules.budgets.models import Budget, BudgetLimit, BudgetMode  # noqa: F401
from .modules.categories.models import Category, Tag  # noqa: F401
from .modules.emergency.models import EmergencyFund  # noqa: F401
from .modules.gmail.models import GmailAccount, GmailAttachment, GmailMessage, GmailRun  # noqa: F401
from .modules.piggybanks.models import PiggyBank, PiggyEvent  # noqa: F401
from .modules.statements.models import StatementImport, StatementRow  # noqa: F401
from .modules.transactions.models import Transaction, TransactionType, transaction_tag  # noqa: F401
