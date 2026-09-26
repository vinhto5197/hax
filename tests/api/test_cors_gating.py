import importlib


def _reload_main(monkeypatch, origins):
    if origins is None:
        monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", origins)
    import apps.api.main as main

    return importlib.reload(main)


def _has_cors(app) -> bool:
    return any(m.cls.__name__ == "CORSMiddleware" for m in app.user_middleware)


def test_cors_is_installed_only_when_configured(monkeypatch):
    assert _has_cors(_reload_main(monkeypatch, "http://localhost:3000").app)
    assert not _has_cors(_reload_main(monkeypatch, None).app)
    # Leave the module with CORS installed, as a dev process would have it.
    _reload_main(monkeypatch, "http://localhost:3000")
