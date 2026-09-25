"""A run's credentials: typed only on the task's sites, never read back by a model or a person."""

import pytest

from app.constants.browser import JEV_SECRET_MASK
from app.services.browser.jev.secrets import RunSecrets

pytestmark = pytest.mark.unit

PASSWORD = "p@ss word+1"


def _secrets() -> RunSecrets:
    return RunSecrets({"password": PASSWORD, "empty": ""}, ["www.Example.test"])


def test_a_placeholder_opens_its_value_only_on_the_tasks_sites() -> None:
    secrets = _secrets()

    assert secrets.value_for("<secret>password</secret>", "https://example.test/login") == PASSWORD
    assert secrets.value_for("<secret>password</secret>", "https://sso.example.test/") == PASSWORD
    assert secrets.value_for("<secret>password</secret>", "https://evil.test/example.test") is None
    assert secrets.value_for("<secret>unknown</secret>", "https://example.test/") is None
    assert secrets.names == ["password"]


def test_a_model_reads_the_placeholder_and_a_person_the_mask_in_every_form_a_url_carries() -> None:
    secrets = _secrets()
    url = "https://example.test/done?pw=p%40ss+word%2B1&raw=p%40ss%20word%2B1"

    assert PASSWORD not in secrets.mask(f"typed {PASSWORD}")
    assert "<secret>password</secret>" in secrets.mask(f"typed {PASSWORD}")
    assert (
        secrets.redact(url)
        == f"https://example.test/done?pw={JEV_SECRET_MASK}&raw={JEV_SECRET_MASK}"
    )
    assert secrets.redact("<secret>password</secret>") == JEV_SECRET_MASK


def test_a_password_the_task_spelled_out_is_hidden_from_people_once_it_is_typed() -> None:
    secrets = RunSecrets({}, ["example.test"])
    landing = "submitted-form.html?my-text=Aryan&my-password=gaia-test-123"
    assert "gaia-test-123" in secrets.redact(landing)

    secrets.learn("gaia-test-123")

    assert (
        secrets.redact(landing)
        == f"submitted-form.html?my-text=Aryan&my-password={JEV_SECRET_MASK}"
    )


def test_learning_a_placeholder_or_nothing_changes_nothing() -> None:
    secrets = _secrets()

    secrets.learn("<secret>password</secret>")
    secrets.learn("")

    assert secrets.redact("Aryan") == "Aryan"


def test_the_agent_fills_placeholders_only_on_the_tasks_sites() -> None:
    assert _secrets().sensitive_data() == {
        "https://example.test": {"password": PASSWORD},
        "https://*.example.test": {"password": PASSWORD},
    }
    assert RunSecrets({}, ["example.test"]).sensitive_data() == {}
