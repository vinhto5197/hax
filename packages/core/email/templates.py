"""Email copy. Params are URLs the API builds — never user-supplied text —
so bodies can't carry injected content; HTML still escapes them."""

import html
from dataclasses import dataclass


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


_IGNORE = "If you didn't request this, you can ignore this email."

_TEMPLATES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # name: (subject, text body with {params}, required params)
    "verify_email": (
        "Verify your hax email",
        "Confirm this address to finish setting up your hax account:\n\n{link}\n\n"
        "The link expires in 24 hours. If you didn't sign up for hax, don't "
        "confirm — someone may have entered your address by mistake. " + _IGNORE + "\n",
        ("link",),
    ),
    "reset_password": (
        "Reset your hax password",
        "Set a new password for your hax account:\n\n{link}\n\n"
        "The link expires in 1 hour. " + _IGNORE + "\n",
        ("link",),
    ),
    "account_exists": (
        "You already have a hax account",
        "Someone tried to sign up for hax with this address, but an account "
        "already exists.\n\nLog in: {login_url}\nForgot your password, or signed "
        "up with Google and want to add one: {reset_url}\n\n" + _IGNORE + "\n",
        ("login_url", "reset_url"),
    ),
}


def render(template: str, params: dict[str, str]) -> Rendered:
    subject, body, required = _TEMPLATES[template]
    missing = [k for k in required if k not in params]
    if missing:
        raise KeyError(f"{template}: missing params {missing}")
    text = body.format(**params)
    # Params are URLs (see module docstring): render them as anchors, not bare
    # escaped text, so the HTML body's links are clickable. quote=True so a
    # `"` in a URL can't break out of the href attribute.
    escaped = {k: html.escape(v, quote=True) for k, v in params.items()}
    anchors = {k: f'<a href="{v}">{v}</a>' for k, v in escaped.items()}
    html_body = (
        "<p>"
        + body.format(**anchors).replace("\n\n", "</p><p>").replace("\n", "<br>")
        + "</p>"
    )
    return Rendered(subject=subject, text=text, html=html_body)
