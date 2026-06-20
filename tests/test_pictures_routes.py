"""Endpoint tests for the /api/pictures* routes.

A minimal FastAPI app carrying only the config router and an app-state config
(artwork.folder pointed at a tmp dir, auth configured) is enough to exercise
auth, listing, upload, rename, delete, thumbnail, and traversal rejection.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.config import AppConfig, ArtworkConfig, ServerConfig
from app.server.routes.config import router as config_router

_AUTH = ("admin", "secret")


def _jpeg_bytes(color: str = "green") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    pics = tmp_path / "pictures"
    pics.mkdir()
    config = AppConfig(
        server=ServerConfig(auth_username=_AUTH[0], auth_password=_AUTH[1]),
        artwork=ArtworkConfig(folder=str(pics)),
    )
    app = FastAPI()
    app.state.config = config
    app.state.config_path = tmp_path / "config.yaml"
    app.include_router(config_router)
    c = TestClient(app)
    c._pics_dir = pics  # type: ignore[attr-defined]
    return c


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


def test_list_requires_auth(client: TestClient):
    assert client.get("/api/pictures").status_code == 401


def test_upload_requires_auth(client: TestClient):
    r = client.post("/api/pictures/upload", files={"file": ("a.jpg", _jpeg_bytes(), "image/jpeg")})
    assert r.status_code == 401


# --------------------------------------------------------------------------
# Listing / upload / thumbnail
# --------------------------------------------------------------------------


def test_list_pictures(client: TestClient):
    (client._pics_dir / "seed.jpg").write_bytes(_jpeg_bytes())
    r = client.get("/api/pictures", auth=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert [p["name"] for p in body["pictures"]] == ["seed.jpg"]


def test_upload_happy_path(client: TestClient):
    r = client.post(
        "/api/pictures/upload",
        files={"file": ("up.jpg", _jpeg_bytes(), "image/jpeg")},
        auth=_AUTH,
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "name": "up.jpg"}
    assert (client._pics_dir / "up.jpg").is_file()


def test_upload_bad_content(client: TestClient):
    r = client.post(
        "/api/pictures/upload",
        files={"file": ("bad.jpg", b"not an image", "image/jpeg")},
        auth=_AUTH,
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_thumbnail_existing(client: TestClient):
    (client._pics_dir / "t.jpg").write_bytes(_jpeg_bytes())
    r = client.get("/api/pictures/thumbnail", params={"name": "t.jpg"}, auth=_AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "no-store"


def test_thumbnail_missing(client: TestClient):
    r = client.get("/api/pictures/thumbnail", params={"name": "ghost.jpg"}, auth=_AUTH)
    assert r.status_code == 404
    assert r.json()["ok"] is False


# --------------------------------------------------------------------------
# Rename
# --------------------------------------------------------------------------


def test_rename_happy_path(client: TestClient):
    (client._pics_dir / "old.jpg").write_bytes(_jpeg_bytes())
    r = client.post("/api/pictures/rename", data={"old": "old.jpg", "new": "new.jpg"}, auth=_AUTH)
    assert r.json() == {"ok": True, "name": "new.jpg"}
    assert (client._pics_dir / "new.jpg").is_file()


def test_rename_clobber_refused(client: TestClient):
    (client._pics_dir / "a.jpg").write_bytes(_jpeg_bytes())
    (client._pics_dir / "b.jpg").write_bytes(_jpeg_bytes())
    r = client.post("/api/pictures/rename", data={"old": "a.jpg", "new": "b.jpg"}, auth=_AUTH)
    assert r.status_code == 400
    assert r.json()["ok"] is False


# --------------------------------------------------------------------------
# Delete / traversal
# --------------------------------------------------------------------------


def test_delete_happy_path(client: TestClient):
    (client._pics_dir / "del.jpg").write_bytes(_jpeg_bytes())
    r = client.post("/api/pictures/delete", data={"name": "del.jpg"}, auth=_AUTH)
    assert r.json() == {"ok": True}
    assert not (client._pics_dir / "del.jpg").exists()


def test_delete_traversal_blocked(client: TestClient, tmp_path: Path):
    outside = tmp_path / "config.yaml"
    outside.write_text("secret: true")
    r = client.post(
        "/api/pictures/delete",
        data={"name": "../config.yaml"},
        auth=_AUTH,
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False
    # The file outside the folder must remain untouched.
    assert outside.is_file()
