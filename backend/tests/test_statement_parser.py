"""Statement parser tests (Indian bank and card statement layouts)."""
from app.modules.statements.parser import (
    amount_to_paise,
    balance_consistency,
    balance_mismatches,
    parse_statement,
    split_rows,
)

STATEMENT = """
HDFC BANK LTD - Statement of Account
Account No: XXXXXX1234   Period: 01/07/2025 to 31/07/2025
Date Narration Withdrawal Deposit Balance
01/07/2025 NEFT CR NEXORA SYSTEMS PVT LTD SALARY JUL 180000.00 230000.00
05/07/2025 UPI RENT PAYMENT R VENKATESH 55000.00 175000.00
10/07/2025 ATM CASH WITHDRAWAL BLR 10000.00 165000.00
15/07/2025 INTEREST CREDIT 1200.00 166200.00
"""

CARD_STATEMENT = """
HDFC Bank Infinia Credit Card Statement
Card Number: XXXX XXXX XXXX 7702   Statement Date: 31/03/2026
Date Transaction Description Amount
02/03/2026 AMAZON IN BANGALORE Ref 560123456789012 2,499.00
05/03/2026 SWIGGY ORDER BLR 845.50
11/03/2026 PAYMENT RECEIVED THANK YOU 45000.00 Cr
18/03/2026 MAKEMYTRIP FLIGHT 12,340.00
22/03/2026 AMAZON REFUND 1,200.00 Cr
"""


def test_amounts_and_rows():
    assert amount_to_paise("1,80,000.00") == 18_000_000
    assert amount_to_paise("1200") == 120_000
    rows = split_rows(STATEMENT)
    assert len(rows) == 4 and rows[0].startswith("01/07/2025")


def test_balance_delta_signs():
    st = parse_statement(STATEMENT, "bank_statement", opening_balance=5_000_000)
    assert [t.amount for t in st.txns] == [18_000_000, -5_500_000, -1_000_000, 120_000]
    assert st.txns[0].date == "2025-07-01" and "NEXORA SYSTEMS" in st.txns[0].description
    assert st.txns[0].balance == 23_000_000
    assert st.account_last4 == "1234"


def test_card_statement_markers_and_refs():
    st = parse_statement(CARD_STATEMENT, "bank_statement")
    assert st.doc_type == "card_statement" and st.account_last4 == "7702"
    by = {t.description.split()[0] + t.description.split()[1]: t.amount for t in st.txns}
    assert by["AMAZONIN"] == -249_900  # the 15-digit ref is not the amount
    assert by["SWIGGYORDER"] == -84_550
    assert by["PAYMENTRECEIVED"] == 4_500_000
    assert by["AMAZONREFUND"] == 120_000


def test_two_transactions_on_one_line_split():
    merged = """
ICICI Bank Statement Period: 01/03/2026 to 31/03/2026
10/03/2026 BIL/Home Loan XX22222 EMI 1,27,000.00 3,50,000.00 12/03/2026 UPI/INDmoney/indmoneymf1@ici/INDMoney 5,000.00 3,45,000.00
"""
    st = parse_statement(merged, opening_balance=47_700_000)
    assert [(t.date, t.amount) for t in st.txns] == [("2026-03-10", -12_700_000), ("2026-03-12", -500_000)]
    assert "INDmoney" not in st.txns[0].description and "INDmoney" in st.txns[1].description


def test_value_date_column_stays_one_row():
    text = """
Axis Bank Statement
05/03/2026 06/03/2026 NEFT CR ACME TECH SALARY MAR 2,50,000.00 4,00,000.00
07/03/2026 07/03/2026 UPI RENT PAYMENT 55,000.00 3,45,000.00
"""
    st = parse_statement(text, opening_balance=15_000_000)
    assert [t.amount for t in st.txns] == [25_000_000, -5_500_000]


def test_invalid_dates_rejected():
    text = """
HDFC Statement
01/07/2025 NEFT CR SALARY 1,80,000.00 2,30,000.00
99/99/99 NOT A DATE 1,111.00 9,999.00
15/13/2025 BAD MONTH 2,222.00 8,888.00
"""
    st = parse_statement(text, opening_balance=5_000_000)
    assert len(st.txns) == 1


