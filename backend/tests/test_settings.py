"""Server-global settings: default, round trip, and input validation."""


def test_settings_default_and_round_trip(client):
    assert client.get("/settings").json() == {"backdrop_mode": "svg"}
    response = client.put("/settings", json={"backdrop_mode": "local"})
    assert response.status_code == 200
    assert client.get("/settings").json() == {"backdrop_mode": "local"}


def test_settings_rejects_unknown_mode(client):
    assert client.put("/settings", json={"backdrop_mode": "dalle"}).status_code == 422
