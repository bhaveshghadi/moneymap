from datetime import datetime

from pydantic import BaseModel, Field


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str | None
    is_admin: bool
    disabled: bool
    must_change_password: bool  # hasn't chosen their own password yet
    locked: bool  # too many wrong passwords just now
    created_at: datetime | None
    last_login_at: datetime | None


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^\s*[A-Za-z0-9._@-]+\s*$")
    display_name: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=256)  # blank = MoneyMap makes one
    is_admin: bool = False


class UserCreated(BaseModel):
    user: UserOut
    temporary_password: str  # shown once; they change it at the first sign-in


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    is_admin: bool | None = None
    disabled: bool | None = None


class UserDelete(BaseModel):
    confirm: str  # their username
