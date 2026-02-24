# Vulture whitelist — suppress known false positives
# Add entries as: `variable_name`
# See: https://github.com/jendrikseipp/vulture#whitelisting
# type: ignore  # mypy: vulture uses _ as a placeholder

# FastAPI/Pydantic
from pydantic import BaseModel  # noqa

_.model_config  # noqa
_.model_fields  # noqa
_.current_datetime  # noqa - Used in Pydantic models
_.mem0_user_id  # noqa - Used in agent state
_.memories_stored  # noqa - Used in agent state

# FastAPI dependencies & route decorators are used implicitly
# Vulture already handles decorators, but explicit overrides go here.

# ─── Starlette / ASGI Middleware ────────────────────────────────────────────

_.dispatch  # noqa - Required method of BaseHTTPMiddleware
_.user_cache_expiry  # noqa - Instance attribute used inside dispatch (auth middleware)

# ─── ARQ Worker config attributes ───────────────────────────────────────────
# ARQ reads these as class-level attributes; they are never called directly.

_.functions  # noqa - ARQ worker config
_.cron_jobs  # noqa - ARQ worker config
_.on_startup  # noqa - ARQ worker config
_.on_shutdown  # noqa - ARQ worker config
_.max_jobs  # noqa - ARQ worker config
_.job_timeout  # noqa - ARQ worker config
_.keep_result  # noqa - ARQ worker config
_.log_results  # noqa - ARQ worker config
_.health_check_interval  # noqa - ARQ worker config
_.health_check_key  # noqa - ARQ worker config
_.allow_abort_jobs  # noqa - ARQ worker config

# ─── Pydantic validators ─────────────────────────────────────────────────────
# Methods decorated with @validator / @field_validator / @model_validator are
# invoked internally by Pydantic and never appear as direct call-sites.

_.validate_date_format  # noqa - Pydantic validator
_.validate_lookup  # noqa - Pydantic validator
_.validate_by_day  # noqa - Pydantic validator
_.validate_by_month_day  # noqa - Pydantic validator
_.validate_by_month  # noqa - Pydantic validator
_.validate_recurrence  # noqa - Pydantic validator
_.validate_dates  # noqa - Pydantic validator
_.validate_timezone_offset  # noqa - Pydantic validator
_.validate_time_format  # noqa - Pydantic validator
_.validate_times  # noqa - Pydantic validator
_.validate_platform  # noqa - Pydantic validator
_.validate_profession  # noqa - Pydantic validator
_.validate_response_style  # noqa - Pydantic validator
_.validate_custom_instructions  # noqa - Pydantic validator
_.validate_name  # noqa - Pydantic validator
_.validate_timezone  # noqa - Pydantic validator
_.validate_phase_progression  # noqa - Pydantic validator
_.validate_single_config  # noqa - Pydantic validator
_.validate_non_empty_strings  # noqa - Pydantic validator
_.validate_priority  # noqa - Pydantic validator
_.validate_auth_type  # noqa - Pydantic validator
_.check_repeat_cron  # noqa - Pydantic validator
_.check_scheduled_at_future  # noqa - Pydantic validator
_.check_max_occurrences  # noqa - Pydantic validator
_.check_stop_after_future  # noqa - Pydantic validator
_.serialize_datetime  # noqa - Pydantic serializer
_.ensure_timezone_aware  # noqa - Pydantic validator
_.coerce_clone_count  # noqa - Pydantic validator
_.normalize_trigger_type  # noqa - Pydantic validator

# ─── Pydantic inner Config classes ───────────────────────────────────────────
# Pydantic v1-style Config classes and their attributes are read reflectively.

_.Config  # noqa - Pydantic v1 Config inner class
_.extra  # noqa - Pydantic Config attribute
_.json_encoders  # noqa - Pydantic Config attribute
_.populate_by_name  # noqa - Pydantic Config attribute
_.allow_population_by_field_name  # noqa - Pydantic Config attribute

# ─── Pytest fixtures & hooks ─────────────────────────────────────────────────
# pytest discovers fixtures and hooks by name at collection time.
import pytest  # noqa

_.fixture  # noqa
_.mark  # noqa
_.pytest_addoption  # noqa - pytest command-line hook
_.skip_destructive  # noqa - pytest fixture
_.event_loop  # noqa - pytest-asyncio fixture
_.mock_stream_writer  # noqa - pytest fixture
_.return_value  # noqa - pytest mock attribute

