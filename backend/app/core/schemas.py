"""Shared Pydantic bits. Amounts are integer paise.

Gotcha: a field named `date` with a default must be typed with the `Date`
alias (`date: Date | None = None`), or the name shadows the type.
"""

from pydantic import BaseModel, ConfigDict


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)
