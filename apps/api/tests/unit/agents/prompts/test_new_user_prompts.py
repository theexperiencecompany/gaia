"""The hand-written new-user playbooks must not drift from the real catalogue.

``NEED_PLAYBOOKS`` names integration ids inline, in prose, and nothing else
checks them: a renamed or removed id leaves the model telling a brand-new user
to connect something that cannot be connected, on their very first reply.
"""

import re

from app.agents.prompts.new_user_prompts import NEED_PLAYBOOKS
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.user_models import OnboardingNeed

#: The playbooks quote ids as 'gmail', 'googlecalendar', 'slack'. A quoted run
#: of lowercase letters is always an id: prose in this block never quotes a
#: single bare word.
_QUOTED_ID = re.compile(r"'([a-z]+)'")

_AVAILABLE_IDS = {item.id for item in OAUTH_INTEGRATIONS if item.available}


def test_every_id_named_in_a_playbook_is_a_connectable_integration() -> None:
    quoted = {
        (need, match) for need, text in NEED_PLAYBOOKS.items() for match in _QUOTED_ID.findall(text)
    }
    assert quoted, "no integration ids found: the regex no longer matches the playbooks"

    unknown = sorted(f"{need.value}: {name}" for need, name in quoted if name not in _AVAILABLE_IDS)
    assert not unknown, f"playbooks name ids that are not connectable: {unknown}"


def test_every_onboarding_need_has_a_playbook() -> None:
    missing = sorted(need.value for need in OnboardingNeed if need not in NEED_PLAYBOOKS)
    assert not missing, f"needs with no playbook: {missing}"
