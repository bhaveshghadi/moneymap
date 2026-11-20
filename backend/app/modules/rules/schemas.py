from datetime import date as Date
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..transactions.schemas import TransactionOut


class Item(BaseModel):
    type: str
    value: Any = None


class RuleIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    active: bool = True
    match_all: bool = True
    stop: bool = False
    conditions: list[Item] = Field(min_length=1, max_length=20)
    actions: list[Item] = Field(min_length=1, max_length=20)


class RulePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None
    match_all: bool | None = None
    stop: bool | None = None
    conditions: list[Item] | None = Field(default=None, min_length=1, max_length=20)
    actions: list[Item] | None = Field(default=None, min_length=1, max_length=20)


class RuleOut(BaseModel):
    id: int
    title: str
    position: int
    active: bool
    match_all: bool
    stop: bool
    conditions: list[Item]
    actions: list[Item]
    model_config = {"from_attributes": True}


class MoveIn(BaseModel):
    direction: Literal["up", "down"]


class Change(BaseModel):
    """One existing transaction a rule matches, and what it would change."""

    transaction: TransactionOut
    changes: list[str]  # e.g. "Category: Food", "Tag: #delivery" (empty = already as the rule says)


class TestOut(BaseModel):
    matched: int
    would_change: int
    items: list[Change]  # the newest 50


class ApplyIn(BaseModel):
    overwrite: bool = False  # False: only fill what's empty
    since: Date | None = None  # only transactions on or after this date


class ApplyOut(BaseModel):
    matched: int
    changed: int


class Suggestion(BaseModel):
    """A payee you've put in the same category again and again."""

    payee: str
    type: Literal["withdrawal", "deposit"]
    category_id: int
    category: str
    count: int  # transactions with this payee in that category
    total: int  # all categorised transactions with this payee
