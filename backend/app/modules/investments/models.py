"""Investments: details on top of an account of type `investment`.

The account's ledger holds the money: putting money in is a transfer bank -> investment,
taking it out is a transfer investment -> bank (never spending or income). What the
investment is worth today comes from its kind's value rule (investments/values.py).
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...db import Base
from ..accounts.models import Account

KINDS = (
    "mf",  # mutual fund: units x NAV (details in `fund`)
    "fd",  # fixed deposit
    "rd",  # recurring deposit
    "post_office",  # subtype: nsc | kvp | scss | mis | td | rd
    "retirement",  # subtype: ppf | epf | nps | ssy  (balance entered by hand)
    "insurance",  # subtype: endowment | money_back | ulip | term
    "lent",  # money lent to a person
    "chit",  # chit fund
    "gold",  # subtype: jewellery | coin | sgb | digital | silver
    "stocks",  # subtype: stock | etf | esop | rsu | startup
    "crypto",
    "property",
    "other",
)


class Investment(Base):
    __tablename__ = "investment"
    __table_args__ = (UniqueConstraint("account_id", name="uq_investment_account_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", name="fk_investment_account_id_account", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16))
    subtype: Mapped[str | None] = mapped_column(String(16))
    institution: Mapped[str | None] = mapped_column(String(120))  # bank, insurer, organiser, place
    number: Mapped[str | None] = mapped_column(String(64))  # FD / policy / PPF / folio number
    person: Mapped[str | None] = mapped_column(String(120))  # money lent: who to
    rate_bp: Mapped[int | None] = mapped_column(Integer)  # yearly %, x100
    compounding: Mapped[str | None] = mapped_column(String(12))  # monthly|quarterly|half_yearly|yearly|payout|simple
    start_date: Mapped[date | None] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date)  # FD/RD/PO maturity, money lent: due back on
    months: Mapped[int | None] = mapped_column(Integer)  # RD / chit months, insurance premium-paying months
    instalment: Mapped[int | None] = mapped_column(Integer)  # paise: RD / chit instalment, insurance premium
    frequency: Mapped[str | None] = mapped_column(String(12))  # premium: monthly|quarterly|half_yearly|yearly|single
    sum_assured: Mapped[int | None] = mapped_column(Integer)  # paise
    maturity_amount: Mapped[int | None] = mapped_column(Integer)  # paise, as the policy / scheme states it
    quantity: Mapped[int | None] = mapped_column(Integer)  # milli-units: grams, shares, coins
    purity: Mapped[str | None] = mapped_column(String(8))  # gold: 24k|22k|18k|14k, silver: 999|925
    unit_price: Mapped[int | None] = mapped_column(Integer)  # paise per unit, the price last entered
    current_value: Mapped[int | None] = mapped_column(Integer)  # paise, entered by hand
    value_date: Mapped[date | None] = mapped_column(Date)  # when unit_price / current_value was entered
    payout_on: Mapped[date | None] = mapped_column(Date)  # chit: the month you took the payout
    payout_amount: Mapped[int | None] = mapped_column(Integer)
    pay_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("account.id", name="fk_investment_pay_from_id_account", ondelete="SET NULL")
    )  # the bank account money usually comes from
    closed_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped[Account] = relationship(foreign_keys=[account_id], lazy="joined")
    fund: Mapped["Fund | None"] = relationship(
        primaryjoin="Investment.account_id == foreign(Fund.account_id)", uselist=False, lazy="selectin", viewonly=True
    )


class Fund(Base):
    """A mutual fund scheme (one per folio) held in an investment account of kind "mf".
    The account's ledger is the money put in; units x NAV is the value."""

    __tablename__ = "fund"
    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE", name="fk_fund_account_id_account"), primary_key=True
    )
    amc: Mapped[str | None] = mapped_column(String(120))
    scheme: Mapped[str] = mapped_column(String(255))
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    folio: Mapped[str | None] = mapped_column(String(40))
    registrar: Mapped[str | None] = mapped_column(String(16))
    units: Mapped[int] = mapped_column(Integer, default=0)  # milli-units
    units_as_of: Mapped[date | None] = mapped_column(Date)  # the CAS period end the units are from
    nav: Mapped[int | None] = mapped_column(Integer)  # 1/10000 rupee
    nav_date: Mapped[date | None] = mapped_column(Date)
    nav_source: Mapped[str | None] = mapped_column(String(8))  # cas | amfi | hand
    cost: Mapped[int | None] = mapped_column(Integer)  # paise, "Total Cost Value" from the CAS
    amfi_code: Mapped[str | None] = mapped_column(String(12))


