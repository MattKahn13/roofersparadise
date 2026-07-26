from roofersparadise.ingest import email_send


def test_send_email_builds_payload(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(email_send.httpx, "post", fake_post)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM", "a@x.com")
    ok = email_send.send_email("to@x.com", "subj", "body")
    assert ok is True
    assert captured["json"]["to"] == ["to@x.com"]
    assert captured["json"]["from"] == "a@x.com"
    assert captured["json"]["subject"] == "subj"
    assert "Bearer re_test" in captured["headers"]["Authorization"]


def test_send_email_no_key_returns_false(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("RESEND_FROM", "a@x.com")
    assert email_send.send_email("to@x.com", "s", "b") is False


def test_send_email_swallows_exceptions(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")
    monkeypatch.setattr(email_send.httpx, "post", boom)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM", "a@x.com")
    assert email_send.send_email("to@x.com", "s", "b") is False
