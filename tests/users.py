"""The one way tests create users (#423, #495).

``subscription_tier`` defaults to **free** because that is what a real signup gets. A test
that wants Pro says so at the call site — never through a file-level default, which is how
a gated endpoint stops being tested as a free musician experiences it. Parametrized-by-
capability tests derive the tier from the parameter (see ``_tier_for`` in
``tests/test_clips_edit_api.py``).
"""

from acemusic.api.models import User
from acemusic.api.services import users as user_service
from acemusic.api.services.tiers import FREE


async def make_user(email: str, *, tier: str = FREE, name: str = "T", **fields) -> User:
    """Create ``email`` as a Google-OAuth user named ``name`` at ``tier``, then set any other ``User`` fields.

    ``None`` values are skipped: tests pass optional kwargs straight through
    (``balance=None``), and in a throwaway database every user is freshly created, so
    "None" can only mean "leave the model default".
    """
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name=name)
    fields["subscription_tier"] = tier
    for field, value in fields.items():
        if value is None:
            continue
        if field not in User.model_fields:
            raise AttributeError(f"User has no field {field!r}")
        setattr(user, field, value)
    await user.save()
    return user
