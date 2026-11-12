from conftest import register


def test_register_login_me(client):
    h = register(client)
    assert client.get("/api/v1/auth/me", headers=h).json()["email"] == "asha@example.com"
    r = client.post("/api/v1/auth/login", json={"email": "ASHA@example.com", "password": "correct-horse-1"})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Asha"


def test_bad_credentials_and_validation(client):
    register(client)
    assert client.post("/api/v1/auth/login", json={"email": "asha@example.com", "password": "nope"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"}).status_code == 401
    dup = client.post("/api/v1/auth/register", json={"email": "asha@example.com", "password": "another-pass-1", "display_name": "X"})
    assert dup.status_code == 400
    weak = client.post("/api/v1/auth/register", json={"email": "b@example.com", "password": "short", "display_name": "B"})
    assert weak.status_code == 400
    bad = client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "long-enough-1", "display_name": "B"})
    assert bad.status_code == 400


def test_api_requires_token(client):
    assert client.get("/api/v1/business-cases").status_code == 401
    assert client.get("/api/v1/business-cases", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_tampered_or_expired_token_rejected(client, monkeypatch):
    from app.core import security
    h = register(client)
    token = h["Authorization"].split()[1]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token[:-3]}abc"}).status_code == 401
    monkeypatch.setenv("BIZAGENT_TOKEN_TTL_HOURS", "1")
    import jwt, datetime as dt
    expired = jwt.encode({"sub": "1", "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)},
                         "test-secret-key-not-for-production", algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    assert security.decode_access_token(token) is not None


def test_users_cannot_see_or_touch_each_others_data(client):
    a = register(client, "a@example.com", "A")
    b = register(client, "b@example.com", "B")
    case = client.post("/api/v1/business-cases", headers=a, json={"title": "Mine", "idea_description": "Secret idea"}).json()["id"]
    hyp = client.post(f"/api/v1/business-cases/{case}/hypotheses", headers=a,
                      json={"statement": "People will pay for this thing"}).json()["id"]
    assert client.get("/api/v1/business-cases", headers=b).json() == []
    for method, url in [
        ("get", f"/api/v1/business-cases/{case}"), ("get", f"/api/v1/business-cases/{case}/hypotheses"),
        ("get", f"/api/v1/business-cases/{case}/overview"), ("get", f"/api/v1/business-cases/{case}/brief.pdf"),
        ("get", f"/api/v1/business-cases/{case}/sprints"), ("delete", f"/api/v1/business-cases/{case}"),
        ("get", f"/api/v1/hypotheses/{hyp}/evidence"), ("post", f"/api/v1/business-cases/{case}/scan"),
    ]:
        assert getattr(client, method)(url, headers=b).status_code == 404, (method, url)
    assert client.patch(f"/api/v1/business-cases/{case}", headers=b, json={"title": "Hijacked"}).status_code == 404
    assert client.get(f"/api/v1/business-cases/{case}", headers=a).json()["title"] == "Mine"


def test_sprint_endpoints_are_owner_scoped(client, live):
    b = register(client, "b@example.com", "B")
    sid = live["id"]
    for method, url in [("get", f"/api/v1/sprints/{sid}"), ("post", f"/api/v1/sprints/{sid}/pause"),
                        ("get", f"/api/v1/sprints/{sid}/signups"), ("get", f"/api/v1/sprints/{sid}/signups.csv"),
                        ("post", f"/api/v1/sprints/{sid}/conclude"), ("delete", f"/api/v1/sprints/{sid}"),
                        ("get", f"/api/v1/sprints/{sid}/preview")]:
        assert getattr(client, method)(url, headers=b).status_code == 404, (method, url)


def test_delete_account_removes_everything(client, factory, auth, live):
    from sqlalchemy import func, select
    from app.domain.models import BusinessCase, Sprint, User
    assert client.delete("/api/v1/auth/me", headers=auth).status_code == 204
    with factory() as s:
        assert s.scalar(select(func.count(User.id))) == 0
        assert s.scalar(select(func.count(BusinessCase.id))) == 0
        assert s.scalar(select(func.count(Sprint.id))) == 0


def test_registration_can_be_closed(client, monkeypatch):
    monkeypatch.setenv("BIZAGENT_ALLOW_REGISTRATION", "false")
    r = client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "long-enough-1", "display_name": "A"})
    assert r.status_code == 403


def test_rate_limit_blocks_repeated_logins(client, monkeypatch):
    from app.core import ratelimit
    monkeypatch.setenv("BIZAGENT_RATE_LIMIT", "on")
    ratelimit.reset()
    codes = [client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "bad"}).status_code for _ in range(12)]
    assert 429 in codes and codes[0] == 401
    ratelimit.reset()
