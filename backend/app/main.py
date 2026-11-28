import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import models  # noqa: F401  (registers every table before the routers use them)
from .config import APP_VERSION
from .core.users import all_user_ids
from .db import as_user
from .modules.accounts.router import router as accounts_router
from .modules.auth.router import router as auth_router
from .modules.auth.security import SessionUserMiddleware
from .modules.bills.router import router as bills_router
from .modules.budgets.router import router as budgets_router
from .modules.cards.emi import router as emi_router
from .modules.cards.router import router as cards_router
from .modules.categories.router import router as categories_router
from .modules.emergency.router import router as emergency_router
from .modules.gmail.fetch import recover_stuck_runs
from .modules.gmail.inbox_router import router as inbox_router
from .modules.gmail.router import router as gmail_router
from .modules.guide.router import router as guide_router
from .modules.investments.fund_router import router as funds_router
from .modules.investments.nav import start_daily_updates
from .modules.investments.router import router as investments_router
from .modules.loans.router import router as loans_router
from .modules.loans.statement_router import router as loan_statement_router
from .modules.overview.router import router as overview_router
from .modules.piggybanks.router import router as piggybanks_router
from .modules.reset.router import router as reset_router
from .modules.rules.router import router as rules_router
from .modules.savings.router import router as savings_router
from .modules.statements.router import router as statements_router
from .modules.transactions.router import router as transactions_router
from .modules.users.router import router as users_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s  [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    for uid in all_user_ids():
        with as_user(uid):
            recover_stuck_runs()  # a restart kills Gmail fetch threads; don't leave them "running"
    stop = start_daily_updates()  # mutual fund prices from AMFI, once a day after 9 pm
    yield
    if stop is not None:
        stop.set()


app = FastAPI(
    title="MoneyMap API",
    version=APP_VERSION,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Every request runs as the signed-in person: their own database file (app/db.py).
app.add_middleware(SessionUserMiddleware)

# One line per feature. Every router except auth requires a signed-in user.
for r in (
    auth_router,
    accounts_router,
    categories_router,
    transactions_router,
    overview_router,
    budgets_router,
    bills_router,
    piggybanks_router,
    emergency_router,
    cards_router,
    emi_router,
    loan_statement_router,
    loans_router,
    funds_router,  # before investments_router: /investments/cas isn't an account id
    investments_router,
    rules_router,
    savings_router,
    guide_router,
    gmail_router,
    inbox_router,
    statements_router,
    reset_router,
    users_router,
):
    app.include_router(r, prefix="/api")


@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}
