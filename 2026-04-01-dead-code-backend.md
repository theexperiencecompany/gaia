# Backend Dead Code Elimination

Run: `cd apps/api && uv run vulture`

**Rules applied:**
- Don't touch anything in `app/agents/` (prompts, tools, subagents, graph manager, skills, middleware, templates, memory)
- Verified every item via grep before listing
- Notion and LinkedIn tool functions are ACTUALLY USED (registered via custom tools registry) — removed from plan
- All utility functions in `app/utils/` are used (at least in tests) — removed from plan
- All constants are used — removed from plan
- Composio service dead methods don't exist in current code — removed from plan
- CheckpointerManager classes don't exist as named — removed from plan

---

## 1. Dead API/service code (verified zero callers in production)

### blog_auth.py
- [ ] `app/api/v1/dependencies/blog_auth.py:53` — `get_optional_blog_token` — defined but never imported or called anywhere

### tiered_rate_limiter.py
- [ ] `app/api/v1/middleware/tiered_rate_limiter.py:173` — `get_usage_info` method — only called in tests, never in production code

### token_repository.py (only called in tests, not production)
- [ ] `app/config/token_repository.py:225` — `update_token`
- [ ] `app/config/token_repository.py:417` — `revoke_all_tokens`
- [ ] `app/config/token_repository.py:450` — `get_authorized_scopes`
- [ ] `app/config/token_repository.py:489` — `list_user_tokens`

### notification sources (zero callers anywhere)
- [ ] `app/utils/notification/sources.py:32` — `create_calendar_event_notification`
- [ ] `app/utils/notification/sources.py:103` — `create_mail_composition_notification`
- [ ] `app/utils/notification/sources.py:174` — `create_todo_creation_notification`
- [ ] `app/utils/notification/sources.py:277` — `create_proactive_notification`

---

## 2. Dead variables (non-agent, safe to rename to `_` or remove)

- [ ] `app/override/langgraph_bigtool/utils.py:15` — `left` parameter (required by reducer signature but unused in body — rename to `_left`)
- [ ] `app/patches/opik_patch.py:13` — `workers` variable assigned but never read
- [ ] `app/services/platform_link_service.py:87` — `use_object_id` assigned but never read
- [ ] `app/services/platform_link_service.py:170` — `use_object_id` assigned but never read

---

## Kept (not in this plan)

- Everything in `app/agents/` (prompts, tools, subagents, graph_manager, skills, middleware, templates, memory)
- All Notion tool functions (MOVE_PAGE, FETCH_PAGE_AS_MARKDOWN, etc.) — registered via `register_notion_custom_tools()` in custom tools registry
- All LinkedIn tool functions — registered via `register_linkedin_custom_tools()` in custom tools registry
- All `app/utils/` functions — all have test coverage and/or production callers
- All constants — all imported somewhere
- SchedulerService — actually `BaseSchedulerService`, subclassed by `ReminderScheduler` and `WorkflowScheduler`
- CheckpointerManager classes — current implementation uses a different `CheckpointerManager` class

---

## Execution

After changes: `nx type-check api && nx lint api`
