#!/usr/bin/env python3
"""
Seed System Skills - Copy bundled skills to VFS.

This script reads skills from app/agents/skills/bundled/ and writes them
to /system/skills/ in MongoDB VFS, making them available to all users.

Run with: cd apps/api && uv run python -m app.agents.skills.seed_system_skills
"""

import asyncio

from app.agents.skills.bundled import get_all_bundled_skills
from app.agents.skills.parser import generate_skill_md
from app.config.loggers import app_logger as logger
from app.services.vfs.mongo_vfs import MongoVFS


async def seed_system_skills(force: bool = False) -> int:
    """
    Seed system skills to VFS.

    Args:
        force: If True, overwrite existing skills

    Returns:
        Number of skills seeded
    """
    vfs = MongoVFS()
    bundled_skills = get_all_bundled_skills()

    if not bundled_skills:
        logger.warning("[seed-skills] No bundled skills found to seed")
        return 0

    seeded = 0
    vfs._allow_system_write = True
    for skill in bundled_skills:
        target = skill.target or "global"
        skill_path = f"/system/skills/{target}/{skill.name}"

        # Generate full SKILL.md with frontmatter
        content = generate_skill_md(
            name=skill.name,
            description=skill.description,
            instructions=skill.body_content,
            target=target,
        )

        try:
            file_path = f"{skill_path}/SKILL.md"

            exists = await vfs.exists(file_path, user_id="system")
            if exists and not force:
                logger.info(f"[seed-skills] Skill already exists: {file_path}")
                seeded += 1
                continue

            await vfs.write(file_path, content, user_id="system")
            logger.info(f"[seed-skills] Seeded: {file_path}")
            seeded += 1

        except Exception as e:
            logger.error(f"[seed-skills] Failed to seed {skill_path}: {e}")

    logger.info(f"[seed-skills] Seeded {seeded} system skills")
    return seeded


async def verify_system_skills() -> int:
    """
    Verify system skills exist in VFS.

    Returns:
        Number of skills found
    """
    vfs = MongoVFS()
    bundled_skills = get_all_bundled_skills()

    found = 0
    for skill in bundled_skills:
        target = skill.target or "global"
        file_path = f"/system/skills/{target}/{skill.name}/SKILL.md"

        try:
            exists = await vfs.exists(file_path, user_id="system")
            if exists:
                logger.info(f"[seed-skills] Verified: {file_path}")
                found += 1
            else:
                logger.warning(f"[seed-skills] Missing: {file_path}")
        except Exception as e:
            logger.error(f"[seed-skills] Error checking {file_path}: {e}")

    return found


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Seed system skills to VFS")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only verify skills exist, don't seed",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite existing skills",
    )
    args = parser.parse_args()

    if args.verify:
        count = await verify_system_skills()
        print(f"Found {count} system skills in VFS")
    else:
        count = await seed_system_skills(force=args.force)
        print(f"Seeded {count} system skills")


if __name__ == "__main__":
    asyncio.run(main())
