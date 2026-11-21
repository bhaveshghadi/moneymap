"""F20 Start-up guide: the checklist ticks itself from the data; steps can be ticked, skipped or
undone; the guide opens on sign-in until hidden or finished."""


def _steps(g):
    return {s["key"]: s for s in g["steps"]}


def test_empty_then_filling_in(client):
    g = client.get("/api/guide").json()
    assert g["show_first"] is True and g["hidden"] is False and g["done"] == 0
    steps = _steps(g)
    assert list(steps)[:3] == ["essentials", "banks", "cards"]
    assert steps["banks"]["detail"] == "None yet" and steps["banks"]["href"].startswith("/accounts")
    assert "marked Essential" in steps["essentials"]["detail"]  # the starter categories mark some

    client.post("/api/accounts", json={"name": "Bank A", "type": "asset", "opening_balance": 100})
    client.post("/api/accounts", json={"name": "Bank B", "type": "asset", "opening_balance": 100})
    client.post("/api/investments", json={"kind": "property", "name": "Village land", "amount": 500_000_00})
    steps = _steps(client.get("/api/guide").json())
    assert steps["banks"]["done"] and steps["banks"]["detail"] == "2 accounts added"
    assert steps["investments"]["done"] and "1 property" in steps["investments"]["detail"]
    assert not steps["funds"]["done"]


def test_tick_skip_undo_and_hide(client):
    g = client.post("/api/guide", json={"action": "check", "step": "essentials"}).json()
    assert _steps(g)["essentials"]["done"] and g["done"] == 1
    g = client.post("/api/guide", json={"action": "skip", "step": "cards"}).json()
    assert _steps(g)["cards"]["skipped"] and not _steps(g)["cards"]["done"]
    g = client.post("/api/guide", json={"action": "undo", "step": "cards"}).json()
    assert not _steps(g)["cards"]["skipped"]
    assert client.post("/api/guide", json={"action": "check", "step": "nope"}).status_code == 422

    g = client.post("/api/guide", json={"action": "hide"}).json()
    assert g["hidden"] and g["show_first"] is False
    g = client.post("/api/guide", json={"action": "show"}).json()
    assert g["show_first"] is True


def test_finished_when_every_step_done_or_skipped(client):
    client.post("/api/accounts", json={"name": "Bank", "type": "asset", "opening_balance": 100})
    for s in client.get("/api/guide").json()["steps"]:
        if s["key"] != "banks":
            client.post("/api/guide", json={"action": "skip" if s["optional"] else "check", "step": s["key"]})
    g = client.get("/api/guide").json()
    assert g["finished"] and g["show_first"] is False  # no longer opens on sign-in


def test_needs_login(anon):
    assert anon.get("/api/guide").status_code == 401