def test_icici_orphan_narration_attaches_to_next_row():
    icici = """
DATE MODE PARTICULARS DEPOSITS WITHDRAWALS BALANCE
03-02-2026 CMS TRANSACTION CMS/TATA CONSULTANCY/Tata Consultancy 171.00 2,13,784.46
05-02-2026 BIL/Home Loan XX22222 EMI Test User 1,30,817.00 82,967.46
UPI/INDmoney/indmoneymf1@ic/INDMoney M/ICICI
05-02-2026 Bank/600000000106/ICI0aaa1111bbbb2222cccc3333dddd5 10,000.00 72,967.46
be2/
UPI/CRED/cred.utility@a/payment on/AXIS
05-02-2026 BANK/600000000107/ACD0aaa1111bbbb2222cccc3333dd 1,006.00 71,961.46
"""
    st = parse_statement(icici, opening_balance=21_361_346)
    assert len(st.txns) == 4
    emi = next(t for t in st.txns if "Home Loan" in t.description)
    assert emi.amount == -13_081_700 and "INDmoney" not in emi.description
    sip = next(t for t in st.txns if "INDmoney" in t.description)
    assert sip.amount == -1_000_000
    cred = next(t for t in st.txns if "cred.utility" in t.description)
    assert cred.amount == -100_600


def test_dr_honorific_kept():
    st = parse_statement("Card Statement Date: 31/03/2026\n02/03/2026 DR. REDDYS PHARMACY BLR 845.50", "card_statement")
    assert "DR. REDDYS" in st.txns[0].description


def test_icici_account_last4_and_card_detection():
    filler = "\n".join(f"Summary line {i}" for i in range(30))
    text = (f"ICICI BANK STATEMENT\n{filler}\nACCOUNT TYPE ACCOUNT BALANCE (I) NOMINATION\n"
            "Savings A/c XXXXXXXX2840 1,23,456.00 REGISTERED\n01/05/2025 UPI/swiggy/food 250.00 1,23,206.00")
    assert parse_statement(text).account_last4 == "2840"
    card = "CREDIT CARD STATEMENT June 2025\nSummary\nText\n4375XXXXXXXX9012\n01/05/2025 AMAZON RETAIL 1,234.00"
    st = parse_statement(card)
    assert st.account_last4 == "9012" and st.doc_type == "card_statement"
    # never from transaction rows
    rows = "HDFC BANK LTD\nStatement\n01/03/2025 NEFT-MB-XXXXXXXX2840-TRANSFER 5,000.00 45,000.00"
    assert parse_statement(rows).account_last4 is None


def test_counterparties():
    assert parse_statement("01/03/2025 UPI/john.doe@okhdfc/Payment 250.00 9,750.00").txns[0].counterparty == "john.doe@okhdfc"
    neft = parse_statement("01/03/2025 NEFT DR-HDFC0001-JANE SMITH-REF123 5,000.00 4,750.00")
    assert neft.txns[0].counterparty == "JANE SMITH"


def test_summary_lines_skipped():
    text = "01/03/2025 OPENING BALANCE 10,000.00\n02/03/2025 SWIGGY 250.00 9,750.00\n31/03/2025 CLOSING BALANCE 9,750.00"
    st = parse_statement(text)
    assert [t.description for t in st.txns] == ["SWIGGY"] and len(st.unparsed) == 2


