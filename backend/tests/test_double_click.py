"""A double / triple click on Import sends the same request several times at once: the work is
done once. Every name and number here is made up."""

from concurrent.futures import ThreadPoolExecutor

from .test_f15_cas_summary import SUMMARY_LINES
from .test_statement_import import PASSWORD, icici  # noqa: F401 (fixture)


def _at_once(fn, n=3):
    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(lambda _: fn(), range(n)))


def _ready_statement(client, icici) -> dict:  # noqa: F811
    d = client.post("/api/statements", json={"attachment_id": icici["att"], "password": PASSWORD}).json()
    base = f"/api/statements/{d['id']}/rows"
    for r in d["rows"]:
        if r["status"] == "needs_account":
            client.patch(f"{base}/{r['id']}", json={"transfer_account_id": icici["card"]["id"]})
        elif r["status"] == "needs_category":
            client.patch(f"{base}/{r['id']}", json={"leave_uncategorised": True})
    return d


def _count(client) -> int:
    return client.get("/api/transactions?limit=500").json()["total"]


def test_statement_import_clicked_three_times(client, icici):  # noqa: F811
    d = _ready_statement(client, icici)
    before = _count(client)
    results = _at_once(lambda: client.post(f"/api/statements/{d['id']}/import"))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    done = sorted(r.json()["imported"] for r in results)
    assert done[:2] == [0, 0] and done[2] > 0  # the first does the work, the others find nothing left
    assert _count(client) == before + done[2]


def test_statement_opened_three_times(client, icici):  # noqa: F811
    results = _at_once(
        lambda: client.post("/api/statements", json={"attachment_id": icici["att"], "password": PASSWORD})
    )
    assert len({r.json()["id"] for r in results}) == 1  # one draft, not three


def test_cas_import_clicked_three_times(client):
    from .test_statement_import import add_email

    att = add_email(SUMMARY_LINES, mid="cas-twice", sender="CAMS <donotreply@camsonline.com>", password=None)
    cid = client.post("/api/statements", json={"attachment_id": att}).json()["detail"]["cas_id"]
    results = _at_once(lambda: client.post(f"/api/investments/cas/{cid}/import"))
    assert sorted(r.status_code for r in results) == [200, 409, 409]  # the others: "already imported"
    assert len(client.get("/api/investments").json()) == 2  # two funds, added once
