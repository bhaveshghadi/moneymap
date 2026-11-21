from typing import Literal

from pydantic import BaseModel


class GuideStep(BaseModel):
    key: str
    title: str
    why: str  # what to do and why it matters
    href: str  # the page that does it
    optional: bool  # "I don't have one" is fine
    manual: bool  # ticked by hand (can't be told from the data)
    detail: str  # what's there now, e.g. "2 accounts added"
    done: bool
    skipped: bool


class GuideOut(BaseModel):
    steps: list[GuideStep]
    done: int
    total: int
    hidden: bool  # you closed the guide
    finished: bool  # every step done or skipped
    show_first: bool  # open it on sign-in


class GuideMark(BaseModel):
    action: Literal["check", "skip", "undo", "hide", "show"]
    step: str | None = None