# Structure of a real ICICI savings e-statement (Sept 2026), names/numbers made up.
ICICI_SAVINGS = """
STATEMENT SUMMARY for Customer ID : XXXXX1234 as on September 30, 2026.
ACCOUNT DETAILS - INR
ACCOUNT TYPE   ACCOUNT BALANCE (I)   NOMINATION
Savings A/c XXXXXXXX5678   1,32,613.33   Not Registered
PPF A/c XXXXXXXX9999   24,828.00   Not Registered
TOTAL   1,57,441.33
Statement of Transactions in Savings Account XXXXXXXX5678 in INR for the period September 01, 2026 - September 30, 2026
DATE   MODE   PARTICULARS   DEPOSITS   WITHDRAWALS   BALANCE
01-09-2026   B/F   1,22,950.91
SUNRISE STORES
01-09-2026   UPI/SUNRISEST/sunrise01@idf/UPI/IDFC   120.00   1,22,830.91
FIRST/600000000101/ICI0aaa1111bbbb2222cccc3333dddd4444
d9
03-09-2026   ACH/DEMOPAYMENTSPVT/ICIC0000000000000001/DEMOMF   5,000.00   1,17,830.91
MEERA IYER
03-09-2026   UPI/MEERA I/meerai01@okkotak/UPI/Kotak   1,000.00   1,18,830.91
Mahi/600000000102/AXI0aaa1111bbbb2222cccc3333dddd55
15
03-09-2026 OTHER ATMS   NFS/CASHWDL/600000000103/00000001/CITY/03-09-26 1200   10,000.00   1,08,830.91
OAKWOOD FURNITURE
03-09-2026   UPI/OAKWOOD/oakwood1@okicici/Cupboard/BANK OF   16,000.00   92,830.91
MA/600000000104/ICI0aaa1111bbbb22
05-09-2026 CMS TRANSACTION   CMS/0099000000001/DEMOMFC REF0001X   5,000.00   97,830.91
05-09-2026   BIL/Personal Loan XX11111 EMI   13,462.00   84,368.91
08-09-2026   BIL/INFT/FIC0000001/CC BillPay-9012/Self   37,812.58   46,556.33
Total:   16,000.00   1,06,139.58   46,556.33
Page 1 of 3 M-12345678-41362
Statement of Transactions in Savings Account XXXXXXXX5678 in INR for the period September 01, 2026 - September 30, 2026
DATE   MODE   PARTICULARS   DEPOSITS   WITHDRAWALS   BALANCE
NIPPON INDIA LIQUID FUND
15-09-2026   NEFT-AXISCN000000001-NIPPON INDIA LIQUID FUND   20,000.00   66,556.33
REDEMPTION A/C-CUST NIPPON INDIA
-0000000000001-UT
22-09-2026 CHEQUE 100001   CLG/GREEN PARK CHS/GPC   1,530.00   65,026.33
30-09-2026   1231015 99999:Int.Pd:30-06-2026 to 29-09-2026   348.00   65,374.33
NETFLIX COM
30-09-2026   UPI/NETFLIX CO/netflix@hdfcbank/Monthly au/HDFC   199.00   65,175.33
BANK/600000000105/HDF0AAA1111BBBB2222CCCC3333DDDD
Total:   20,348.00   1,729.00   65,175.33
Account Related Other Information
ACCOUNT TYPE   ACCOUNT NUMBER   MICR CODE   IFS CODE
Savings   XXXXXXXX5678   400000000   ICIC0000001
Page 2 of 3 M-12345678-41362
"""


def test_icici_savings_real_structure():
    st = parse_statement(ICICI_SAVINGS)
    assert st.account_last4 == "5678" and st.doc_type == "bank_statement"
    got = [(t.date, t.amount) for t in st.txns]
    assert got == [
        ("2026-09-01", -12_000),       # first row: direction fixed by the B/F balance
        ("2026-09-03", -500_000),
        ("2026-09-03", 100_000),       # UPI credit
        ("2026-09-03", -1_000_000),    # ATM (the 03-09-26 inside doesn't split the row)
        ("2026-09-03", -1_600_000),
        ("2026-09-05", 500_000),       # CMS credit
        ("2026-09-05", -1_346_200),    # EMI
        ("2026-09-08", -3_781_258),    # credit-card bill pay
        ("2026-09-15", 2_000_000),     # NEFT redemption (after the page break)
        ("2026-09-22", -153_000),      # cheque
        ("2026-09-30", 34_800),        # interest (internal dates don't split it)
        ("2026-09-30", -19_900),
    ]
    by_date = {t.amount: t for t in st.txns}
    # payee lines printed above a row are its name hint, and don't leak into the previous row
    assert by_date[-12_000].name_hint == "SUNRISE STORES"
    assert by_date[-1_600_000].name_hint == "OAKWOOD FURNITURE"
    assert "OAKWOOD" not in by_date[-1_000_000].description
    assert by_date[-19_900].name_hint == "NETFLIX COM"
    # totals / page furniture never glue onto a row
    assert not any("Total" in t.raw or "Page" in t.raw for t in st.txns)
    from app.modules.statements.parser import balance_consistency
    assert balance_consistency(st) == len(st.txns) - 1  # every running balance adds up


