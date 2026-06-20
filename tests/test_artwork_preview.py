"""Endpoint test for the /api/test-artwork dry-run preview.

``fetch_artwork`` is monkeypatched so the test never hits the network.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import app.renderer.components.artwork as artwork_mod
from app.config import AppConfig, ServerConfig
from app.server.routes.config import router as config_router

_AUTH = ("admin", "secret")


@pytest.fixture()
def client() -> TestClient:
    config = AppConfig(
        server=ServerConfig(auth_username=_AUTH[0], auth_password=_AUTH[1]),
    )
    app = FastAPI()
    app.state.config = config
    app.state.config_path = Path("/tmp/unused.yaml")
    app.include_router(config_router)
    return TestClient(app)


def test_test_artwork_success(client: TestClient, monkeypatch):
    def fake_fetch(width, height, query, *, eink_enhance=False, **kw):
        return Image.new("RGB", (width, height), "purple"), "Titolo, Artista (1900)"

    monkeypatch.setattr(artwork_mod, "fetch_artwork", fake_fetch)

    r = client.post("/api/test-artwork", data={"query": "mountain"}, auth=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["caption"] == "Titolo, Artista (1900)"
    assert body["image"].startswith("data:image/png;base64,")


def test_test_artwork_no_result(client: TestClient, monkeypatch):
    monkeypatch.setattr(artwork_mod, "fetch_artwork", lambda *a, **k: None)
    r = client.post("/api/test-artwork", data={"query": "zzz"}, auth=_AUTH)
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_test_artwork_requires_auth(client: TestClient):
    assert client.post("/api/test-artwork", data={"query": "x"}).status_code == 401
