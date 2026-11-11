"""Print the CLI's config schema: the settings groups, with requiredness from the capability table.

`mise cli:schema` writes it to packages/cli/src/lib/api-config-schema.generated.json;
the api-schema CI lane regenerates it and fails on drift.
"""

import json
from typing import TypedDict

from app.config.capability_requirements import required_keys
from app.config.deployment import DeploymentKind, baseline_profile
from app.config.settings_validator import SettingsGroup, SettingsValidator


class _Variable(TypedDict):
    name: str
    required: bool
    category: str
    description: str
    affectedFeatures: str
    docsUrl: str | None


class _Category(TypedDict):
    name: str
    description: str
    affectedFeatures: str
    requiredInProd: bool
    allRequired: bool
    docsUrl: str | None
    alternativeGroup: str | None
    selfhostSetup: bool
    variables: list[_Variable]


def _category(group: SettingsGroup, required_everywhere: frozenset[str]) -> _Category:
    return {
        "name": group.name,
        "description": group.description,
        "affectedFeatures": group.affected_features,
        "requiredInProd": group.required_in(baseline_profile(DeploymentKind.PRODUCTION)),
        "allRequired": group.all_required,
        "docsUrl": group.docs_url,
        "alternativeGroup": group.alternative_group,
        "selfhostSetup": group.selfhost_setup,
        "variables": [
            {
                "name": key,
                "required": key in required_everywhere,
                "category": group.name,
                "description": group.description,
                "affectedFeatures": group.affected_features,
                "docsUrl": group.docs_url,
            }
            for key in group.keys
        ],
    }


def main() -> None:
    required_everywhere = frozenset.intersection(
        *(required_keys(baseline_profile(kind)) for kind in DeploymentKind)
    )
    categories = [_category(group, required_everywhere) for group in SettingsValidator().groups]
    print(json.dumps(categories, indent=2))


if __name__ == "__main__":
    main()