# Made-up data, same shape as a real ICICI savings statement's last page.
ICICI_LAST_PAGE = """
DATE   MODE   PARTICULARS   DEPOSITS   WITHDRAWALS   BALANCE
01-10-2026   B/F   50,000.00
RAVI KUMAR
02-10-2026   UPI/RAVI KUMA/XX1111@okaxis/UPI/AXIS   500.00   49,500.00
BA/600000000001/ICIaaaa
BIL/NEFT/IN1200000001/Plot/SURESH/U
03-10-2026   20,000.00   29,500.00
NIONBANK OF I
Lakshmi General Stores
03-10-2026   UPI/Lakshmi Ge/XX2222@ybl/UPI/YES BANK   150.00   29,350.00
L/600000000002/ICIbbbb
NFS/CASH WDL/600000000003/PA0000X1/PUNE
05-10-2026 OTHER ATMS   5,000.00   24,350.00
/05-10-261200
meera123 okicici
UPI/meera123/XXa123@okicici/UPI/INDIA
06-10-2026   200.00   24,150.00
POST/600000000004/ICIcccc
08
SITA DEVI
UPI/SITA DEVI/XX3333@okbizax/UPI/AXIS
07-10-2026   1,000.00   23,150.00
BANK/600000000005/ICIdddd
74
Total:   0.00   26,850.00   23,150.00
Other information related to the Account(s)
Savings   XXXXXXXX5678   400000000   ICIC0000001   -   NOT REGISTERED
Sincerely,
A monthly limit applies (minimum of 2 lakh up to a maximum of 7.5 lakh as per product type).
capacity.
"""


def test_icici_last_page_rows_and_footer():
    from app.modules.statements.parser import balance_mismatches

    st = parse_statement(ICICI_LAST_PAGE)
    assert [t.amount for t in st.txns] == [-50_000, -2_000_000, -15_000, -500_000, -20_000, -100_000]
    assert balance_mismatches(st) == 0
    ravi, neft, shop, atm, meera, sita = st.txns
    # last row stops at "Total:" — the footer (and its numbers) is not part of it
    assert sita.balance == 2_315_000 and sita.name_hint == "SITA DEVI"
    assert "Sincerely" not in sita.raw and "capacity" not in sita.raw
    # an NFS (ATM) line printed above its row belongs to that row
    assert "NFS/CASH WDL" in atm.description and "NFS" not in ravi.raw
    # a UPI handle-style name ("meera123 okicici") is the next row's payee
    assert meera.name_hint == "meera123 okicici" and "meera123 okicici" not in atm.raw
    # wrapped tail of the previous row isn't glued onto the next payee name
    assert shop.name_hint == "Lakshmi General Stores"
    assert "NIONBANK OF I" in neft.raw and neft.name_hint is None


# Made-up data shaped like an ICICI co-branded credit-card statement.
CARD_WITH_SECTIONS = """
Credit Card Statement
Date   SerNo.   Transaction Details   Reward   Intl.#   Amount (in`)
01/10/2026   10000000001   QUICKMART GROCERY BANGALORE IN   14   282.00
01/10/2026   10000000002   FOODAPP BANGALORE IN   10   1,074.00
EARNINGS
Earnings transfered to
Amazon Pay balance*
733   733
used for purchasing 10 Crore + products. Credit will be added within 2 Business
Days of monthly Credit Card statement generation   0
Page 1 of 4
Date   SerNo.   Transaction Details   Reward Points   Intl.# amount   Amount (in
03/10/2026   10000000003   BBPS Payment received   0   2,000.00 CR
17/10/2026   10000000004   SOME SHOP Tiruppur TN IN   16   1,623.57
# International Spends
EMI / PERSONAL LOAN ON CREDIT CARDS
Merchant EMI   20/07/2026   20/12/2026   6   34,934.00   3   18,290.59   6,096.87
conversions
Page 2 of 4
MOST IMPORTANT TERMS AND CONDITIONS (MITC)
Effective 01/04/2026 a fee of 1,100.00 applies on late payment.
"""


