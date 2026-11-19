"""The API's link to the Linked Accounts page is the one the web app and the bots use."""

import re

from app.constants.nurture import NURTURE_STEPS
from app.constants.platform_links import LINKED_ACCOUNTS_SETTINGS_PATH
from tests.helpers import REPO_ROOT

SHARED_ROUTES = REPO_ROOT / "libs/shared/ts/src/constants/routes.ts"


def test_linked_accounts_path_matches_the_shared_web_route() -> None:
    declared = re.search(r'LINKED_ACCOUNTS_SETTINGS_PATH = "([^"]+)"', SHARED_ROUTES.read_text())

    assert declared is not None
    assert declared.group(1) == LINKED_ACCOUNTS_SETTINGS_PATH


def test_channels_nurture_email_links_to_linked_accounts() -> None:
    channels = next(step for step in NURTURE_STEPS if step.key == "channels")

    assert channels.cta_path == LINKED_ACCOUNTS_SETTINGS_PATH
