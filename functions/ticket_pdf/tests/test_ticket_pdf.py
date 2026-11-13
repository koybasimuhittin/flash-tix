"""ticket-pdf through functions-framework's real app, with local storage in a temp folder."""

import base64
import json
import uuid
from pathlib import Path

import functions_framework
import pytest
from pypdf import PdfReader

SOURCE = Path(__file__).resolve().parents[1] / "main.py"


def payload(**overrides) -> dict:
    data = {
        "type": "booking.confirmed",
        "version": 1,
        "booking_id": str(uuid.uuid4()),
        "user_id": 42,
        "buyer_email": "ayse@example.com",
        "buyer_name": "Ayşe Gül Şahin",
        "event": {
            "id": 7,
            "title": "Rock Night",
            "venue": "Big Hall",
            "city": "İstanbul",
            "starts_at": "2026-12-20T17:00:00+00:00",
        },
        "seats": [
            {"seat_id": "A-3-12", "section_name": "Front", "price_cents": 150_000},
            {"seat_id": "A-3-13", "section_name": "Front", "price_cents": 150_000},
        ],
        "total_price_cents": 300_000,
        "confirmed_at": "2026-11-13T18:00:00+00:00",
        "request_id": "req-1",
    }
    data.update(overrides)
    return data


def envelope(data) -> dict:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return {
        "message": {
            "data": base64.b64encode(raw).decode(),
            "attributes": {"type": "booking.confirmed", "version": "1", "request_id": "req-1"},
            "messageId": "1",
            "publishTime": "2026-11-13T18:00:00Z",
        },
        "subscription": "local/booking-confirmed-ticket-pdf",
    }


@pytest.fixture
def storage(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(storage):
    app = functions_framework.create_app(target="handle_push", source=str(SOURCE))
    return app.test_client()


def test_renders_one_page_per_seat(client, storage):
    data = payload()
    response = client.post("/", json=envelope(data))
    assert response.status_code == 204
    pdf = PdfReader(storage / "tickets" / f"{data['booking_id']}.pdf")
    assert len(pdf.pages) == 2
    first = pdf.pages[0].extract_text()
    assert "Ayşe Gül Şahin" in first  # Turkish letters survive (Vera font, not Helvetica)
    assert "20 Dec 2026, 20:00" in first  # 17:00 UTC shown in Istanbul time
    assert "A-3-12" in first and "TRY 1,500.00" in first
    assert "A-3-13" in pdf.pages[1].extract_text()


def test_redelivery_overwrites_the_same_file(client, storage):
    data = payload()
    assert client.post("/", json=envelope(data)).status_code == 204
    assert client.post("/", json=envelope(data)).status_code == 204
    files = list((storage / "tickets").iterdir())
    assert [f.name for f in files] == [f"{data['booking_id']}.pdf"]  # no partial files left


@pytest.mark.parametrize(
    "body",
    [
        {"not": "a push envelope"},
        envelope(b"not json"),
        envelope(payload(version=2)),
        envelope(payload(type="booking.cancelled")),
        envelope(payload(booking_id="../../etc/passwd")),
        envelope(payload(seats=[])),
        envelope({k: v for k, v in payload().items() if k != "event"}),
    ],
    ids=["no-envelope", "bad-json", "v2", "other-type", "path-traversal", "no-seats", "no-event"],
)
def test_invalid_messages_are_acked_and_ignored(client, storage, body):
    assert client.post("/", json=body).status_code == 204  # ack: never retry a poison message
    assert not (storage / "tickets").exists()


def test_storage_failure_returns_5xx_so_pubsub_retries(client, storage, monkeypatch):
    (storage / "tickets").write_text("a file where the folder should be")
    response = client.post("/", json=envelope(payload()))
    assert response.status_code >= 500


def test_get_is_a_healthcheck(client):
    assert client.get("/").status_code == 200
