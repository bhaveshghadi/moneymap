"""Starter categories created on first-run setup. Transfers (self transfer,
credit-card payment, ATM cash) are the Transfer transaction type, not
categories. Users can rename or delete any of them."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category

# (name, kind, lucide icon, palette colour)
DEFAULT_CATEGORIES: list[tuple[str, str, str, str]] = [
    # income
    ("Salary", "income", "wallet", "mint"),
    ("Business / Freelance", "income", "briefcase", "mint"),
    ("Interest", "income", "percent", "mint"),
    ("Dividend", "income", "coins", "mint"),
    ("Capital Gains", "income", "trending-up", "mint"),
    ("Rental Income", "income", "key-round", "mint"),
    ("Reimbursement", "income", "receipt-text", "mint"),
    ("Refund", "income", "rotate-ccw", "mint"),
    ("Cashback", "income", "badge-percent", "mint"),
    ("Gift", "income", "gift", "coral"),
    ("Other Income", "income", "arrow-down-to-line", "mint"),
    # expense
    ("Housing", "expense", "house", "indigo"),
    ("Rent", "expense", "key", "indigo"),
    ("Society Maintenance", "expense", "building-2", "indigo"),
    ("Utilities", "expense", "zap", "amber"),
    ("Electricity", "expense", "plug-zap", "amber"),
    ("Water", "expense", "droplets", "blue"),
    ("Gas", "expense", "flame", "coral"),
    ("Mobile & Internet", "expense", "wifi", "blue"),
    ("Groceries", "expense", "shopping-basket", "mint"),
    ("Food Delivery", "expense", "utensils", "coral"),
    ("Dining", "expense", "utensils-crossed", "coral"),
    ("Quick Commerce", "expense", "bike", "mint"),
    ("Transport", "expense", "car", "blue"),
    ("Fuel", "expense", "fuel", "amber"),
    ("Cabs", "expense", "car-taxi-front", "amber"),
    ("Vehicle & Servicing", "expense", "wrench", "slate"),
    ("Travel", "expense", "plane", "blue"),
    ("Hotels", "expense", "bed-double", "blue"),
    ("Health", "expense", "heart-pulse", "red"),
    ("Pharmacy", "expense", "pill", "red"),
    ("Fitness", "expense", "dumbbell", "mint"),
    ("Personal Care", "expense", "sparkles", "purple"),
    ("Insurance", "expense", "shield-check", "mint"),
    ("Subscriptions", "expense", "repeat", "indigo"),
    ("Shopping", "expense", "shopping-bag", "purple"),
    ("Clothing", "expense", "shirt", "purple"),
    ("Electronics", "expense", "smartphone", "purple"),
    ("Entertainment", "expense", "clapperboard", "purple"),
    ("Education & Fees", "expense", "graduation-cap", "blue"),
    ("Kids & Childcare", "expense", "baby", "coral"),
    ("Pets", "expense", "paw-print", "amber"),
    ("Household", "expense", "house-plug", "indigo"),
    ("Domestic Help", "expense", "hand-helping", "indigo"),
    ("Family Support", "expense", "users", "coral"),
    ("Gifts Given", "expense", "gift", "coral"),
    ("Charity", "expense", "heart-handshake", "coral"),
    ("Loan / EMI", "expense", "landmark", "coral"),
    ("Taxes", "expense", "scale", "slate"),
    ("Bank Charges & Fees", "expense", "receipt", "red"),
    ("Card Fees & Interest", "expense", "percent", "red"),
    ("Investment", "expense", "trending-up", "mint"),
]


# Starter expense categories counted as essential spending for the emergency fund.
ESSENTIAL_CATEGORIES: frozenset[str] = frozenset(
    {
        "Rent",
        "Housing",
        "Society Maintenance",
        "Utilities",
        "Electricity",
        "Water",
        "Gas",
        "Mobile & Internet",
        "Groceries",
        "Transport",
        "Fuel",
        "Health",
        "Pharmacy",
        "Insurance",
        "Education & Fees",
        "Kids & Childcare",
        "Domestic Help",
        "Loan / EMI",
        "Family Support",
        "Taxes",
    }
)


def seed_categories(db: Session) -> None:
    existing = set(db.scalars(select(Category.name)))
    for name, kind, icon, color in DEFAULT_CATEGORIES:
        if name not in existing:
            db.add(Category(name=name, kind=kind, icon=icon, color=color, essential=name in ESSENTIAL_CATEGORIES))