def test_card_statement_stops_at_non_transaction_sections():
    st = parse_statement(CARD_WITH_SECTIONS)
    assert st.doc_type == "card_statement"
    assert [(t.date, t.amount) for t in st.txns] == [
        ("2026-10-01", -28_200),
        ("2026-10-01", -107_400),  # stays a purchase: "Credit" in the text below it isn't glued on
        ("2026-10-03", 200_000),
        ("2026-10-17", -162_357),  # last purchase; the EMI table and terms aren't rows
    ]
    assert st.txns[1].description.endswith("FOODAPP BANGALORE IN 10")


# ICICI net-banking download ("OpTransactionHistory"): name line above each row,
# "S No  DD.MM.YYYY  [cheque]  amount  balance", remarks below, page furniture between.
# Made-up names and numbers.
ICICI_OP_HISTORY = """1
Statement of Transactions in Saving Account no. 000101234567 in INR for the period March 1, 2026 - March 31, 2026
TEST PERSON   Your Base Branch: ICICI BANK LIMITED,
Transaction   Withdrawal   Deposit   Balance
S No.   Cheque Number   Transaction Remarks
Date   Amount (INR)   Amount (INR)   (INR)
Tea Stall
1   02.03.2026   40.00   9960.00
UPI/Tea Stall/teastall@ybl/UPI/YES BANK
L/600000000001/ICIabc123
CRED Club
2   03.03.2026   2500.00   7460.00
UPI/CRED Club/cred.club@axisb/payment on/AXIS
BANK/600000000002/ACDdef456
www.icici.bank.in   Dial your Bank 1800-1080
Please call from your registered mobile number for faster access
Never share your OTP, CVV or passwords with anyone, even if the person claims to be a Bank employee.
2
Transaction   Withdrawal   Deposit   Balance
S No.   Cheque Number   Transaction Remarks
Date   Amount (INR)   Amount (INR)   (INR)
Internet banking trxn
3   05.03.2026   1200.00   6260.00
BIL/INFT/AB12345678/Personal Loan XX1111 EMI
Test
Credit trxn
4   06.03.2026   000123   50000.00   56260.00
NEFT-DEMO0001-ACME TECH SALARY
5e2416
Ravi Kumar
5   07.03.2026   300.00   55960.00
UPI/Ravi Kumar/ravi@okhdfcb/UPI/HDFC
Sincerly,
Team ICICI Bank
Legends for transactions in your Account Statement
BIL - Internet Bill payment   NEFT - National Electronics Funds Transfer System 1,000.00
"""


def test_icici_op_history_download():
    st = parse_statement(ICICI_OP_HISTORY)
    assert st.account_last4 == "4567"
    assert [(t.date, t.amount) for t in st.txns] == [
        ("2026-03-02", -4000), ("2026-03-03", -250000), ("2026-03-05", -120000),
        ("2026-03-06", 5000000), ("2026-03-07", -30000),
    ]
    assert [t.name_hint for t in st.txns] == ["Tea Stall", "CRED Club", "Internet banking trxn", "Credit trxn", "Ravi Kumar"]
    assert st.txns[0].description.startswith("UPI/Tea Stall/teastall@ybl") and "ICIabc123" in st.txns[0].description
    assert st.txns[2].description.endswith("EMI Test")  # wrapped remark kept, next row's name not taken
    assert st.txns[3].description.startswith("NEFT-DEMO0001") and "5e2416" in st.txns[3].description  # cheque no. ignored
    assert "www.icici" not in " ".join(t.description for t in st.txns)  # page footer dropped
    assert st.txns[4].description == "UPI/Ravi Kumar/ravi@okhdfcb/UPI/HDFC"  # stops at the closing text
    assert balance_consistency(st) == 4 and balance_mismatches(st) == 0
