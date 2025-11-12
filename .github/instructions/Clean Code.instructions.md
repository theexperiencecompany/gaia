---
applyTo: “**”
---

Write clean and minimalistic code. Do not create unnecessary test files, markdown files, or unnecessary files. Prioritize writing clean, modular, and production-level code. Reuse existing logic, paradigms, and abstractions if present. Do not do anything unnecessary or extra. Only add comments that are meaningful and cannot be inferred from the code; explain complex or non-obvious logic clearly.
Make changes file by file and allow for review of mistakes.
Make edits in a single shot per file. Do not make multiple edits to the same file.
Only implement changes explicitly requested; do not invent changes.
Provide all edits in a single chunk per file, not in multiple steps.
Encourage modular design for maintainability and reusability.
Adhere to the existing coding style in the project.
Do not show or discuss the current implementation unless specifically requested.
Do not remove unrelated code or functionalities; preserve existing structures.
Never use apologies or feedback about understanding in comments or documentation.

DRY Principle: Avoid code duplication; reuse code via functions, classes, modules, or libraries. Modify code in one place if updates are needed.

Function Length & Responsibility: Write short, focused functions (single responsibility principle). Break up long or complex functions into smaller ones.

Do not manually run servers or build unnecessarily unless explicitly told. Use available tools instead of terminal commands.
Do not run git commands unless explicitly instructed.
Do not create new files to replace existing files unless told otherwise; only modify existing files.
Do not run terminal commands if an existing tool can accomplish the task.
Do not make critical or breaking changes without user approval.
Ensure all changes are compatible with existing functionality; remove deprecated or backwards compatibility code if replaced.

Never use any types; infer proper types from context or use existing types.
Never import inside functions unless absolutely necessary or to avoid circular dependencies.
Do not add console logs or debugging statements unless explicitly requested.
Do not run or open backend/frontend servers or any other servers. You can only make code changes.

Use meaningful names for variables, functions, classes, and modules. Avoid vague names like “data” or “info”; be specific about the purpose.

Github Repository: https://github.com/theexperiencecompany/gaia
Use DeepWiki MCP (when available) for understanding the codebase. Use the ask_question tool to clarify doubts. Verify DeepWiki information against the latest codebase.
Maintain clarity, conciseness, and production-level quality in all code edits.

# Don't unnecessary read log files if the user has already told you what to do and has passed you the necessary logs.