# ─── Magic / dunder attributes ────────────────────────────────────────────────

_.__doc__  # noqa - Python magic attribute
_.__signature__  # noqa - Python magic attribute
_.__annotations__  # noqa - Python magic attribute
_.__getattr__  # noqa - Python magic attribute

# ─── Custom Composio tools ───────────────────────────────────────────────────
# These function names are passed as string identifiers to the Composio SDK.

_.CUSTOM_SHARE_SPREADSHEET  # noqa
_.CUSTOM_CREATE_PIVOT_TABLE  # noqa
_.CUSTOM_SET_DATA_VALIDATION  # noqa
_.CUSTOM_ADD_CONDITIONAL_FORMAT  # noqa
_.CUSTOM_CREATE_CHART  # noqa
_.CUSTOM_CREATE_POST  # noqa
_.CUSTOM_ADD_COMMENT  # noqa
_.CUSTOM_GET_POST_COMMENTS  # noqa
_.CUSTOM_REACT_TO_POST  # noqa
_.CUSTOM_DELETE_REACTION  # noqa
_.CUSTOM_GET_POST_REACTIONS  # noqa
_.MOVE_PAGE  # noqa
_.FETCH_PAGE_AS_MARKDOWN  # noqa
_.INSERT_MARKDOWN  # noqa
_.FETCH_DATA  # noqa
_.CUSTOM_CREATE_TEST_PAGE  # noqa
_.CUSTOM_BATCH_FOLLOW  # noqa
_.CUSTOM_BATCH_UNFOLLOW  # noqa
_.CUSTOM_CREATE_THREAD  # noqa - Composio custom tool (twitter)
_.CUSTOM_SEARCH_USERS  # noqa - Composio custom tool (twitter)
_.CUSTOM_SCHEDULE_TWEET  # noqa - Composio custom tool (twitter)

# ─── LangGraph overrides ─────────────────────────────────────────────────────

_._get_tool  # noqa - Overrides base class method in langgraph_bigtool

# ─── Framework / registry methods ────────────────────────────────────────────

_.wrap_tools  # noqa - Service method called by framework
_.get_all_tool_names  # noqa - Registry method
_.get_registered_toolkits  # noqa - Registry method

# ─── Import-for-side-effects — composio hook registration ────────────────────
# These modules are imported in all_hooks.py solely to trigger hook registration.

_.gmail_hooks  # noqa - imported for side effects in all_hooks.py
_.reddit_hooks  # noqa - imported for side effects in all_hooks.py
_.slack_hooks  # noqa - imported for side effects in all_hooks.py
_.twitter_hooks  # noqa - imported for side effects in all_hooks.py
_.user_id_hooks  # noqa - imported for side effects in all_hooks.py

# ─── Composio gmail custom tools ─────────────────────────────────────────────
# Uppercase function names registered as Composio custom tools.

_.MARK_AS_READ  # noqa - Composio custom tool
_.MARK_AS_UNREAD  # noqa - Composio custom tool
_.ARCHIVE_EMAIL  # noqa - Composio custom tool
_.STAR_EMAIL  # noqa - Composio custom tool
_.GET_UNREAD_COUNT  # noqa - Composio custom tool

# ─── LiveKit voice-agent ──────────────────────────────────────────────────────

_.conversation_description  # noqa - LiveKit voice-agent state
_.log_context_fields  # noqa - LiveKit structured logging
_.log_context  # noqa - LiveKit structured logging

# ─── Dynamic call sites ───────────────────────────────────────────────────────

_.call_subagent  # noqa - called dynamically in subagent_runner

# ─── Intentionally unused parameters (monkey patch signatures) ───────────────

_.workers  # noqa - intentionally unused in opik_patch sequential replacement

# ─── Composio hook registry ───────────────────────────────────────────────────

_.all_hooks  # noqa - hooks registry variable

# ─── LangGraph TYPE_CHECKING imports ─────────────────────────────────────────

_.Runtime  # noqa - used as TYPE_CHECKING type annotation

# ─── Composio schema fields ───────────────────────────────────────────────────
# External API response schema definitions — not dead code.

