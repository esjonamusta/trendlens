from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import history as history_db
from main import app

client = TestClient(app)


TOPIC_A = {
    "rank": 1,
    "headline": "AI agents rising",
    "keywords": ["ai", "agents"],
    "confidence": "High",
    "source_count": 10,
    "sources": [],
    "pm_action": "Act now",
    "weighted_evidence_score": 3.2,
    "canonical_topic_id": "abc123",
}

TOPIC_B = {
    "rank": 2,
    "headline": "OSS pricing",
    "keywords": ["oss", "pricing"],
    "confidence": "Medium",
    "source_count": 5,
    "sources": [],
    "pm_action": "Watch",
    "weighted_evidence_score": 1.5,
    "canonical_topic_id": "def456",
}


def test_get_timeline_returns_snapshots_with_topics(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(history_db, "DB_PATH", db_file)
    history_db.init_db()

    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("run1", "test-domain", "{}", "{}", json.dumps([TOPIC_A]), "2026-05-23T09:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("run2", "test-domain", "{}", "{}", json.dumps([TOPIC_A, TOPIC_B]), "2026-05-30T09:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    result = history_db.get_timeline("test-domain", days=30)
    assert len(result) == 2
    assert result[0]["run_id"] == "run2"  # most recent first
    assert len(result[0]["topics"]) == 2
    assert result[0]["topics"][0]["headline"] == "AI agents rising"
    assert result[0]["topics"][0]["weighted_evidence_score"] == 3.2


def test_get_timeline_filters_by_days(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(history_db, "DB_PATH", db_file)
    history_db.init_db()

    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("old-run", "test-domain", "{}", "{}", json.dumps([TOPIC_A]), "2025-01-01T00:00:00+00:00"),
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("new-run", "test-domain", "{}", "{}", json.dumps([TOPIC_B]), now_iso),
    )
    conn.commit()
    conn.close()

    result = history_db.get_timeline("test-domain", days=7)
    assert len(result) == 1
    assert result[0]["run_id"] == "new-run"


def test_get_timeline_filters_by_date_range(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(history_db, "DB_PATH", db_file)
    history_db.init_db()

    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("before", "test-domain", "{}", "{}", json.dumps([TOPIC_A]), "2026-05-01T09:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("inside", "test-domain", "{}", "{}", json.dumps([TOPIC_B]), "2026-05-15T09:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("after", "test-domain", "{}", "{}", json.dumps([TOPIC_A]), "2026-05-30T09:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    result = history_db.get_timeline(
        "test-domain",
        start_date="2026-05-10",
        end_date="2026-05-20",
    )
    assert len(result) == 1
    assert result[0]["run_id"] == "inside"


def test_timeline_endpoint_returns_200(tmp_path, monkeypatch):
    import app.db.history as history_db
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(history_db, "DB_PATH", db_file)
    history_db.init_db()

    response = client.get("/history/developer-experience/timeline?days=30")
    assert response.status_code == 200
    data = response.json()
    assert "snapshots" in data
    assert "domain" in data
    assert data["domain"] == "developer-experience"


def test_timeline_endpoint_returns_snapshots(tmp_path, monkeypatch):
    import app.db.history as history_db
    import json
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(history_db, "DB_PATH", db_file)
    history_db.init_db()

    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    topic = {
        "rank": 1, "headline": "AI agents rising", "keywords": ["ai"],
        "confidence": "High", "source_count": 10, "sources": [],
        "pm_action": "Act now", "weighted_evidence_score": 3.2,
        "canonical_topic_id": "abc123",
    }
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("run1", "developer-experience", "{}", "{}", json.dumps([topic]), now_iso),
    )
    conn.commit()
    conn.close()

    response = client.get("/history/developer-experience/timeline?days=30")
    assert response.status_code == 200
    data = response.json()
    assert len(data["snapshots"]) == 1
    assert data["snapshots"][0]["topics"][0]["headline"] == "AI agents rising"


def test_timeline_endpoint_accepts_date_range(tmp_path, monkeypatch):
    import app.db.history as history_db
    import json
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(history_db, "DB_PATH", db_file)
    history_db.init_db()

    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("run1", "developer-experience", "{}", "{}", json.dumps([TOPIC_A]), "2026-05-10T09:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO snapshots (run_id, domain, config_json, report_json, topics_json, created_at) VALUES (?,?,?,?,?,?)",
        ("run2", "developer-experience", "{}", "{}", json.dumps([TOPIC_B]), "2026-05-20T09:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    response = client.get("/history/developer-experience/timeline?start_date=2026-05-15&end_date=2026-05-25")
    assert response.status_code == 200
    data = response.json()
    assert [s["run_id"] for s in data["snapshots"]] == ["run2"]


def test_timeline_endpoint_rejects_partial_date_range():
    response = client.get("/history/developer-experience/timeline?start_date=2026-05-15")
    assert response.status_code == 400


def test_timeline_endpoint_rejects_inverted_date_range():
    response = client.get("/history/developer-experience/timeline?start_date=2026-05-20&end_date=2026-05-15")
    assert response.status_code == 400


def test_trend_feedback_endpoint_returns_204(tmp_path, monkeypatch):
    import app.db.history as history_db
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(history_db, "DB_PATH", db_file)
    history_db.init_db()

    response = client.post("/trend-feedback", json={
        "domain": "developer-experience",
        "item_headline": "AI agents rising",
        "feedback_type": "relevant",
    })
    assert response.status_code == 204
