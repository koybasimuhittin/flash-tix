"""POST /tickets through the real app, with local storage in a temp folder."""

import uuid

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from worker_svc.tickets import qr_content


def event(**overrides) -> dict:
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


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(storage):
    from worker_svc.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def test_renders_one_page_per_seat(client, storage):
    data = event()
    assert client.post("/tickets", json=data).status_code == 204
    pdf = PdfReader(storage / "tickets" / f"{data['booking_id']}.pdf")
    assert len(pdf.pages) == 2
    first = pdf.pages[0].extract_text()
    assert "Ayşe Gül Şahin" in first  # Turkish letters survive (Vera font, not Helvetica)
    assert "20 Dec 2026, 20:00" in first  # 17:00 UTC shown in Istanbul time
    assert "A-3-12" in first and "TRY 1,500.00" in first
    assert "A-3-13" in pdf.pages[1].extract_text()


def test_sending_the_same_booking_twice_rewrites_one_file(client, storage):
    data = event()
    assert client.post("/tickets", json=data).status_code == 204
    assert client.post("/tickets", json=data).status_code == 204
    files = [path.name for path in (storage / "tickets").iterdir()]
    assert files == [f"{data['booking_id']}.pdf"]  # no partial files left behind


@pytest.mark.parametrize(
    "body",
    [
        {"not": "an event"},
        event(version=2),
        event(type="booking.cancelled"),
        event(booking_id="../../etc/passwd"),
        event(seats=[]),
        {key: value for key, value in event().items() if key != "event"},
    ],
    ids=["garbage", "v2", "other-type", "path-traversal", "no-seats", "no-event"],
)
def test_invalid_events_are_rejected_and_nothing_is_written(client, storage, body):
    assert client.post("/tickets", json=body).status_code == 422
    assert not (storage / "tickets").exists()


def test_storage_failure_is_a_server_error_so_the_caller_retries(client, storage):
    (storage / "tickets").write_text("a file where the folder should be")
    assert client.post("/tickets", json=event()).status_code >= 500


def test_qr_content():
    booking = uuid.uuid4()
    assert qr_content(booking, "A-1-1") == f"FLASHTIX|{booking}|A-1-1"