_.gid  # noqa - Composio schema field
_.due_on  # noqa - Composio schema field
_.attachment_list  # noqa - Composio schema field
_.message_timestamp  # noqa - Composio schema field
_.messageId  # noqa - Composio schema field
_.messageText  # noqa - Composio schema field
_.messageTimestamp  # noqa - Composio schema field
_.labelIds  # noqa - Composio schema field
_.preview  # noqa - Composio schema field
_.organizer_email  # noqa - Composio schema field
_.organizer_name  # noqa - Composio schema field
_.countdown_window_minutes  # noqa - Composio schema field
_.creator_email  # noqa - Composio schema field
_.hangout_link  # noqa - Composio schema field
_.html_link  # noqa - Composio schema field
_.organizer_self  # noqa - Composio schema field
_.createdTime  # noqa - Composio schema field
_.lastModifyingUser  # noqa - Composio schema field
_.mimeType  # noqa - Composio schema field
_.modifiedTime  # noqa - Composio schema field
_.detected_at  # noqa - Composio schema field
_.row_data  # noqa - Composio schema field
_.row_number  # noqa - Composio schema field
_.starred_at  # noqa - Composio schema field
_.createdAt  # noqa - Composio schema field
_.createdBy  # noqa - Composio schema field
_.bot_id  # noqa - Composio schema field
_.ok  # noqa - Composio schema field
_.exclude_archived  # noqa - Composio schema field
_.is_archived  # noqa - Composio schema field
_.is_channel  # noqa - Composio schema field
_.is_general  # noqa - Composio schema field
_.num_members  # noqa - Composio schema field
_.include_trashed  # noqa - Composio schema field
_.modified_after  # noqa - Composio schema field
_.order_by  # noqa - Composio schema field
_.kind  # noqa - Composio schema field
_.displayName  # noqa - Composio schema field
_.emailAddress  # noqa - Composio schema field
_.providers_queried  # noqa - Composio schema field
_.free_slots  # noqa - Composio schema field
_.important_threads  # noqa - Composio schema field
_.assigned_issues  # noqa - Composio schema field
_.active_cycle  # noqa - Composio schema field
_.recent_activity  # noqa - Composio schema field
_.channels_with_activity  # noqa - Composio schema field
_.recently_edited  # noqa - Composio schema field
_.relevant_pages  # noqa - Composio schema field
_.assigned_prs  # noqa - Composio schema field
_.review_requests  # noqa - Composio schema field
_.overdue_tasks  # noqa - Composio schema field
_.task_lists  # noqa - Composio schema field
_.boards  # noqa - Composio schema field
_.spaces  # noqa - Composio schema field
_.before  # noqa - Composio schema field
_.since  # noqa - Composio schema field
_.private  # noqa - Composio schema field
_.html_url  # noqa - Composio schema field
_.fork  # noqa - Composio schema field
_.pushed_at  # noqa - Composio schema field
_.default_branch  # noqa - Composio schema field

# ─── Settings attributes used by external services ───────────────────────────
# Used by bot apps (Discord, Slack, Telegram) or external integrations.

_.GOOGLE_USERINFO_URL  # noqa - used by auth/OAuth integrations
_.ASSEMBLYAI_API_KEY  # noqa - used by voice/transcription integrations
_.DEEPGRAM_API_KEY  # noqa - used by voice-agent (livekit-plugins-deepgram reads env)
_.DISCORD_CLIENT_ID  # noqa - used by Discord bot app
_.SLACK_BOT_TOKEN  # noqa - used by Slack bot app
_.SLACK_SIGNING_SECRET  # noqa - used by Slack bot app
_.SLACK_APP_TOKEN  # noqa - used by Slack bot app

# ─── html2text configuration attributes ──────────────────────────────────────
# Set on html2text.HTML2Text instances to configure conversion behaviour.

_.ignore_links  # noqa - html2text configuration attribute
_.body_width  # noqa - html2text configuration attribute
_.ignore_images  # noqa - html2text configuration attribute
_.skip_internal_links  # noqa - html2text configuration attribute

# ─── Pydantic model fields (API schemas) ─────────────────────────────────────
# These are field definitions on Pydantic models that form part of the API
# schema. They are never "called" directly but are used for (de)serialisation.

# apps/api/app/models/about_models.py
_.avatar  # noqa - Pydantic model field
_.linkedin  # noqa - Pydantic model field
_.twitter  # noqa - Pydantic model field

# apps/api/app/models/blog_models.py
_.author_details  # noqa - Pydantic model field

