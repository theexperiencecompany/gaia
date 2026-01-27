#!/usr/bin/env python3
"""
Script to refactor repeated "Get Started with GAIA" sections into a reusable snippet.
This extracts the section to snippets/get-started.mdx and replaces all occurrences
with <Snippet file="get-started.mdx" />
"""

import os
import re
from pathlib import Path

# Define the snippet content
SNIPPET_CONTENT = """## Get Started with GAIA

Ready to experience AI-powered productivity? GAIA is available as a hosted service or self-hosted solution.

**Try GAIA Today:**
- 🌐 [heygaia.io](https://heygaia.io) - Start using GAIA in minutes
- 💻 [GitHub Repository](https://github.com/theexperiencecompany/gaia) - Self-host or contribute to the project
- 🏢 [The Experience Company](https://experience.heygaia.io) - Learn about the team building GAIA

GAIA is open source and privacy-first. Your data stays yours, whether you use our hosted service or run it on your own infrastructure.
"""

# The import and reference that will replace the content
SNIPPET_IMPORT = 'import GetStarted from "/snippets/get-started.mdx";'
SNIPPET_REFERENCE = "<GetStarted />"


def create_snippet_file(docs_dir: Path):
    """Create the snippet file in the snippets directory."""
    snippet_path = docs_dir / "snippets" / "get-started.mdx"

    print(f"Creating snippet file: {snippet_path}")
    with open(snippet_path, "w") as f:
        f.write(SNIPPET_CONTENT)

    print(f"✓ Snippet created at {snippet_path}")
    return snippet_path


def find_mdx_files(docs_dir: Path):
    """Find all .mdx files in the docs directory."""
    return list(docs_dir.rglob("*.mdx"))


def replace_in_file(file_path: Path):
    """Replace the "Get Started with GAIA" section with snippet reference in a file."""
    with open(file_path, "r") as f:
        content = f.read()

    # Pattern to match the entire "Get Started with GAIA" section
    # This pattern matches the section starting with ## Get Started with GAIA
    # through the end of the content (including the separator line if present)
    pattern = re.compile(
        r"\n---\n\n## Get Started with GAIA\n\n"
        r"Ready to experience AI-powered productivity\? GAIA is available as a hosted service or self-hosted solution\.\n\n"
        r"\*\*Try GAIA Today:\*\*\n"
        r"- 🌐 \[heygaia\.io\]\(https://heygaia\.io\) - Start using GAIA in minutes\n"
        r"- 💻 \[GitHub Repository\]\(https://github\.com/theexperiencecompany/gaia\) - Self-host or contribute to the project\n"
        r"- 🏢 \[The Experience Company\]\(https://experience\.heygaia\.io\) - Learn about the team building GAIA\n\n"
        r"GAIA is open source and privacy-first\. Your data stays yours, whether you use our hosted service or run it on your own infrastructure\.",
        re.MULTILINE,
    )

    # Check if the pattern exists
    if pattern.search(content):
        # Replace with the snippet reference
        new_content = pattern.sub(f"\n---\n\n{SNIPPET_REFERENCE}", content)

        # Add import statement after frontmatter if not already present
        if SNIPPET_IMPORT not in new_content:
            # Find the end of frontmatter (---...---) and insert import after it
            frontmatter_end = re.search(
                r"^---\n.*?\n---\n", new_content, re.MULTILINE | re.DOTALL
            )
            if frontmatter_end:
                insert_pos = frontmatter_end.end()
                new_content = (
                    new_content[:insert_pos]
                    + f"\n{SNIPPET_IMPORT}\n"
                    + new_content[insert_pos:]
                )

        # Write back to file
        with open(file_path, "w") as f:
            f.write(new_content)

        return True

    return False


def main():
    """Main function to orchestrate the refactoring."""
    # Get the docs directory
    script_dir = Path(__file__).parent
    docs_dir = script_dir.parent

    print(f"Working in docs directory: {docs_dir}")
    print()

    # Step 1: Create the snippet file
    snippet_path = create_snippet_file(docs_dir)
    print()

    # Step 2: Find all .mdx files
    print("Finding all .mdx files...")
    mdx_files = find_mdx_files(docs_dir)
    # Exclude the snippet file itself
    mdx_files = [f for f in mdx_files if "snippets" not in str(f)]
    print(f"Found {len(mdx_files)} .mdx files to process")
    print()

    # Step 3: Replace in each file
    print("Replacing content with snippet references...")
    replaced_count = 0
    replaced_files = []

    for file_path in mdx_files:
        if replace_in_file(file_path):
            replaced_count += 1
            relative_path = file_path.relative_to(docs_dir)
            replaced_files.append(str(relative_path))
            print(f"✓ Replaced in: {relative_path}")

    print()
    print("=" * 60)
    print(f"✓ Refactoring complete!")
    print(f"  - Created snippet: snippets/get-started.mdx")
    print(f"  - Updated {replaced_count} files")
    print("=" * 60)

    if replaced_files:
        print()
        print("Files updated:")
        for file in replaced_files:
            print(f"  - {file}")


if __name__ == "__main__":
    main()
