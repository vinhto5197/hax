from starlette.requests import Request

from apps.api.auth import extract_token


def make_request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "method": "GET", "path": "/"})


def test_bearer_header_wins():
    request = make_request(
        {"authorization": "Bearer abc", "cookie": "authjs.session-token=cookie-tok"}
    )
    assert extract_token(request) == "abc"


def test_cookie_fallback():
    request = make_request({"cookie": "authjs.session-token=cookie-tok"})
    assert extract_token(request) == "cookie-tok"


def test_no_token_is_none():
    assert extract_token(make_request()) is None


def test_non_bearer_authorization_ignored():
    request = make_request({"authorization": "Basic Zm9v"})
    assert extract_token(request) is None
