"""Rules: when a transaction matches the conditions, set things on it (category, tags, payee …).
One ordered list, run top to bottom. Conditions and actions are small JSON lists of
{"type": ..., "value": ...}; the vocabulary is in rules/engine.py."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base


class Rule(Base):
    __tablename__ = "rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)  # run order, smallest first
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    match_all: Mapped[bool] = mapped_column(Boolean, default=True)  # all conditions (True) or any one
    stop: Mapped[bool] = mapped_column(Boolean, default=False)  # skip the rules after this one when it matches
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
