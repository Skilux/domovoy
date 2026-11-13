import pytest

from domovoy.store_names import store_name


def test_unset_suffix_keeps_the_demo_actor_names():
    assert store_name("domovoy-property-ids", {}) == "domovoy-property-ids"


def test_suffix_gives_the_public_actor_its_own_stores():
    assert store_name("domovoy-extraction-cache", {"DOMOVOY_STORE_SUFFIX": "-public"}) == "domovoy-extraction-cache-public"


@pytest.mark.parametrize("bad", ["public", "-Public", "-pub lic", "-x/y"])
def test_invalid_suffix_fails_clearly(bad):
    with pytest.raises(ValueError, match="DOMOVOY_STORE_SUFFIX"):
        store_name("domovoy-profile-state", {"DOMOVOY_STORE_SUFFIX": bad})
