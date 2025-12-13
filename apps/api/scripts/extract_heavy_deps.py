#!/usr/bin/env python3
import tomli

# Load pyproject.toml
with open("pyproject.toml", "rb") as f:
    data = tomli.load(f)

# Extract heavy dependencies
try:
    heavy_deps = data.get("dependency-groups", {}).get("heavy", [])

    if not heavy_deps:
        print("No heavy dependencies found in pyproject.toml")
        heavy_deps = []

    # Write them to a file
    with open("heavy-deps.txt", "w") as out:
        out.write("\n".join(heavy_deps))

    print(f"Extracted {len(heavy_deps)} heavy dependencies.")

except Exception as e:
    print(f"Error extracting heavy dependencies: {e}")
    with open("heavy-deps.txt", "w") as out:
        out.write("# Error extracting dependencies")