# apps/api/app/models/calendar_models.py
_.original_summary  # noqa - Pydantic model field

# apps/api/app/models/chat_models.py
_.disclaimer  # noqa - Pydantic model field
_.subtype  # noqa - Pydantic model field
_.filetype  # noqa - Pydantic model field
_.EMAIL_PROCESSING  # noqa - Pydantic enum value
_.REMINDER_PROCESSING  # noqa - Pydantic enum value
_.OTHER  # noqa - Pydantic enum value
_.WEB  # noqa - Pydantic enum value
_.MOBILE  # noqa - Pydantic enum value
_.TELEGRAM  # noqa - Pydantic enum value
_.DISCORD  # noqa - Pydantic enum value
_.SLACK  # noqa - Pydantic enum value
_.WHATSAPP  # noqa - Pydantic enum value
_.WORKFLOW_SYSTEM  # noqa - Pydantic enum value

# apps/api/app/models/composio_schemas/context_tools.py
_.limit_per_provider  # noqa - Pydantic model field
_.items_count  # noqa - Pydantic model field
_.total_items  # noqa - Pydantic model field
_.busy_hours  # noqa - Pydantic model field
_.threads  # noqa - Pydantic model field

# apps/api/app/models/composio_schemas/github_tools.py
_.owner  # noqa - Pydantic model field

# apps/api/app/models/device_token_models.py
_.IOS  # noqa - Pydantic enum value
_.ANDROID  # noqa - Pydantic enum value

# apps/api/app/models/integration_models.py
_.suggested  # noqa - Pydantic model field

# apps/api/app/models/linear_models.py
_.labels_to_remove  # noqa - Pydantic model field

# apps/api/app/models/mail_models.py
_.include_action_items  # noqa - Pydantic model field
_.EmailImportanceLevelEnum  # noqa - Pydantic enum class
_.URGENT  # noqa - Pydantic enum value
_.LOW  # noqa - Pydantic enum value

# apps/api/app/models/mcp_config.py
_.handoff_tool_name  # noqa - Pydantic model field

# apps/api/app/models/memory_models.py
_.expiration_date  # noqa - Pydantic model field
_.immutable  # noqa - Pydantic model field
_.organization  # noqa - Pydantic model field
_.relationship  # noqa - Pydantic model field
_.target_type  # noqa - Pydantic model field

# apps/api/app/models/message_models.py
_.calendarId  # noqa - Pydantic model field
_.backgroundColor  # noqa - Pydantic model field

# apps/api/app/models/models_models.py
_.OPENAI  # noqa - Pydantic enum value

# apps/api/app/models/notes_models.py
_.plaintext  # noqa - Pydantic model field

# apps/api/app/models/notification/notification_models.py
_.WARNING  # noqa - Pydantic enum value
_.AI_EMAIL_DRAFT  # noqa - Pydantic enum value
_.AI_CALENDAR_EVENT  # noqa - Pydantic enum value
_.AI_TODO_SUGGESTION  # noqa - Pydantic enum value
_.AI_TODO_ADDED  # noqa - Pydantic enum value
_.EMAIL_TRIGGER  # noqa - Pydantic enum value
_.BACKGROUND_JOB  # noqa - Pydantic enum value
_.DANGER  # noqa - Pydantic enum value
_.scheduled_for  # noqa - Pydantic model field
_.retry_count  # noqa - Pydantic model field
_.archived_at  # noqa - Pydantic model field
_.next_actions  # noqa - Pydantic model field
_.update_action  # noqa - Pydantic model field

# apps/api/app/models/oauth_models.py
_.oauth_endpoints  # noqa - Pydantic model field

# apps/api/app/models/payment_models.py
_.ACTIVE  # noqa - Pydantic enum value
_.ON_HOLD  # noqa - Pydantic enum value
_.EXPIRED  # noqa - Pydantic enum value
_.max_users  # noqa - Pydantic model field
_.current_plan  # noqa - Pydantic model field
_.is_subscribed  # noqa - Pydantic model field
_.days_remaining  # noqa - Pydantic model field
_.can_upgrade  # noqa - Pydantic model field
_.can_downgrade  # noqa - Pydantic model field
_.has_subscription  # noqa - Pydantic model field
_.payment_completed  # noqa - Pydantic model field

