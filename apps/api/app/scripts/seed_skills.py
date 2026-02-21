"""
Seeding script for system skills (alias).

Usage:
    cd apps/api && uv run python -m app.scripts.seed_skills

This is an alias for the unified seeder at:
    app.agents.skills.seed_system_skills
"""

import asyncio

from app.agents.skills.seed_system_skills import main

if __name__ == "__main__":
    asyncio.run(main())
