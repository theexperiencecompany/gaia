"""
Agent Skills System - Installable skills following the Agent Skills open standard.

Skills are folders of instructions (SKILL.md), scripts, and resources stored
on the user's persistent JuiceFS workspace. The agent discovers available
skills at runtime and activates them using the coding tools (`read`, `bash`),
since `/workspace/skills/<name>/` is bind-mounted into the sandbox.

Modules:
    models      - Pydantic models (SkillMetadata, InstalledSkill, SkillSource)
    parser      - SKILL.md YAML frontmatter parser and validator
    registry    - MongoDB-backed installed skills registry (CRUD)
    installer   - Install skills from GitHub repos or inline creation
    discovery   - Generate <available_skills> XML for agent system prompts
"""
