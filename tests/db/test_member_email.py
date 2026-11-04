"""member_email: a route that already knows its user is a member reads the
email as `str`; an anonymous demo visitor (email None) is refused loudly
instead of flowing None into a string slot. A pure read of the model: the
users are transient, no database round trip."""

import pytest

from packages.db.models import User
from packages.db.repos.users import member_email


def test_member_email_returns_the_members_email():
    user = User(email="member@test.local")
    assert member_email(user) == "member@test.local"


def test_member_email_for_a_user_with_no_email_raises_value_error_naming_no_email():
    visitor = User(email=None)
    with pytest.raises(ValueError, match="no email"):
        member_email(visitor)
