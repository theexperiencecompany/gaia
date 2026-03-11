#!/usr/bin/env python3
"""
Seed System Skills Script.

This script seeds all builtin system skills to MongoDB + VFS.

Usage:
    cd apps/api
    uv run python -m app.scripts.seed_skills

Arguments:
    --verify    Only verify skills exist in VFS, don't seed
    --force     Force overwrite existing skills

What it does:
    1. Reads SKILL.md files from: app/agents/skills/builtin/
    2. Validates skill content
    3. Writes body content to VFS at: /system/skills/{agent_name}/{skill_name}/SKILL.md
    4. Registers metadata in MongoDB skills collection (user_id="system")
    5. Invalidates skills cache in Redis
"""

import argparse
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
from shared.py.wide_events import log
from app.db.redis import delete_cache_by_pattern
from app.services.vfs.mongo_vfs import MongoVFS
from app.services.vfs.path_resolver import get_system_skill_path


async def _seed_builtin_skill(
    vfs: MongoVFS,
    skill_dir: Path,
    force: bool = False,
) -> tuple[Skill | None, str | None]:
    """Seed a single builtin skill from filesystem."""
    skill_name = skill_dir.name

    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        log.warning(f"[seed] Skipping {skill_name}: no SKILL.md found")
        return None, None

    try:
        content = skill_md_path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"[seed] Failed to read SKILL.md for {skill_name}: {e}")
        return None, None

    errors = validate_skill_content(content)
    if errors:
        log.warning(f"[seed] Invalid SKILL.md for {skill_name}: {errors}")
        return None, None

    try:
        metadata, body = parse_skill_md(content)
    except Exception as e:
        log.warning(f"[seed] Failed to parse SKILL.md for {skill_name}: {e}")
        return None, None

    target = metadata.target
    vfs_dir = get_system_skill_path(target, metadata.name)

    try:
        existing = await get_skill_by_name("system", metadata.name, target)
        if existing and not force:
            log.info(f"[seed] Builtin skill already exists: {metadata.name}")
            return None, metadata.name
        elif existing and force and existing.id:
            await uninstall_skill("system", existing.id)
    except Exception as e:
        log.debug(f"[seed] Could not check existing skill {metadata.name}: {e}")

    try:
        await vfs.write(
            f"{vfs_dir}/SKILL.md", body, "system", metadata={"source": "builtin"}
        )

        all_files = ["SKILL.md"]
        for root, _dirs, files in os.walk(skill_dir):
            for file in files:
                if file == "SKILL.md":
                    continue
                local_path = Path(root) / file
                relative_path = local_path.relative_to(skill_dir)
                vfs_relative = str(relative_path).replace("\\", "/")

                try:
                    file_content = local_path.read_text(encoding="utf-8")
                    await vfs.write(
                        f"{vfs_dir}/{vfs_relative}",
                        file_content,
                        "system",
                        metadata={"source": "builtin"},
                    )
                    all_files.append(vfs_relative)
                except Exception as e:
                    log.warning(f"[seed] Failed to write {vfs_relative}: {e}")

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

        log.info(f"[seed] Seeded builtin: {metadata.name} (target={target})")
        return skill, None
    except Exception as e:
        log.warning(f"[seed] Failed to seed builtin {metadata.name}: {e}")
        return None, None


async def seed_all_system_skills(force: bool = False) -> tuple[List[Skill], List[str]]:
    """Seed all builtin system skills to VFS and MongoDB.

    Args:
        force: If True, overwrite existing skills

    Returns:
        Tuple of newly seeded Skill objects and existing skill names
    """
    log.info("[seed] Starting system skills seeding")

    vfs = MongoVFS(allow_system_write=True)
    seeded: List[Skill] = []
    existing: List[str] = []

    builtin_path = Path(__file__).parent.parent / "agents" / "skills" / "builtin"
    if builtin_path.exists():
        builtin_dirs = [d for d in builtin_path.iterdir() if d.is_dir()]
        log.info(f"[seed] Found {len(builtin_dirs)} builtin skills")

        for skill_dir in builtin_dirs:
            skill, existing_name = await _seed_builtin_skill(
                vfs, skill_dir, force=force
            )
            if skill:
                seeded.append(skill)
            elif existing_name:
                existing.append(existing_name)
    else:
        log.warning(f"[seed] Builtin skills path not found: {builtin_path}")

    log.info(f"[seed] Seeded {len(seeded)} new system skills")
    if existing:
        log.info(f"[seed] Skipped {len(existing)} existing system skills")

    await delete_cache_by_pattern("skills:user:*")
    await delete_cache_by_pattern("skills:text:*")
    log.info("[seed] Invalidated skills caches")

    return seeded, existing


async def verify_system_skills() -> int:
    """Verify system skills exist in VFS.

    Returns:
        Number of skills found
    """
    vfs = MongoVFS()
    builtin_path = Path(__file__).parent.parent / "agents" / "skills" / "builtin"

    found = 0
    if builtin_path.exists():
        for skill_dir in builtin_path.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md_path = skill_dir / "SKILL.md"
            if not skill_md_path.exists():
                continue

            try:
                content = skill_md_path.read_text(encoding="utf-8")
                metadata, _ = parse_skill_md(content)
                vfs_dir = get_system_skill_path(metadata.target, metadata.name)
                file_path = f"{vfs_dir}/SKILL.md"

                exists = await vfs.exists(file_path, user_id="system")
                if exists:
                    log.info(f"[seed] Verified: {file_path}")
                    found += 1
                else:
                    log.warning(f"[seed] Missing: {file_path}")
            except Exception as e:
                log.error(f"[seed] Error checking {skill_dir}: {e}")

    return found


async def main():
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
        seeded_skills, existing_skills = await seed_all_system_skills(force=args.force)

        if seeded_skills:
            print(f"Seeded {len(seeded_skills)} new system skills:")
            for skill in seeded_skills:
                print(f"  - {skill.name} -> {skill.vfs_path}")
        else:
            print("No new system skills seeded.")

        if existing_skills:
            print(
                f"Skipped {len(existing_skills)} existing system skills "
                "(use --force to overwrite):"
            )
            for skill_name in existing_skills:
                print(f"  - {skill_name}")


if __name__ == "__main__":
    asyncio.run(main())
