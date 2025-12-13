"""
Monkey patch for Composio SDK to add unique request ID tracking.

This patch modifies the Tools.execute() method to inject a unique request_id
that is available in both before_execute and after_execute modifiers,
but is NOT included in the actual tool execution request.

Flow:
1. execute() generates UUID at the start
2. request_id is added to arguments dict (accessible in before_execute hooks via params["arguments"][REQUEST_ID_KEY])
3. request_id is removed from arguments dict before actual API call
4. request_id is added to response["data"] dict (accessible in after_execute hooks via response["data"][REQUEST_ID_KEY])

Usage in hooks:
    from app.patches.composio_request_id import REQUEST_ID_KEY

    # In before_execute hook
    def my_hook(tool: str, toolkit: str, params: ToolExecuteParams) -> ToolExecuteParams:
        request_id = params.get("arguments", {}).get(REQUEST_ID_KEY)  # Available here
        logger.info(f"[{request_id}] Starting {tool}")
        return params

    # In after_execute hook
    def my_hook(tool: str, toolkit: str, response: ToolExecutionResponse) -> ToolExecutionResponse:
        request_id = response.get("data", {}).get(REQUEST_ID_KEY)  # Same ID available here
        logger.info(f"[{request_id}] Completed {tool}")
        return response
"""

import uuid

from app.config.loggers import app_logger as logger
from app.constants.keys import REQUEST_ID_KEY


def patch_composio_request_id():
    """
    Patch Composio SDK Tools.execute() to add request_id tracking.

    The request_id flows through the execution pipeline:
    - Generated once at start of execute()
    - Available in before_execute hooks via params dict
    - Removed before actual tool execution (not sent to API)
    - Injected into response for after_execute hooks
    """
    try:
        from composio.core.models.tools import Tools

        def patched_execute(
            self,
            slug,
            arguments,
            *,
            connected_account_id=None,
            custom_auth_params=None,
            custom_connection_data=None,
            user_id=None,
            text=None,
            version=None,
            modifiers=None,
        ):
            """
            Patched execute that injects request_id for tracking.

            The request_id is added to the request dict that flows to before_execute,
            then removed before actual execution, then added to response for after_execute.
            """
            # Generate unique request ID for this execution
            request_id = str(uuid.uuid4())

            # Get the tool schema
            tool = self._tool_schemas.get(slug)
            if tool is None and self._custom_tools.get(slug=slug) is not None:
                tool = self._custom_tools[slug].info
                self._tool_schemas[slug] = tool

            if tool is None:
                tool = self._client.tools.retrieve(tool_slug=slug)
                self._tool_schemas[slug] = tool

            # Apply before_execute modifiers with request_id
            if modifiers is not None:
                from composio.core.models._modifiers import apply_modifier_by_type

                # Create request dict with request_id in arguments
                processed_params = apply_modifier_by_type(
                    modifiers=modifiers,
                    toolkit=tool.toolkit.slug,
                    tool=slug,
                    type="before_execute",
                    request={
                        "connected_account_id": connected_account_id,
                        "custom_auth_params": custom_auth_params,
                        "custom_connection_data": custom_connection_data,
                        "version": version,
                        "text": text,
                        "user_id": user_id,
                        "arguments": {
                            **(arguments if isinstance(arguments, dict) else {}),
                            REQUEST_ID_KEY: request_id,
                        },
                    },
                )

                # Extract processed values
                connected_account_id = processed_params["connected_account_id"]
                custom_auth_params = processed_params["custom_auth_params"]
                custom_connection_data = processed_params["custom_connection_data"]
                text = processed_params["text"]
                version = processed_params["version"]
                user_id = processed_params["user_id"]
                arguments = processed_params["arguments"]

            # Process file uploads
            arguments = self._file_helper.substitute_file_uploads(
                tool=tool,
                request=arguments,
            )

            # Execute the tool (without request_id)
            response = (
                self._execute_custom_tool(slug=slug, arguments=arguments)
                if self._custom_tools.get(slug) is not None
                else self._execute_tool(
                    slug=slug,
                    arguments=arguments,
                    connected_account_id=connected_account_id,
                    custom_auth_params=custom_auth_params,
                    custom_connection_data=custom_connection_data,
                    user_id=user_id,
                    text=text,
                    version=version,
                )
            )

            # Process file downloads
            response = self._file_helper.substitute_file_downloads(
                tool=tool,
                response=response,
            )

            # Apply after_execute modifiers with request_id
            if modifiers is not None:
                from composio.core.models._modifiers import apply_modifier_by_type

                # Inject request_id into response["data"] for after_execute hooks
                if isinstance(response, dict):
                    if "data" not in response:
                        response["data"] = {}
                    if isinstance(response["data"], dict):
                        response["data"][REQUEST_ID_KEY] = request_id

                response = apply_modifier_by_type(
                    modifiers=modifiers,
                    toolkit=tool.toolkit.slug,
                    tool=slug,
                    type="after_execute",
                    response=response,  # type: ignore
                )

                # Clean up request_id from response["data"] before returning
                if isinstance(response, dict) and isinstance(
                    response.get("data"), dict
                ):
                    if REQUEST_ID_KEY in response["data"]:
                        response["data"] = {
                            k: v
                            for k, v in response["data"].items()
                            if k != REQUEST_ID_KEY
                        }

            return response

        # Apply the patch
        Tools.execute = patched_execute  # type: ignore

        logger.info(
            "Successfully patched Composio SDK Tools.execute() for request_id tracking"
        )

    except ImportError as e:
        logger.warning(f"Could not patch Composio SDK: {e}")
    except AttributeError as e:
        logger.warning(f"Composio SDK API may have changed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error patching Composio SDK: {e}", exc_info=True)


# Apply patch when module is imported
patch_composio_request_id()