# apps/api/app/models/platform_models.py
_.platformUserId  # noqa - Pydantic model field
_.connectedAt  # noqa - Pydantic model field
_.action_link  # noqa - Pydantic model field

# apps/api/app/models/support_models.py
_.IN_PROGRESS  # noqa - Pydantic enum value
_.RESOLVED  # noqa - Pydantic enum value
_.CLOSED  # noqa - Pydantic enum value
_.uploaded_at  # noqa - Pydantic model field
_.resolved_at  # noqa - Pydantic model field
_.tags  # noqa - Pydantic model field
_.support_request  # noqa - Pydantic model field

# apps/api/app/models/team_models.py  (same field names as about/blog models, already whitelisted above)

# apps/api/app/models/todo_models.py
_.has_next  # noqa - Pydantic model field
_.has_prev  # noqa - Pydantic model field
_.pending  # noqa - Pydantic model field
_.completion_rate  # noqa - Pydantic model field

# apps/api/app/models/trigger_configs.py
_.exclude_bot_messages  # noqa - Pydantic model field
_.exclude_direct_messages  # noqa - Pydantic model field
_.exclude_group_messages  # noqa - Pydantic model field
_.exclude_mpim_messages  # noqa - Pydantic model field
_.exclude_thread_replies  # noqa - Pydantic model field

# apps/api/app/models/usage_models.py
_.feature_title  # noqa - Pydantic model field
_.snapshot_date  # noqa - Pydantic model field

# apps/api/app/models/user_models.py
_.INITIAL  # noqa - Pydantic enum value
_.GETTING_STARTED  # noqa - Pydantic enum value

# apps/api/app/models/webhook_models.py
_.customer_id  # noqa - Pydantic model field
_.street  # noqa - Pydantic model field
_.zipcode  # noqa - Pydantic model field
_.business_id  # noqa - Pydantic model field
_.brand_id  # noqa - Pydantic model field
_.billing  # noqa - Pydantic model field
_.settlement_amount  # noqa - Pydantic model field
_.settlement_currency  # noqa - Pydantic model field
_.tax  # noqa - Pydantic model field
_.settlement_tax  # noqa - Pydantic model field
_.payment_method  # noqa - Pydantic model field
_.card_network  # noqa - Pydantic model field
_.card_type  # noqa - Pydantic model field
_.card_last_four  # noqa - Pydantic model field
_.card_issuing_country  # noqa - Pydantic model field
_.cancel_at_next_billing_date  # noqa - Pydantic model field
_.tax_inclusive  # noqa - Pydantic model field
_.trial_period_days  # noqa - Pydantic model field
_.on_demand  # noqa - Pydantic model field
_.addons  # noqa - Pydantic model field
_.discount_id  # noqa - Pydantic model field
_.connection_id  # noqa - Pydantic model field
_.connection_nano_id  # noqa - Pydantic model field
_.trigger_nano_id  # noqa - Pydantic model field

# apps/api/app/models/workflow_models.py
_.last_executed_at  # noqa - Pydantic model field
_.successful_executions  # noqa - Pydantic model field
_.instruction  # noqa - Pydantic model field

# apps/api/app/schemas/integrations/responses.py
_.oauth_url  # noqa - Pydantic model field
_.public_url  # noqa - Pydantic model field

# apps/api/app/services/platform_link_service.py
_.use_object_id  # noqa - Pydantic model field / service config

# apps/api/app/utils/document_utils.py
_.margins  # noqa - document configuration field
_.font_family  # noqa - document configuration field
_.line_spacing  # noqa - document configuration field
_.paper_size  # noqa - document configuration field
_.document_class  # noqa - document configuration field
_.table_of_contents  # noqa - document configuration field
_.number_sections  # noqa - document configuration field

# apps/api/app/utils/webhook_utils.py
_.version  # noqa - webhook field

# apps/api/app/agents/memory/skill_learning/models.py
_.last_used_at  # noqa - Pydantic model field
_.extraction_time_ms  # noqa - Pydantic model field

# apps/api/app/models/composio_schemas/context_tools.py
_.unread_count  # noqa - Pydantic model field (GmailContextData, SlackContextData)
_.cards  # noqa - Pydantic model field (TrelloContextData)

# apps/api/app/models/composio_schemas/slack_tools.py
_.types  # noqa - Pydantic model field (SlackListAllChannelsInput)
