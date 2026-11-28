"""'Date  Narration  Instrument  Debit  Credit  Balance' statements with dates like '18 Aug 2026'
(Saraswat Co-operative Bank and similar). Made-up rows."""

from app.modules.statements.parser import parse_statement, score

# Column-kept text: the first row is a CREDIT, which only the column position can tell.
LAYOUT = """Account Number   XXXXXXXX1234
   Date                Narration                              Instrument           Debit                   Credit             Balance
                                                              Number

   03 Jul 2026         NEFT/N12345/ACME PVT LTD               -                                            5,000.00           6,250.50
                       SALARY JUL


   05 Jul 2026         CARD AMC JUL26 XX0000                  -                    118.00                                     6,132.50

   31 Jul 2026         1234:Int.Pd:01-                        -                                            12.00              6,144.50
                       04-2026 to 30-06-2026
                                             This is computer generated statement and does not require any signature
Some Bank Ltd.                                                                                       Page 1   of 1
"""

# The same rows as plain text: empty cells vanish, so the first row's direction is a guess.
PLAIN = """Account Number   XXXXXXXX1234
Date Narration Instrument
Number Debit Credit Balance
03 Jul 2026 NEFT/N12345/ACME PVT LTD
SALARY JUL - 5,000.00 6,250.50
05 Jul 2026 CARD AMC JUL26 XX0000 - 118.00 6,132.50
31 Jul 2026 1234:Int.Pd:01-
04-2026 to 30-06-2026 - 12.00 6,144.50
Generated on : 01 Aug 2026 08:09:37 PM
Page 1 of 1
"""


def test_columns_give_direction():
    st = parse_statement(LAYOUT)
    assert [(t.date, t.amount, t.balance) for t in st.txns] == [
        ("2026-07-03", 500000, 625050),
        ("2026-07-05", -11800, 613250),
        ("2026-07-31", 1200, 614450),
    ]
    assert st.txns[0].description == "NEFT/N12345/ACME PVT LTD SALARY JUL"
    assert st.txns[2].description == "1234:Int.Pd:01- 04-2026 to 30-06-2026"
    assert st.guessed == 0
    assert st.account_last4 == "1234"


def test_plain_text_reads_amounts_and_prefers_the_column_text():
    st = parse_statement(PLAIN)
    assert [t.amount for t in st.txns][1:] == [-11800, 1200]  # from the balance changes
    assert [t.balance for t in st.txns] == [625050, 613250, 614450]
    assert st.guessed == 1
    assert score(parse_statement(LAYOUT)) > score(st)
