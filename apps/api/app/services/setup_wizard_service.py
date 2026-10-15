"""Whether the self-host administrator has dismissed the first-run setup wizard."""

from app.db.repositories.instance_settings import instance_settings_repository
from app.models.runtime_models import SetupWizardSetting

SETUP_WIZARD_SETTING_KEY = "setup"


async def is_setup_wizard_dismissed() -> bool:
    """Return whether the admin skipped the wizard's AI provider step."""
    stored = await instance_settings_repository.find_by_key(SETUP_WIZARD_SETTING_KEY)
    if stored is None:
        return False
    return SetupWizardSetting.model_validate(stored.value).dismissed


async def dismiss_setup_wizard() -> None:
    """Record that the wizard no longer opens itself; the setup banner takes over."""
    await instance_settings_repository.set_value(
        SETUP_WIZARD_SETTING_KEY,
        SetupWizardSetting(dismissed=True).model_dump(mode="json"),  # pragma: no mutate — bool-only
    )
