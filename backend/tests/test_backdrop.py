"""World backdrops: the SVG sanitizer's accept/reject contract, the
failure-tolerant generator (both modes), and the column's round trip out
to the API."""

import base64
import copy
from types import SimpleNamespace

import httpx
import pytest

from app import db, worldgen
from app.worldgen import FALLBACK_BACKDROP, FALLBACK_WORLD, generate_backdrop, sanitize_svg

CLEAN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">'
    '<defs><radialGradient id="g"><stop offset="0%" stop-color="#111"/>'
    '</radialGradient></defs>'
    '<rect width="1920" height="1080" fill="url(#g)"/>'
    "</svg>"
)


def test_sanitizer_accepts_clean_svg_and_the_fallback_backdrop():
    assert sanitize_svg(CLEAN_SVG) == CLEAN_SVG
    assert sanitize_svg(FALLBACK_BACKDROP) == FALLBACK_BACKDROP


@pytest.mark.parametrize(
    "svg",
    [
        pytest.param("<svg><script>alert(1)</script></svg>", id="script"),
        pytest.param('<svg onload="alert(1)"><rect/></svg>', id="event-attr"),
        pytest.param("<svg><foreignObject><div>x</div></foreignObject></svg>", id="foreignObject"),
        pytest.param('<svg><a href="https://evil.example"><rect/></a></svg>', id="external-href"),
        pytest.param('<svg><use xlink:href="https://e.x/x.svg#a"/></svg>', id="external-xlink"),
        pytest.param('<svg><a href="javascript:alert(1)"><rect/></a></svg>', id="js-href"),
        pytest.param("<svg><rect></svg>", id="malformed-xml"),
        pytest.param(f'<svg>{"<rect/>" * 20000}</svg>', id="oversize"),
    ],
)
def test_sanitizer_rejects_active_or_broken_svg(svg):
    assert sanitize_svg(svg) is None


def _fake_client(text):
    async def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    return SimpleNamespace(messages=SimpleNamespace(create=create))


@pytest.mark.asyncio
async def test_generate_backdrop_extracts_and_sanitizes():
    client = _fake_client(f"Here is your backdrop:\n{CLEAN_SVG}\nEnjoy.")
    assert await generate_backdrop(client, "T", "C") == CLEAN_SVG


@pytest.mark.asyncio
async def test_generate_backdrop_returns_none_on_garbage():
    assert await generate_backdrop(_fake_client("no svg here"), "T", "C") is None
    # API blowing up must not raise either — a backdrop never costs a world.
    async def boom(**kwargs):
        raise RuntimeError("api down")

    client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    assert await generate_backdrop(client, "T", "C") is None


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fakepixels"


def _fake_httpx(monkeypatch, *, payload=None, exc=None):
    """Stand-in for httpx.AsyncClient used by the raster paths (SD and xAI)."""

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *excinfo):
            return False

        async def post(self, url, json=None, headers=None):
            if exc is not None:
                raise exc
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload or {})

    monkeypatch.setattr(worldgen.httpx, "AsyncClient", FakeAsyncClient)


@pytest.mark.asyncio
async def test_local_mode_returns_png_data_uri(world_db, monkeypatch):
    db.set_setting("backdrop_mode", "local")
    _fake_httpx(monkeypatch, payload={"images": [base64.b64encode(PNG_BYTES).decode()]})
    result = await generate_backdrop(_fake_client("unused"), "T", "C")
    assert result.startswith("data:image/png;base64,")
    assert base64.b64decode(result.split(",", 1)[1]) == PNG_BYTES


@pytest.mark.asyncio
async def test_local_mode_falls_back_to_svg_when_sd_unreachable(world_db, monkeypatch):
    db.set_setting("backdrop_mode", "local")
    _fake_httpx(monkeypatch, exc=httpx.ConnectError("connection refused"))
    result = await generate_backdrop(_fake_client(CLEAN_SVG), "T", "C")
    assert result == CLEAN_SVG


@pytest.mark.asyncio
async def test_local_mode_rejects_non_png_and_falls_back(world_db, monkeypatch):
    db.set_setting("backdrop_mode", "local")
    _fake_httpx(monkeypatch, payload={"images": [base64.b64encode(b"GIF89a not a png").decode()]})
    result = await generate_backdrop(_fake_client(CLEAN_SVG), "T", "C")
    assert result == CLEAN_SVG


JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"fakejpeg"


@pytest.mark.asyncio
async def test_grok_mode_returns_data_uri_with_sniffed_mime(world_db, monkeypatch):
    db.set_setting("backdrop_mode", "grok")
    monkeypatch.setenv("GROK_KEY", "test-key")
    _fake_httpx(
        monkeypatch, payload={"data": [{"b64_json": base64.b64encode(JPEG_BYTES).decode()}]}
    )
    result = await generate_backdrop(_fake_client("unused"), "T", "C")
    assert result.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(result.split(",", 1)[1]) == JPEG_BYTES


@pytest.mark.asyncio
async def test_grok_mode_without_key_falls_back_to_svg(world_db, monkeypatch):
    db.set_setting("backdrop_mode", "grok")
    monkeypatch.delenv("GROK_KEY", raising=False)
    result = await generate_backdrop(_fake_client(CLEAN_SVG), "T", "C")
    assert result == CLEAN_SVG


@pytest.mark.asyncio
async def test_grok_mode_api_error_falls_back_to_svg(world_db, monkeypatch):
    db.set_setting("backdrop_mode", "grok")
    monkeypatch.setenv("GROK_KEY", "test-key")
    _fake_httpx(monkeypatch, exc=httpx.HTTPStatusError("401", request=None, response=None))
    result = await generate_backdrop(_fake_client(CLEAN_SVG), "T", "C")
    assert result == CLEAN_SVG


def test_backdrop_round_trips_to_both_endpoints(client):
    # FALLBACK_WORLD (inserted by /games via the pool fake) carries the
    # hand-authored backdrop — it should surface on /worlds and /state.
    created = client.post(
        "/games", json={"name": "Thorin", "description": "a dwarf warrior"}
    ).json()
    state = client.get(
        f"/games/{created['game_id']}/state", params={"token": created["player_token"]}
    ).json()
    assert state["world_backdrop"] == FALLBACK_BACKDROP

    world_id = db.insert_world(copy.deepcopy(FALLBACK_WORLD))
    listed = client.get("/worlds").json()
    mine = next(w for w in listed if w["id"] == world_id)
    assert mine["backdrop_svg"] == FALLBACK_BACKDROP
