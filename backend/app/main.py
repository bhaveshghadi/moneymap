import logging

from fastapi import FastAPI

from . import models  # noqa: F401  (registers every table before the routers use them)
from .config import APP_VERSION
from .modules.accounts.router import router as accounts_router
from .modules.auth.router import router as auth_router
from .modules.bills.router import router as bills_router
from .modules.budgets.router import router as budgets_router
from .modules.categories.router import router as categories_router
from .modules.overview.router import router as overview_router
from .modules.piggybanks.router import router as piggybanks_router
from .modules.reset.router import router as reset_router
from .modules.transactions.router import router as transactions_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s  [%(name)s] %(message)s")

app = FastAPI(
    title="MoneyMap API",
    version=APP_VERSION,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

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
    reset_router,
):
    app.include_router(r, prefix="/api")


@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}
