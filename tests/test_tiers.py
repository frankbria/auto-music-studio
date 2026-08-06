"""US-26.2: the tier table itself.

Pure lookups, so these run without a database. The property that matters most is that
the table fails *closed* — every way of being not-quite-Pro must resolve to free.
"""

import pytest

from acemusic.api.services import tiers
from acemusic.api.services.tiers import Capability


class TestNormalise:
    @pytest.mark.parametrize(
        "value",
        [None, "", "free", "FREE", "Pro", "PRO", "premium", "pro ", " pro", "enterprise", "0"],
    )
    def test_anything_that_is_not_exactly_pro_is_free(self, value) -> None:
        # A typo in a database field must not hand out Pro. Case and whitespace included:
        # the frontend applies the same exact-match rule, and the two must not disagree.
        assert tiers.normalise(value) == tiers.FREE

    def test_pro_is_pro(self) -> None:
        assert tiers.normalise("pro") == tiers.PRO


class TestAllows:
    @pytest.mark.parametrize("capability", list(Capability))
    def test_pro_may_do_everything(self, capability) -> None:
        assert tiers.allows("pro", capability)

    @pytest.mark.parametrize("capability", list(Capability))
    def test_free_may_do_none_of_the_gated_capabilities(self, capability) -> None:
        assert not tiers.allows("free", capability)

    @pytest.mark.parametrize("capability", list(Capability))
    def test_an_unknown_tier_is_refused(self, capability) -> None:
        # Fails closed: an unrecognised tier gets the free ruleset, not a free pass.
        assert not tiers.allows("platinum", capability)
        assert not tiers.allows(None, capability)


class TestAllocations:
    def test_the_documented_monthly_allocations(self) -> None:
        assert tiers.monthly_allocation("free") == 50.0
        assert tiers.monthly_allocation("pro") == 500.0

    def test_an_unknown_tier_gets_the_free_allocation(self) -> None:
        # Not a KeyError, and not the Pro allowance.
        assert tiers.monthly_allocation("platinum") == 50.0
        assert tiers.monthly_allocation(None) == 50.0


class TestDescriptions:
    @pytest.mark.parametrize("capability", list(Capability))
    def test_every_capability_can_explain_itself(self, capability) -> None:
        # The 403 body carries these; a capability with no description would refuse
        # someone without telling them what they are missing.
        name, benefit = tiers.describe(capability)
        assert name and benefit
        # Reads as a label rather than a bare identifier — a leading digit is fine
        # ("1080p and 4K video"); a lowercase word means someone pasted the enum name.
        assert not name[0].islower(), f"{capability} name should read as a label: {name!r}"

    def test_every_capability_is_gated(self) -> None:
        # The free tier is defined by what it lacks, so a newly added capability is
        # locked by default. This fails if one is ever added outside _PRO_ONLY.
        for capability in Capability:
            assert not tiers.allows("free", capability), f"{capability} leaked to the free tier"
