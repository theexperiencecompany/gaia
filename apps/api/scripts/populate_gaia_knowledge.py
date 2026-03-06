#!/usr/bin/env python
"""
Populate GAIA's knowledge base in ChromaDB from content.md file.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Initialize settings and providers
from app.config.settings import settings  # noqa: F401

# Import chromadb module so @lazy_provider decorators register all providers
from app.db.chroma.chromadb import init_chromadb_constructor  # noqa: F401

# Create actual embedding instance and register it (not lazy)
from langchain_google_genai import GoogleGenerativeAIEmbeddings  # noqa: E402

embedding_instance = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

from app.core.lazy_loader import providers  # noqa: E402
from app.services.gaia_knowledge_service import (  # noqa: E402
    KnowledgeItem,
    gaia_knowledge_service,
)


def clean_markdown_header(text: str) -> str:
    """
    Remove markdown header symbols (#, ##, ###) from text.

    Args:
        text: Text that may contain markdown headers

    Returns:
        Cleaned text without header symbols
    """
    # Remove markdown headers (one or more # followed by space)
    return re.sub(r"^#{1,6}\s+", "", text).strip()


def split_markdown_by_headers(content: str) -> list[tuple[str, str]]:
    """
    Split markdown content into sections based on headers.

    Args:
        content: The markdown content to split

    Returns:
        List of (header, content) tuples where header is the markdown header
        line and content is the text between headers
    """
    sections = []
    lines = content.split("\n")
    current_header = ""
    current_content: list[str] = []

    for line in lines:
        # Check if line is a markdown header
        if line.strip().startswith("#"):
            # Save previous section if it exists
            if current_header or current_content:
                sections.append((current_header, "\n".join(current_content)))
            current_header = line.strip()
            current_content = []
        else:
            current_content.append(line)

    # Add final section
    if current_header or current_content:
        sections.append((current_header, "\n".join(current_content)))

    return sections


def prepare_knowledge_items(
    sections: list[tuple[str, str]], min_length: int = 50
) -> list[dict]:
    """
    Prepare knowledge items using hierarchical chunking strategy.

    Strategy: Combine related sections hierarchically (H1 with H2, H2 with H3)
    to preserve context and provide more comprehensive search results.

    Args:
        sections: List of (header, content) tuples from split_markdown_by_headers
        min_length: Minimum character length for a section to be included

    Returns:
        List of dicts with 'content' and 'metadata' keys ready for batch insert
    """
    items = []

    # Track hierarchy: H1 -> H2 -> H3
    current_h1 = {"header": "", "content": ""}
    current_h2 = {"header": "", "content": ""}

    for idx, (header, section_content) in enumerate(sections, 1):
        if not section_content.strip():
            continue

        # Clean the header
        clean_header = clean_markdown_header(header)

        # Determine header level
        header_level = len(header) - len(header.lstrip("#"))

        # Build hierarchical content based on header level
        if header_level == 1:  # H1
            current_h1 = {"header": clean_header, "content": section_content.strip()}
            current_h2 = {"header": "", "content": ""}

            # Store H1 with its content
            full_content = f"{clean_header}\n\n{section_content}".strip()
            items.append(
                {
                    "content": full_content,
                    "metadata": {
                        "source": "content.md",
                        "section": clean_header,
                        "section_index": idx,
                        "level": "h1",
                    },
                }
            )

        elif header_level == 2:  # H2
            # Include parent H1 context
            parent_context = (
                f"{current_h1['header']}\n\n" if current_h1["header"] else ""
            )
            full_content = (
                f"{parent_context}{clean_header}\n\n{section_content}".strip()
            )

            current_h2 = {"header": clean_header, "content": section_content.strip()}

            if len(full_content) >= min_length:
                items.append(
                    {
                        "content": full_content,
                        "metadata": {
                            "source": "content.md",
                            "section": clean_header,
                            "parent_section": current_h1["header"]
                            if current_h1["header"]
                            else None,
                            "section_index": idx,
                            "level": "h2",
                        },
                    }
                )

        elif header_level == 3:  # H3
            # Include parent H2 and H1 context
            parent_context = ""
            if current_h1["header"]:
                parent_context += f"{current_h1['header']}\n\n"
            if current_h2["header"]:
                parent_context += f"{current_h2['header']}\n\n"

            full_content = (
                f"{parent_context}{clean_header}\n\n{section_content}".strip()
            )

            if len(full_content) >= min_length:
                items.append(
                    {
                        "content": full_content,
                        "metadata": {
                            "source": "content.md",
                            "section": clean_header,
                            "parent_section": current_h2["header"]
                            if current_h2["header"]
                            else current_h1["header"],
                            "section_index": idx,
                            "level": "h3",
                        },
                    }
                )

    return items


async def populate_knowledge(
    content_path: Optional[str] = None, clear_first: bool = False
) -> None:
    """
    Populate the GAIA knowledge base from content.md.

    Args:
        content_path: Path to content markdown file
        clear_first: Whether to clear existing knowledge first
    """
    if not content_path:
        content_path = str(
            Path(__file__).parent.parent.parent.parent / "docs" / "GAIA.md"
        )

    # Eagerly initialize providers needed by the script
    print("⚙️  Initializing providers...")

    # The @lazy_provider decorator returns a function that registers the provider.
    # We must call it to actually register `chromadb_constructor`.
    init_chromadb_constructor()

    providers.register(
        name="google_embeddings",
        loader_func=lambda: embedding_instance,
    )
    await providers.aget("chromadb_constructor")
    print("✅ Providers initialized")

    print("🚀 Starting GAIA knowledge population")
    print("📝 Collection: gaia_knowledge")
    print(f"📂 Source: {content_path}")
    print("=" * 60)

    # Read content file
    content_file = Path(content_path)
    if not content_file.exists():
        print(f"❌ Error: {content_path} not found!")
        return

    content = content_file.read_text(encoding="utf-8")
    print(f"✅ Loaded content: {len(content)} characters")

    # Clear existing knowledge if requested
    if clear_first:
        print("\n🗑️  Clearing existing knowledge...")
        if await gaia_knowledge_service.clear_knowledge():
            print("✅ Knowledge cleared")
        else:
            print("⚠️  Failed to clear knowledge")

    # Split content and prepare batch items
    sections = split_markdown_by_headers(content)
    print(f"📚 Found {len(sections)} sections\n")

    # Prepare items
    batch_items = prepare_knowledge_items(sections)

    # Preview items
    for idx, item in enumerate(batch_items, 1):
        header = item["metadata"]["section"]
        content_len = len(item["content"])
        print(f"  📄 {idx}. {header[:60]}... ({content_len} chars)")

    # Convert dicts to KnowledgeItem Pydantic models
    knowledge_items = [
        KnowledgeItem(content=item["content"], metadata=item.get("metadata", {}))
        for item in batch_items
    ]

    # Upload to ChromaDB
    print(f"\n{'=' * 60}")
    print(f"💾 Adding {len(knowledge_items)} items to ChromaDB...")

    added_count = await gaia_knowledge_service.add_knowledge_batch(knowledge_items)

    print(f"{'=' * 60}")
    if added_count == len(knowledge_items):
        print(f"✅ Successfully added {added_count} knowledge items!")
    else:
        print(f"❌ Failed! Added {added_count}/{len(knowledge_items)} items")

    # Test search functionality
    await _test_knowledge_search()

    print(f"\n{'=' * 60}")
    if added_count == len(knowledge_items):
        print("🎉 Knowledge population complete!")
    else:
        print("💥 Knowledge population failed — see errors above.")
    print(f"{'=' * 60}")


async def _test_knowledge_search() -> None:
    """Test knowledge search with a sample query."""
    print(f"\n{'=' * 60}")
    print("🔍 Testing knowledge search...")

    query = "What is GAIA?"
    results = await gaia_knowledge_service.search_knowledge(query=query, limit=3)

    if results:
        print(f"✅ Found {len(results)} results for '{query}':\n")
        for idx, result in enumerate(results, 1):
            preview = result.content[:80].replace("\n", " ")
            print(f"{idx}. Score: {result.relevance_score:.4f}")
            print(f"   {preview}...\n")
    else:
        print(f"❌ No results found for '{query}'")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Populate GAIA knowledge base from content.md"
    )
    parser.add_argument(
        "--content",
        default=str(Path(__file__).parent.parent.parent.parent / "docs" / "GAIA.md"),
        help="Path to content markdown file",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing knowledge before populating",
    )

    args = parser.parse_args()

    asyncio.run(populate_knowledge(content_path=args.content, clear_first=args.clear))


if __name__ == "__main__":
    main()
