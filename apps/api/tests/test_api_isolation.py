"""Isolation over HTTP: the same guarantees as test_isolation.py, through the real API."""


async def _seed(client, headers):
    h = (await client.post("/holdings", headers=headers,
                           json={"ticker": "NVDA", "purchase_date": "2024-06-03", "shares": 10})).json()
    w = (await client.post("/watchlist", headers=headers, json={"ticker": "AMD", "note": "chip"})).json()
    m = (await client.post("/memories", headers=headers,
                           json={"kind": "preference", "content": "No oil stocks", "tags": ["oil"]})).json()
    return h, w, m


async def test_users_cannot_see_or_delete_each_others_data(client, invited_user):
    alice, _, _ = await invited_user()
    bob, _, _ = await invited_user()
    h, w, m = await _seed(client, alice)

    for path in ("/holdings", "/watchlist", "/memories"):
        assert (await client.get(path, headers=bob)).json() == []
    for path in (f"/holdings/{h['id']}", f"/watchlist/{w['id']}", f"/memories/{m['id']}"):
        assert (await client.delete(path, headers=bob)).status_code == 404   # not 403: existence isn't revealed
    for path in ("/holdings", "/watchlist", "/memories"):
        assert len((await client.get(path, headers=alice)).json()) == 1      # Alice's data untouched
    assert "NVDA" not in str((await client.get("/me/export", headers=bob)).json())


async def test_input_validation(client, invited_user):
    alice, _, _ = await invited_user()
    bad_holdings = [
        {"ticker": "NVDA", "purchase_date": "2024-06-03", "shares": 1, "amount": 5},  # both
        {"ticker": "NVDA", "purchase_date": "2999-01-01", "shares": 1},               # future
        {"ticker": "NV DA", "purchase_date": "2024-06-03", "shares": 1},              # bad ticker
        {"ticker": "NVDA", "purchase_date": "2024-06-03", "shares": -1},              # negative
        {"ticker": "NVDA", "purchase_date": "2024-06-03", "shares": 1, "user_id": "x"},  # unknown field
    ]
    for body in bad_holdings:
        assert (await client.post("/holdings", headers=alice, json=body)).status_code == 422
    assert (await client.delete("/holdings/not-a-uuid", headers=alice)).status_code == 422
    assert (await client.patch("/me/profile", headers=alice, json={"risk_tolerance": "extreme"})).status_code == 422


async def test_profile_and_watchlist_behaviour(client, invited_user):
    alice, _, _ = await invited_user()
    r = await client.patch("/me/profile", headers=alice, json={"risk_tolerance": "high", "interests": ["AI"]})
    assert r.json()["risk_tolerance"] == "high" and r.json()["interests"] == ["AI"]
    first = await client.post("/watchlist", headers=alice, json={"ticker": "amd", "note": "keep this"})
    again = await client.post("/watchlist", headers=alice, json={"ticker": "AMD", "note": "overwrite?"})
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["note"] == "keep this"


async def test_delete_account(client, invited_user):
    alice, _, _ = await invited_user()
    await _seed(client, alice)
    assert (await client.request("DELETE", "/me", headers=alice, json={"confirm": "nope"})).status_code == 422
    assert (await client.request("DELETE", "/me", headers=alice, json={"confirm": "DELETE"})).status_code == 204
    # still invited, so the next request starts a fresh, empty account
    for path in ("/holdings", "/watchlist", "/memories"):
        assert (await client.get(path, headers=alice)).json() == []