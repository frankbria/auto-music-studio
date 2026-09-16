"""The one way API tests create users (#423).

``subscription_tier`` defaults to **free** because that is what a real signup gets. A test
that wants Pro says so at the call site — never through a file-level default, which is how
a gated endpoint stops being tested as a free musician experiences it. Parametrized-by-
capability tests derive the tier from the parameter (see ``_tier_for`` in
``tests/test_clips_edit_api.py``).
"""

from acemusic.api.models import User
from acemusic.api.services import users as user_service
from acemusic.api.services.tiers import FREE


async def make_user(email: str, *, tier: str = FREE, **fields) -> User:
    """Create ``email`` as a Google-OAuth user at ``tier`` and set any other ``User`` fields.

    ``None`` values are skipped: tests pass optional kwargs straight through
    (``balance=None``), and in a throwaway database every user is freshly created, so
    "None" can only mean "leave the model default".
    """
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    fields["subscription_tier"] = tier
    for name, value in fields.items():
        if value is None:
            continue
        if name not in User.model_fields:
            raise AttributeError(f"User has no field {name!r}")
        setattr(user, name, value)
    await user.save()
    return user
