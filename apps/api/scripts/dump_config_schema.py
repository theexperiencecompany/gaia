import ast
import json
from pathlib import Path
import sys

# SettingsGroup(...) keyword -> JSON key, for the keywords whose value is a literal
_CONSTANT_KEYWORDS = {
    "name": "name",
    "description": "description",
    "affected_features": "affectedFeatures",
    "required_in_prod": "requiredInProd",
    "all_required": "allRequired",
    "docs_url": "docsUrl",
    "alternative_group": "alternativeGroup",
}


def extract_settings_validator(file_path):
    # dev tool that parses the settings module the operator points it at; no trust boundary crossed
    with Path(file_path).open() as f:  # NOSONAR pythonsecurity:S8707
        tree = ast.parse(f.read())

    groups = []

    class GroupVisitor(ast.NodeVisitor):
        def visit_Call(self, node):
            # Look for SettingsGroup(...) calls
            if isinstance(node.func, ast.Name) and node.func.id == "SettingsGroup":
                group = {
                    "requiredInProd": True,  # Default
                    "allRequired": True,  # Default
                    "variables": [],
                }

                for keyword in node.keywords:
                    key = keyword.arg
                    value = keyword.value
                    if key in _CONSTANT_KEYWORDS and isinstance(value, ast.Constant):
                        group[_CONSTANT_KEYWORDS[key]] = value.value
                    elif key == "keys" and isinstance(value, ast.List):
                        group["_keys"] = [
                            elt.value for elt in value.elts if isinstance(elt, ast.Constant)
                        ]

                groups.append(group)

            self.generic_visit(node)

    GroupVisitor().visit(tree)
    return groups


def _field_default(item: ast.AnnAssign) -> tuple[bool, object]:
    """Whether a settings field has a default (so needs no user input), and its literal value."""
    # an Optional[...] annotation alone is not a default: pydantic v2 still requires the field
    default_val = item.value.value if isinstance(item.value, ast.Constant) else None
    return item.value is not None, default_val


def extract_settings(file_path):
    # dev tool that parses the settings module the operator points it at; no trust boundary crossed
    with Path(file_path).open() as f:  # NOSONAR pythonsecurity:S8707
        tree = ast.parse(f.read())

    required_in_dev = set()
    defaults = {}

    class SettingsVisitor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            # CommonSettings fields are required unless DevelopmentSettings makes them optional
            if node.name not in ("CommonSettings", "DevelopmentSettings"):
                return
            for item in node.body:
                if not (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)):
                    continue
                var_name = item.target.id
                needs_no_input, default_val = _field_default(item)
                if isinstance(default_val, str):
                    defaults[var_name] = default_val
                if node.name == "CommonSettings" and not needs_no_input:
                    required_in_dev.add(var_name)
                elif node.name == "DevelopmentSettings" and needs_no_input:
                    required_in_dev.discard(var_name)

    SettingsVisitor().visit(tree)
    return required_in_dev, defaults


def main():
    if len(sys.argv) < 3:
        # Default paths relative to script location in apps/api/scripts
        base_dir = Path(__file__).resolve().parent.parent
        validator_path = base_dir / "app/config/settings_validator.py"
        settings_path = base_dir / "app/config/settings.py"
    else:
        validator_path = sys.argv[1]
        settings_path = sys.argv[2]

    groups = extract_settings_validator(validator_path)
    required_in_dev, defaults = extract_settings(settings_path)

    # Merge
    final_categories = []

    for group in groups:
        keys = group.pop("_keys", [])
        variables = []
        for key in keys:
            is_required = key in required_in_dev
            default_val = defaults.get(key)

            # Special case for some infrastructure defaults handled by CLI?
            # The CLI logic overrides defaults for infra vars.
            # But here we just report what the python code thinks.

            variables.append(
                {
                    "name": key,
                    "required": is_required,
                    "category": group.get("name"),
                    "description": group.get("description"),
                    "affectedFeatures": group.get("affectedFeatures"),
                    "defaultValue": default_val,
                    "docsUrl": group.get("docsUrl"),
                }
            )

        group["variables"] = variables
        final_categories.append(group)

    print(json.dumps(final_categories, indent=2))


if __name__ == "__main__":
    main()
