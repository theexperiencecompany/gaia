import ast
import json
import os
import sys


def extract_settings_validator(file_path):
    with open(file_path, "r") as f:
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

                # Parse arguments
                for keyword in node.keywords:
                    key = keyword.arg
                    value = keyword.value

                    if key == "name":
                        if isinstance(value, ast.Constant):  # Python 3.8+
                            group["name"] = value.value
                        elif isinstance(value, ast.Str):
                            group["name"] = value.s
                    elif key == "description":
                        if isinstance(value, ast.Constant):
                            group["description"] = value.value
                        elif isinstance(value, ast.Str):
                            group["description"] = value.s
                    elif key == "affected_features":
                        if isinstance(value, ast.Constant):
                            group["affectedFeatures"] = value.value
                        elif isinstance(value, ast.Str):
                            group["affectedFeatures"] = value.s
                    elif key == "required_in_prod":
                        if isinstance(value, ast.Constant):
                            group["requiredInProd"] = value.value
                        elif isinstance(value, ast.NameConstant):  # Python 3.7
                            group["requiredInProd"] = value.value
                    elif key == "all_required":
                        if isinstance(value, ast.Constant):
                            group["allRequired"] = value.value
                        elif isinstance(value, ast.NameConstant):
                            group["allRequired"] = value.value
                    elif key == "docs_url":
                        if isinstance(value, ast.Constant):
                            group["docsUrl"] = value.value
                        elif isinstance(value, ast.Str):
                            group["docsUrl"] = value.s
                    elif key == "alternative_group":
                        if isinstance(value, ast.Constant):
                            group["alternativeGroup"] = value.value
                        elif isinstance(value, ast.Str):
                            group["alternativeGroup"] = value.s
                    elif key == "keys":
                        # List of strings
                        if isinstance(value, ast.List):
                            keys = []
                            for elt in value.elts:
                                if isinstance(elt, ast.Constant):
                                    keys.append(elt.value)
                                elif isinstance(elt, ast.Str):
                                    keys.append(elt.s)
                            group["_keys"] = keys

                groups.append(group)

            self.generic_visit(node)

    GroupVisitor().visit(tree)
    return groups


def extract_settings(file_path):
    with open(file_path, "r") as f:
        tree = ast.parse(f.read())

    required_in_dev = set()
    defaults = {}

    class SettingsVisitor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            # DevelopmentSettings or CommonSettings
            # We treat CommonSettings variables as required unless overridden/optional in DevelopmentSettings
            # But simpler logic: Look at DevelopmentSettings. If a field has Optional[...] type or None default, it's optional.

            # Note: We need to traverse CommonSettings too because DevelopmentSettings inherits from it.
            # But the 'field info' logic in env-parser.ts relied on REQUIRED_IN_DEV set manually.
            # Here we want to know: "Is it required for the app to start in DEV mode?"

            if node.name in ["CommonSettings", "DevelopmentSettings"]:
                for body_item in node.body:
                    if isinstance(body_item, ast.AnnAssign):
                        target = body_item.target
                        if isinstance(target, ast.Name):
                            var_name = target.id

                            # Check annotation for Optional
                            is_optional = False
                            # Optional[str] is usually Subscript(value=Name(Optional), slice=...)
                            # Or Union[str, None]
                            if isinstance(body_item.annotation, ast.Subscript):
                                if (
                                    isinstance(body_item.annotation.value, ast.Name)
                                    and body_item.annotation.value.id == "Optional"
                                ):
                                    is_optional = True

                            # Check default value
                            has_default = body_item.value is not None
                            default_val = None
                            if has_default:
                                if isinstance(body_item.value, ast.Constant):
                                    default_val = body_item.value.value
                                    if default_val is None:
                                        is_optional = True
                                elif isinstance(body_item.value, ast.Str):
                                    default_val = body_item.value.s
                                # If default is not None, effectively optional (has fallback)
                                # But we want to know if USER INPUT is required.
                                # If default is "", maybe required?

                            if node.name == "DevelopmentSettings":
                                if is_optional or has_default:
                                    # Not strictly required input
                                    if var_name in required_in_dev:
                                        required_in_dev.remove(var_name)

                                    # Store default if string
                                    if isinstance(default_val, str):
                                        defaults[var_name] = default_val
                                else:
                                    # Required in Dev?
                                    # If it was in CommonSettings as required, it stays required.
                                    pass

                            elif node.name == "CommonSettings":
                                # Assume required unless overridden in Dev
                                if not (is_optional or has_default):
                                    required_in_dev.add(var_name)
                                else:
                                    if isinstance(default_val, str):
                                        defaults[var_name] = default_val

    SettingsVisitor().visit(tree)
    return required_in_dev, defaults


def main():
    if len(sys.argv) < 3:
        # Default paths relative to script location in apps/api/scripts
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        validator_path = os.path.join(base_dir, "app/config/settings_validator.py")
        settings_path = os.path.join(base_dir, "app/config/settings.py")
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
