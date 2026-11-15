"""F3: categories and tags."""
from .helpers import TODAY, balance, cat_id, spend  # noqa: F401


def test_setup_seeds_categories(client):
    cats = client.get("/api/categories").json()
    assert len(cats) == 53
    kinds = {c["kind"] for c in cats}
    assert kinds == {"expense", "income"}
    assert sum(c["kind"] == "income" for c in cats) == 11


def test_categories_and_tags(client, bank):
    r = client.post("/api/categories", json={"name": "Hobbies", "icon": "palette", "color": "purple"})
    assert r.status_code == 201
    c = r.json()
    assert client.post("/api/categories", json={"name": "Hobbies"}).status_code == 409
    assert client.post("/api/categories", json={"name": "X", "color": "pink"}).status_code == 422
    t = spend(client, bank, 700, category_id=c["id"], tags=["trip"])
    assert client.patch(f"/api/categories/{c['id']}", json={"name": "Hobby"}).json()["name"] == "Hobby"
    hobby = next(x for x in client.get("/api/categories").json() if x["id"] == c["id"])
    assert hobby["transaction_count"] == 1
    # deleting a category leaves its transactions uncategorised
    assert client.delete(f"/api/categories/{c['id']}").status_code == 204
    assert client.get(f"/api/transactions/{t['id']}").json()["category"] is None
    tags = client.get("/api/tags").json()
    assert [(x["name"], x["transaction_count"]) for x in tags] == [("trip", 1)]
    tid = tags[0]["id"]
    assert client.patch(f"/api/tags/{tid}", json={"name": "Holiday"}).json()["name"] == "Holiday"
    assert client.get(f"/api/transactions/{t['id']}").json()["tags"] == ["Holiday"]
    assert client.delete(f"/api/tags/{tid}").status_code == 204
    assert client.get(f"/api/transactions/{t['id']}").json()["tags"] == []
