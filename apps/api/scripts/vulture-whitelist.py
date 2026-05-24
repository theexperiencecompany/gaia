# Vulture whitelist — suppress known false positives
# Add entries as: `variable_name`
# See: https://github.com/jendrikseipp/vulture#whitelisting
# type: ignore  # mypy: vulture uses _ as a placeholder

# FastAPI/Pydantic
from pydantic import BaseModel  # noqa

_.model_config  # noqa
_.model_fields  # noqa

# loguru types imported under TYPE_CHECKING and used only in string
# annotations (record: "Record") — vulture can't see string annotations.
Message  # noqa
Record  # noqa
_.current_datetime  # noqa - Used in Pydantic models
_.mem0_user_id  # noqa - Used in agent state
_.memories_stored  # noqa - Used in agent state

# FastAPI dependencies & route decorators are used implicitly
# Vulture already handles decorators, but explicit overrides go here.

# Pytest fixtures
import pytest  # noqa

_.fixture  # noqa
_.mark  # noqa

# Composio hook modules — imported only for their decorator side effects in
# app/utils/composio_hooks/all_hooks.py. Removing them breaks hook registration.
gmail_hooks  # noqa
reddit_hooks  # noqa
slack_hooks  # noqa
twitter_hooks  # noqa
user_id_hooks  # noqa

# Parameters kept for API compatibility / framework callback signatures.
todo_source  # noqa - create_subagent_middleware: kept for API compatibility (see docstring)
old_md  # noqa - LiveKit participant_metadata_changed callback signature (p, old_md, new_md)

# Custom tool functions - registered dynamically via Composio
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
_.CUSTOM_BATCH_FOLLOW  # noqa
_.CUSTOM_BATCH_UNFOLLOW  # noqa
