#!/usr/bin/env python3
"""
Skill Seeder - Seed all builtin system skills to MongoDB + VFS.

Reads skills from:
  - app/agents/skills/builtin/  (builtin skills)

Writes body-only content to VFS at /system/skills/{agent_name}/{skill_name}/SKILL.md
and registers flat metadata in the MongoDB skills collection with user_id="system".

Run with:
    cd apps/api && uv run python -m app.agents.skills.seed_system_skills
    cd apps/api && uv run python -m app.scripts.seed_skills  (alias)
"""

import asyncio
import os
from pathlib import Path
from typing import List

from app.agents.skills.models import Skill, SkillSource
from app.agents.skills.parser import parse_skill_md, validate_skill_content
from app.agents.skills.registry import (
    get_skill_by_name,
    install_skill,
    uninstall_skill,
)
from app.config.loggers import app_logger as logger
from app.db.redis import delete_cache_by_pattern
from app.services.vfs.mongo_vfs import MongoVFS
from app.services.vfs.path_resolver import get_system_skill_path


async def _seed_builtin_skill(
    vfs: MongoVFS,
    skill_dir: Path,
    force: bool = False,
) -> Skill | None:
    """Seed a single builtin skill from filesystem."""
    skill_name = skill_dir.name

    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        logger.warning(f"[seed] Skipping {skill_name}: no SKILL.md found")
        return None

    try:
        content = skill_md_path.read_text()
    except Exception as e:
        logger.warning(f"[seed] Failed to read SKILL.md for {skill_name}: {e}")
        return None

    errors = validate_skill_content(content)
    if errors:
        logger.warning(f"[seed] Invalid SKILL.md for {skill_name}: {errors}")
        return None

    try:
        metadata, body = parse_skill_md(content)
    except Exception as e:
        logger.warning(f"[seed] Failed to parse SKILL.md for {skill_name}: {e}")
        return None

    target = metadata.target
    vfs_dir = get_system_skill_path(target, metadata.name)

    try:
        existing = await get_skill_by_name("system", metadata.name, target)
        if existing and not force:
            logger.info(f"[seed] Builtin skill already exists: {metadata.name}")
            return existing
        elif existing and force and existing.id:
            await uninstall_skill("system", existing.id)
    except Exception as e:
        logger.debug(f"[seed] Could not check existing skill {metadata.name}: {e}")

    try:
        # Write body-only to VFS (no frontmatter)
        await vfs.write(
            f"{vfs_dir}/SKILL.md", body, "system", metadata={"source": "builtin"}
        )

        # Write additional files from the skill directory
        all_files = ["SKILL.md"]
        for root, _dirs, files in os.walk(skill_dir):
            for file in files:
                if file == "SKILL.md":
                    continue
                local_path = Path(root) / file
                relative_path = local_path.relative_to(skill_dir)
                vfs_relative = str(relative_path).replace("\\", "/")

                try:
                    file_content = local_path.read_text()
                    await vfs.write(
                        f"{vfs_dir}/{vfs_relative}",
                        file_content,
                        "system",
                        metadata={"source": "builtin"},
                    )
                    all_files.append(vfs_relative)
                except Exception as e:
                    logger.warning(f"[seed] Failed to write {vfs_relative}: {e}")

        # Register in MongoDB with flat fields
        skill = await install_skill(
            user_id="system",
            name=metadata.name,
            description=metadata.description,
            target=target,
            vfs_path=vfs_dir,
            source=SkillSource.INLINE,
            body_content=body,
            files=all_files,
        )

        logger.info(f"[seed] Seeded builtin: {metadata.name} (target={target})")
        return skill
    except Exception as e:
        logger.warning(f"[seed] Failed to seed builtin {metadata.name}: {e}")
        return None


async def seed_all_system_skills(force: bool = False) -> List[Skill]:
    """Seed all builtin system skills to VFS and MongoDB.

    Args:
        force: If True, overwrite existing skills

    Returns:
        List of seeded Skill objects
    """
    logger.info("[seed] Starting system skills seeding")

    vfs = MongoVFS()
    vfs._allow_system_write = True
    seeded: List[Skill] = []

    # Seed builtin skills
    builtin_path = Path(__file__).parent / "builtin"
    if builtin_path.exists():
        builtin_dirs = [d for d in builtin_path.iterdir() if d.is_dir()]
        logger.info(f"[seed] Found {len(builtin_dirs)} builtin skills")

        for skill_dir in builtin_dirs:
            skill = await _seed_builtin_skill(vfs, skill_dir, force=force)
            if skill:
                seeded.append(skill)
    else:
        logger.warning(f"[seed] Builtin skills path not found: {builtin_path}")

    logger.info(f"[seed] Seeded {len(seeded)} system skills")

    # Invalidate all skills caches
    await delete_cache_by_pattern("skills:user:*")
    await delete_cache_by_pattern("skills:text:*")
    logger.info("[seed] Invalidated skills caches")

    return seeded


# Keep backward-compat names for existing callers
seed_system_skills = seed_all_system_skills
seed_builtin_skills = seed_all_system_skills


async def verify_system_skills() -> int:
    """Verify system skills exist in VFS.

    Returns:
        Number of skills found
    """
    vfs = MongoVFS()
    builtin_path = Path(__file__).parent / "builtin"

    found = 0
    if builtin_path.exists():
        for skill_dir in builtin_path.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md_path = skill_dir / "SKILL.md"
            if not skill_md_path.exists():
                continue

            try:
                content = skill_md_path.read_text()
                metadata, _ = parse_skill_md(content)
                vfs_dir = get_system_skill_path(metadata.target, metadata.name)
                file_path = f"{vfs_dir}/SKILL.md"

                exists = await vfs.exists(file_path, user_id="system")
                if exists:
                    logger.info(f"[seed] Verified: {file_path}")
                    found += 1
                else:
                    logger.warning(f"[seed] Missing: {file_path}")
            except Exception as e:
                logger.error(f"[seed] Error checking {skill_dir}: {e}")

    return found


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Seed system skills to VFS + MongoDB")
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
        skills = await seed_all_system_skills(force=args.force)
        print(f"Seeded {len(skills)} system skills:")
        for skill in skills:
            print(f"  - {skill.name} -> {skill.vfs_path}")


if __name__ == "__main__":
    asyncio.run(main())
