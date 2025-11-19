"""Test Mem0 batch storage exactly as used in profile crawling."""

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.services.memory_service import memory_service


async def test_profile_memory_storage():
    """
    Recreate exact profile memory storage from email_processor.py line 537.
    This mimics storing crawled social profiles.
    """
    print("\n" + "=" * 80)
    print("Testing Profile Memory Storage (Batch)")
    print("=" * 80)

    # Test user
    test_user_id = "test_batch_debug"
    user_name = "aryan randeriya"
    user_email = "aryan@example.com"

    # Simulate crawled profile content (like from crawl4ai)
    successful_profiles = [
        {
            "platform": "twitter",
            "url": "https://x.com/aryanranderiya",
            "content": """aryan randeriya (@aryanranderiya)

Software Engineer at Acme Corp
San Francisco, CA

Building AI products. Love hiking and coffee.
Tweets about tech, startups, and life.

Following: 234 | Followers: 1,245
""",
        },
        {
            "platform": "github",
            "url": "https://github.com/aryanranderiya",
            "content": """aryan randeriya (aryanranderiya)

🚀 Software Engineer @ Acme Corp
📍 San Francisco
💻 Python, JavaScript, Go
⭐ 45 repositories | 234 stars

Pinned Repositories:
- ai-assistant: Personal AI assistant built with LangChain
- web-scraper: Fast async web scraping library
- dotfiles: My development environment setup
""",
        },
        {
            "platform": "linkedin",
            "url": "https://linkedin.com/in/aryanranderiya",
            "content": """aryan randeriya
Software Engineer at Acme Corp
San Francisco Bay Area

About:
Passionate software engineer with 5 years of experience building
scalable web applications and AI-powered tools. Expert in Python,
JavaScript, and distributed systems.

Experience:
- Software Engineer, Acme Corp (2021-Present)
- Junior Developer, StartupCo (2019-2021)

Skills: Python, JavaScript, React, Node.js, AWS, Docker
""",
        },
    ]

    print(f"\nSimulating storage of {len(successful_profiles)} crawled profiles...")
    print(f"User: {user_name} ({user_email})")
    print(f"User ID: {test_user_id}\n")

    # Build messages exactly like email_processor.py does
    profile_messages = []

    for profile in successful_profiles:
        memory_content = f"""User's {profile["platform"]} profile: {profile["url"]} {profile["content"]} """
        profile_messages.append({"role": "user", "content": memory_content})
        print(f"  - {profile['platform']}: {profile['url']}")

    print(f"\nCalling store_memory_batch with {len(profile_messages)} messages...")
    print("\n⚠️  NOTE: async_mode=False means SYNCHRONOUS processing!")
    print("   Mem0 will process all messages NOW (LLM extraction for each)")
    print("   With 3 long profiles, this takes 30-60+ seconds")
    print("-" * 80)

    start = time.time()
    try:
        # Exact call from email_processor.py line 537
        batch_success = await memory_service.store_memory_batch(
            messages=profile_messages,
            user_id=test_user_id,
            async_mode=True,
            metadata={
                "type": "social_profile",
                "source": "parallel_gmail_search_extraction",
                "discovered_at": datetime.now(timezone.utc).isoformat(),
                "batch_size": len(profile_messages),
                "user_name": user_name,
                "user_email": user_email,
            },
        )
        elapsed = time.time() - start

        print("-" * 80)
        print(f"⏱️  Took {elapsed:.2f} seconds")
        if batch_success:
            print(f"✓ SUCCESS: Stored {len(successful_profiles)} profiles")
        else:
            print(f"✗ FAILED: batch_success = {batch_success}")
            print("  Possible reasons:")
            print("  - Mem0 filtered all content (returned 0 memories)")
            print("  - API error (check logs above for 400 Bad Request)")

    except Exception as e:
        elapsed = time.time() - start
        print("-" * 80)
        print(f"⏱️  Failed after {elapsed:.2f} seconds")
        print(f"✗ EXCEPTION: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 80)
    print("WHY IS IT SLOW?")
    print("=" * 80)
    print("async_mode=False = Mem0 processes synchronously (waits for LLM)")
    print("async_mode=True  = Mem0 queues job, returns immediately")
    print("\nProfile content is VERY LONG (hundreds of lines)")
    print("Mem0 runs LLM extraction on each message = slow")
    print("\nSOLUTION: Use async_mode=True for large batches or long content")


if __name__ == "__main__":
    asyncio.run(test_profile_memory_storage())
