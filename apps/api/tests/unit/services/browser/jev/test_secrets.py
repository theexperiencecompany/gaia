"""A run's credentials: each typed only on its own site, never read back by a model or a person."""

import pytest

from app.constants.browser import JEV_SECRET_MASK
from app.schemas.browser_job import BrowserTaskSecret
from app.services.browser.jev.secrets import RunSecrets, SecretWithheld

pytestmark = pytest.mark.unit

PASSWORD = "p@ss word+1"


def _secrets(**values: str) -> RunSecrets:
    return RunSecrets(
        {
            name: BrowserTaskSecret(value=value, site="example.test")
            for name, value in values.items()
        }
    )


def test_each_placeholder_opens_its_value_only_on_its_own_site() -> None:
    secrets = RunSecrets(
        {
            "password": BrowserTaskSecret(value=PASSWORD, site="https://www.Example.test/login"),
            "pin": BrowserTaskSecret(value="1234", site="bank.test"),
            "empty": BrowserTaskSecret(value="", site="example.test"),
        }
    )

    assert secrets.value_for("<secret>password</secret>", "https://example.test/login") == PASSWORD
    assert secrets.value_for("<secret>password</secret>", "https://sso.example.test/") == PASSWORD
    assert secrets.value_for("<secret>pin</secret>", "https://bank.test/") == "1234"
    for placeholder, url in [
        ("<secret>password</secret>", "https://bank.test/"),
        ("<secret>pin</secret>", "https://example.test/"),
        ("<secret>password</secret>", "https://evil.test/example.test"),
        ("<secret>password</secret>", "about:blank"),
        ("<secret>unknown</secret>", "https://example.test/"),
    ]:
        with pytest.raises(SecretWithheld, match=r"<secret>\w+</secret>"):
            secrets.value_for(placeholder, url)
    assert secrets.names == ["password", "pin"]


def test_a_site_that_names_no_host_is_refused() -> None:
    with pytest.raises(ValueError, match="names no site"):
        BrowserTaskSecret(value=PASSWORD, site="https://")


def test_the_agent_fills_each_placeholder_only_on_its_own_site() -> None:
    secrets = RunSecrets(
        {
            "password": BrowserTaskSecret(value=PASSWORD, site="example.test"),
            "user": BrowserTaskSecret(value="ada", site="example.test"),
            "pin": BrowserTaskSecret(value="1234", site="bank.test"),
        }
    )

    assert secrets.sensitive_data() == {
        "https://example.test": {"password": PASSWORD, "user": "ada"},
        "https://*.example.test": {"password": PASSWORD, "user": "ada"},
        "https://bank.test": {"pin": "1234"},
        "https://*.bank.test": {"pin": "1234"},
    }
    assert RunSecrets({}).sensitive_data() == {}


def test_a_model_reads_the_placeholder_and_a_person_the_mask_in_every_form_a_url_carries() -> None:
    secrets = _secrets(password=PASSWORD)
    url = "https://example.test/done?pw=p%40ss+word%2B1&raw=p%40ss%20word%2B1"

    assert secrets.mask(f"typed {PASSWORD}") == "typed <secret>password</secret>"
    assert (
        secrets.redact(url)
        == f"https://example.test/done?pw={JEV_SECRET_MASK}&raw={JEV_SECRET_MASK}"
    )
    assert secrets.redact("<secret>password</secret>") == JEV_SECRET_MASK


def test_masking_twice_leaves_a_placeholder_whole_even_when_it_holds_a_value() -> None:
    secrets = _secrets(admin="admin")

    once = secrets.mask("signed in as admin")

    assert secrets.mask(once) == once == "signed in as <secret>admin</secret>"


def test_a_text_cut_inside_a_value_keeps_no_prefix_of_it() -> None:
    secrets = _secrets(password="hunter2-secret")

    assert secrets.excerpt("welcome back hunter2-se", cut=True) == "welcome back "
    assert secrets.excerpt("welcome back hunter2-secret", cut=True) == (
        "welcome back <secret>password</secret>"
    )
    assert secrets.excerpt("a hunter", cut=False) == "a hunter"


def test_a_password_the_task_spelled_out_is_hidden_from_people_once_it_is_typed() -> None:
    secrets = RunSecrets({})
    landing = "submitted-form.html?my-text=Aryan&my-password=gaia-test-123"
    assert "gaia-test-123" in secrets.redact(landing)

    secrets.learn("gaia-test-123")

    assert (
        secrets.redact(landing)
        == f"submitted-form.html?my-text=Aryan&my-password={JEV_SECRET_MASK}"
    )


def test_learning_a_placeholder_or_nothing_changes_nothing() -> None:
    secrets = _secrets(password=PASSWORD)

    secrets.learn("<secret>password</secret>")
    secrets.learn("")

    assert secrets.redact("Aryan") == "Aryan"


def test_a_secret_inside_a_longer_one_never_splits_it() -> None:
    secrets = _secrets(password="a-secret-x", pin="secret")

    assert secrets.mask("typed a-secret-x") == "typed <secret>password</secret>"
    assert secrets.redact("typed a-secret-x") == f"typed {JEV_SECRET_MASK}"
    secrets.learn("b-a-secret-x-c")
    assert secrets.redact("typed b-a-secret-x-c") == f"typed {JEV_SECRET_MASK}"


def test_a_secret_that_starts_a_longer_one_never_cuts_it_short() -> None:
    secrets = _secrets(password="hunter2-long", pin="hunter2")

    assert secrets.mask("hunter2-long") == "<secret>password</secret>"
    assert secrets.redact("hunter2-long and hunter2") == f"{JEV_SECRET_MASK} and {JEV_SECRET_MASK}"