class FundTxn(Base):
    """One unit movement in a fund (from a CAS). `transaction_id` is the money side, when there is one."""

    __tablename__ = "fund_txn"
    __table_args__ = (UniqueConstraint("account_id", "date", "kind", "units", "amount", name="uq_fund_txn_row"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE", name="fk_fund_txn_account_id_account"), index=True
    )
    date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column(Integer)  # paise, + into the fund
    units: Mapped[int] = mapped_column(Integer)  # milli-units, signed
    nav: Mapped[int] = mapped_column(Integer)
    stamp_duty: Mapped[int] = mapped_column(Integer, default=0)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", ondelete="SET NULL", name="fk_fund_txn_transaction_id_transaction")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CasImport(Base):
    """A CAS PDF being reviewed / imported."""

    __tablename__ = "cas_import"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("gmail_attachment.id", ondelete="SET NULL", name="fk_cas_import_attachment_id_gmail_attachment"),
        index=True,
    )
    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)
    unparsed: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | imported
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)

    funds: Mapped[list["CasFund"]] = relationship(
        back_populates="cas", order_by="CasFund.idx", cascade="all, delete-orphan", lazy="selectin"
    )
    rows: Mapped[list["CasRow"]] = relationship(
        back_populates="cas", order_by="CasRow.idx", cascade="all, delete-orphan", lazy="selectin"
    )


class CasFund(Base):
    __tablename__ = "cas_fund"
    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("cas_import.id", ondelete="CASCADE", name="fk_cas_fund_import_id_cas_import"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    amc: Mapped[str | None] = mapped_column(String(120))
    folio: Mapped[str | None] = mapped_column(String(40))
    scheme: Mapped[str] = mapped_column(String(255))
    isin: Mapped[str | None] = mapped_column(String(12))
    registrar: Mapped[str | None] = mapped_column(String(16))
    opening_units: Mapped[int] = mapped_column(Integer, default=0)
    closing_units: Mapped[int | None] = mapped_column(Integer)
    nav: Mapped[int | None] = mapped_column(Integer)
    nav_date: Mapped[date | None] = mapped_column(Date)
    cost: Mapped[int | None] = mapped_column(Integer)
    market_value: Mapped[int | None] = mapped_column(Integer)
    # review: the investment account it goes to (None = a new one on import)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("account.id", ondelete="SET NULL", name="fk_cas_fund_account_id_account")
    )
    create_new: Mapped[bool] = mapped_column(Boolean, default=False)
    skip: Mapped[bool] = mapped_column(Boolean, default=False)
    # what to import: both | fund (today's holding, no history) | txns (rows into a fund you have)
    mode: Mapped[str] = mapped_column(String(8), default="both", server_default="both")

    cas: Mapped[CasImport] = relationship(back_populates="funds")


class CasRow(Base):
    """One CAS transaction. `action` is what happens on the money side:
    link (an existing transfer with this fund records it), convert (turn the matched bank
    expense / income into that transfer), transfer (create one with bank_account_id),
    switch (create the fund -> fund transfer, on the "out" row), before (older than your
    records: counts in the fund's opening balance), units (no money moves), skip."""

    __tablename__ = "cas_row"
    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("cas_import.id", ondelete="CASCADE", name="fk_cas_row_import_id_cas_import"), index=True
    )
    fund_id: Mapped[int] = mapped_column(
        ForeignKey("cas_fund.id", ondelete="CASCADE", name="fk_cas_row_fund_id_cas_fund"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer)
    nav: Mapped[int] = mapped_column(Integer)
    balance: Mapped[int] = mapped_column(Integer)
    stamp_duty: Mapped[int] = mapped_column(Integer, default=0)
    action: Mapped[str] = mapped_column(String(10))
    match_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", ondelete="SET NULL", name="fk_cas_row_match_transaction_id_transaction")
    )
    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("account.id", ondelete="SET NULL", name="fk_cas_row_bank_account_id_account")
    )
    pair_row_id: Mapped[int | None] = mapped_column(Integer)  # the other side of a switch
    existing: Mapped[bool] = mapped_column(Boolean, default=False)  # imported by an earlier CAS
    user_set: Mapped[bool] = mapped_column(Boolean, default=False)
    fund_txn_id: Mapped[int | None] = mapped_column(Integer)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", ondelete="SET NULL", name="fk_cas_row_transaction_id_transaction")
    )

    cas: Mapped[CasImport] = relationship(back_populates="rows")
    fund: Mapped[CasFund] = relationship(lazy="joined")
