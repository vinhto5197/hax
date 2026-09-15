import pytest

from packages.core.email import templates


@pytest.mark.parametrize("name", ["verify_email", "reset_password"])
def test_link_templates_include_link_and_expiry(name):
    r = templates.render(name, {"link": "http://app/x?token=abc"})
    assert "http://app/x?token=abc" in r.text
    assert "http://app/x?token=abc" in r.html
    assert r.subject
    assert ("24 hours" in r.text) == (name == "verify_email")
    assert ("1 hour" in r.text) == (name == "reset_password")


def test_account_exists_mentions_both_paths():
    r = templates.render(
        "account_exists",
        {"login_url": "http://app/login", "reset_url": "http://app/fp"},
    )
    assert "http://app/login" in r.text and "http://app/fp" in r.text


def test_unknown_template_rejected():
    with pytest.raises(KeyError):
        templates.render("nope", {})


def test_missing_param_rejected():
    with pytest.raises(KeyError):
        templates.render("verify_email", {})


def test_html_escapes_params():
    r = templates.render("verify_email", {"link": "http://a/?t=<b>"})
    assert "<b>" not in r.html and "&lt;b&gt;" in r.html
    assert 'href="http://a/?t=&lt;b&gt;"' in r.html
