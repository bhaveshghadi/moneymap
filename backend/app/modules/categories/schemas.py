from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ...core.schemas import ORM

COLORS = {"indigo", "mint", "coral", "amber", "blue", "purple", "red", "slate"}


def _check_color(v: str | None) -> str | None:
    if v is not None and v not in COLORS:
        raise ValueError(f"color must be one of {sorted(COLORS)}")
    return v


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["expense", "income"] = "expense"
    icon: str = Field(default="circle", max_length=48)
    color: str = "indigo"

    @field_validator("color")
    @classmethod
    def _color(cls, v: str | None) -> str | None:
        return _check_color(v)


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: Literal["expense", "income"] | None = None
    icon: str | None = Field(default=None, max_length=48)
    color: str | None = None

    @field_validator("color")
    @classmethod
    def _color(cls, v: str | None) -> str | None:
        return _check_color(v)


class CategoryRef(ORM):
    id: int
    name: str
    kind: str
    icon: str
    color: str


class CategoryOut(CategoryRef):
    transaction_count: int = 0
    spent_this_month: int = 0


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class TagOut(ORM):
    id: int
    name: str
    transaction_count: int = 0
