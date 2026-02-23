# Vulture whitelist — suppress known false positives
# Add entries as: `variable_name  # noqa`
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

# Pytest fixtures
import pytest  # noqa

_.fixture  # noqa
_.mark  # noqa

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
_.CUSTOM_CREATE_TEST_PAGE  # noqa
_.CUSTOM_BATCH_FOLLOW  # noqa
_.CUSTOM_BATCH_UNFOLLOW  # noqa
