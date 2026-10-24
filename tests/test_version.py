from app.config import settings


async def test_version_identifies_release(client, monkeypatch):
    monkeypatch.setattr(settings, "commit_sha", "a" * 40)
    monkeypatch.setattr(settings, "build_time", "2026-10-24T00:00:00Z")
    monkeypatch.setattr(settings, "actions_url", "https://github.com/Odysseus-cyber/Aegis-RAG/actions/runs/1")
    response = await client.get("/version")
    assert response.status_code == 200
    assert response.json() == {
        "name": "Aegis-RAG", "commit_sha": "a" * 40,
        "build_time": "2026-10-24T00:00:00Z",
        "actions_url": "https://github.com/Odysseus-cyber/Aegis-RAG/actions/runs/1",
    }
