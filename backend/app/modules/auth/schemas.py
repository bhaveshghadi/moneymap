from pydantic import BaseModel, Field


class AuthStatus(BaseModel):
    setup_required: bool
    authenticated: bool
    username: str | None = None
    display_name: str | None = None
    is_admin: bool = False
    must_change_password: bool = False  # set by the admin's temporary password


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SetupIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = ""  # not needed while on the admin's temporary password (just used to sign in)
    new_password: str = Field(min_length=8, max_length=256)
