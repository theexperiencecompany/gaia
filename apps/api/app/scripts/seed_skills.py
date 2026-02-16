"""
Seeding script for builtin skills.

Usage:
    cd apps/api && uv run python -m app.scripts.seed_skills

This script reads skills from app/agents/skills/builtin/ and stores them in VFS.
Run this manually after deployment or when adding new builtin skills.
"""

import asyncio
import os
from pathlib import Path
from typing import List, Optional

from app.agents.skills.models import InstalledSkill, SkillSource
from app.agents.skills.parser import parse_skill_md, validate_skill_content
from app.agents.skills.registry import get_skill_by_name, install_skill, uninstall_skill
from app.config.loggers import app_logger as logger
from app.services.vfs.mongo_vfs import MongoVFS

BUILTIN_SKILLS_PATH = Path(__file__).parent.parent / "agents" / "skills" / "builtin"


def _get_skill_directories() -> List[Path]:
    """Get all skill directories from builtin folder."""
    if not BUILTIN_SKILLS_PATH.exists():
        logger.warning(
            f"[seed-skills] Builtin skills path does not exist: {BUILTIN_SKILLS_PATH}"
        )
        return []

    skill_dirs = []
    for item in BUILTIN_SKILLS_PATH.iterdir():
        if item.is_dir():
            skill_dirs.append(item)

    return skill_dirs


async def _seed_single_skill(
    skill_dir: Path, force: bool = False
) -> Optional[InstalledSkill]:
    """Seed a single skill to VFS and MongoDB."""
    skill_name = skill_dir.name

    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        logger.warning(f"[seed-skills] Skipping {skill_name}: no SKILL.md found")
        return None

    try:
        content = skill_md_path.read_text()
    except Exception as e:
        logger.warning(f"[seed-skills] Failed to read SKILL.md for {skill_name}: {e}")
        return None

    errors = validate_skill_content(content)
    if errors:
        logger.warning(f"[seed-skills] Invalid SKILL.md for {skill_name}: {errors}")
        return None

    try:
        metadata, body = parse_skill_md(content)
    except Exception as e:
        logger.warning(f"[seed-skills] Failed to parse SKILL.md for {skill_name}: {e}")
        return None

    subagent_id = metadata.target or "global"
    vfs_path = f"/system/skills/{subagent_id}/{skill_name}"

    try:
        existing = await get_skill_by_name("system", skill_name, metadata.target)
        if existing and not force:
            logger.info(f"[seed-skills] Skill {skill_name} already exists, skipping")
            return existing
        elif existing and force:
            logger.info(
                f"[seed-skills] Skill {skill_name} exists, uninstalling first due to --force"
            )
            if existing.id:
                await uninstall_skill("system", existing.id)
    except Exception as e:
        logger.debug(f"[seed-skills] Could not check existing skill {skill_name}: {e}")

    try:
        vfs = MongoVFS()
        vfs._allow_system_write = True

        await vfs.write(
            f"{vfs_path}/SKILL.md",
            content,
            "system",
            metadata={"source": "builtin"},
        )

        all_files = []
        for root, dirs, files in os.walk(skill_dir):
            for file in files:
                if file == "SKILL.md":
                    continue
                local_path = Path(root) / file
                relative_path = local_path.relative_to(skill_dir)
                vfs_relative = str(relative_path).replace("\\", "/")

                try:
                    file_content = local_path.read_text()
                    await vfs.write(
                        f"{vfs_path}/{vfs_relative}",
                        file_content,
                        "system",
                        metadata={"source": "builtin"},
                    )
                    all_files.append(vfs_relative)
                except Exception as e:
                    logger.warning(f"[seed-skills] Failed to write {vfs_relative}: {e}")

        all_files.insert(0, "SKILL.md")

        installed = await install_skill(
            user_id="system",
            skill_metadata=metadata,
            vfs_path=vfs_path,
            source=SkillSource.INLINE,
            body_content=body,
            files=all_files,
        )

        logger.info(
            f"[seed-skills] Seeded builtin skill: {skill_name} (target: {subagent_id})"
        )
        return installed

    except Exception as e:
        logger.warning(f"[seed-skills] Failed to seed skill {skill_name}: {e}")
        return None


async def seed_builtin_skills(force: bool = False) -> List[InstalledSkill]:
    """Seed all builtin skills to VFS and MongoDB."""
    logger.info("[seed-skills] Starting builtin skills seeding")

    skill_dirs = _get_skill_directories()
    logger.info(f"[seed-skills] Found {len(skill_dirs)} builtin skills")

    seeded_skills: List[InstalledSkill] = []

    for skill_dir in skill_dirs:
        skill = await _seed_single_skill(skill_dir, force=force)
        if skill:
            seeded_skills.append(skill)

    logger.info(f"[seed-skills] Seeded {len(seeded_skills)} builtin skills")
    return seeded_skills


async def main():
    """Main entry point for seeding script."""
    import argparse

    parser = argparse.ArgumentParser(description="Seed builtin skills to VFS")
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing skills"
    )
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Starting builtin skills seeding...")
    logger.info("=" * 50)

    skills = await seed_builtin_skills(force=args.force)

    logger.info("=" * 50)
    logger.info(f"Seeding complete! Seeded {len(skills)} skills:")
    for skill in skills:
        logger.info(f"  - {skill.skill_metadata.name} -> {skill.vfs_path}")
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
