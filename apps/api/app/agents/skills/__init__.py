"""
Agent Skills System - Installable skills following the Agent Skills open standard.

Skills are folders of instructions (SKILL.md), scripts, and resources stored
in the user's VFS. The agent discovers available skills at runtime and activates
them using existing VFS tools (vfs_read, vfs_cmd) to read SKILL.md content and
browse resources — no special activation tools needed.

Modules:
    models      - Pydantic models (SkillMetadata, InstalledSkill, SkillSource)
    parser      - SKILL.md YAML frontmatter parser and validator
    registry    - MongoDB-backed installed skills registry (CRUD)
    installer   - Install skills from GitHub repos or inline creation
    discovery   - Generate <available_skills> XML for agent system prompts
"""
