import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import Request

from app.config.loggers import notification_logger as logger
from app.models.notification.notification_models import (
    ActionResult,
    ActionType,
    NotificationAction,
    NotificationRecord,
    NotificationStatus,
)


class ActionHandler(ABC):
    """Base class for all action handlers"""

    @property
    @abstractmethod
    def action_type(self) -> str:
        pass

    @abstractmethod
    def can_handle(self, action: NotificationAction) -> bool:
        pass

    @abstractmethod
    async def execute(
        self,
        action: NotificationAction,
        notification: NotificationRecord,
        user_id: str,
        request: Optional[Request],
    ) -> ActionResult:
        pass


# Action Handlers
class ApiCallActionHandler(ActionHandler):
    """Handler for API call actions"""

    @property
    def action_type(self) -> str:
        return "api_call"

    def can_handle(self, action: NotificationAction) -> bool:
        return action.type == ActionType.API_CALL and action.config.api_call is not None

    async def execute(
        self,
        action: NotificationAction,
        notification: NotificationRecord,
        user_id: str,
        request: Optional[Request],
    ) -> ActionResult:
        api_config = action.config.api_call

        logger.info(api_config)

        if api_config is None:
            logging.error(
                f"API call configuration missing for action {action.id} in notification {notification.id}"
            )
            return ActionResult(
                success=False,
                message="API call configuration is missing",
                error_code="CONFIG_ERROR",
            )

        try:
            # Prepare headers with authentication
            headers = {
                "Content-Type": "application/json",
                "X-User-ID": user_id,
                "X-Notification-ID": notification.id,
                **(api_config.headers or {}),
            }

            # Prepare payload with context
            payload = {
                **(api_config.payload or {}),
                "user_id": user_id,
                "notification_id": notification.id,
                "action_id": action.id,
                "metadata": notification.original_request.metadata,
            }

            # If the action is internal, use the request base URL
            if request and api_config.is_internal:
                base_url = request.base_url
                api_config.endpoint = f"{base_url}{api_config.endpoint.lstrip('/')}"

            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=api_config.method,
                    url=api_config.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                    cookies=(
                        request.cookies if request and api_config.is_internal else None
                    ),
                )

                response.raise_for_status()
                result_data = response.json() if response.content else {}

                return ActionResult(
                    success=True,
                    message=api_config.success_message
                    or "Action completed successfully",
                    data=result_data,
                    update_notification={
                        "status": NotificationStatus.ARCHIVED,
                    },
                    update_action={
                        "executed": True,
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )

        except httpx.HTTPError as e:
            logger.error(
                f"API call failed for action {action.id} in notification {notification.id}: {str(e)}"
            )
            return ActionResult(
                success=False,
                message=api_config.error_message or f"API call failed: {str(e)}",
                error_code="API_ERROR",
            )
        except Exception as e:
            logger.error(
                f"Unexpected error during API call for action {action.id} in notification {notification.id}: {str(e)}"
            )
            return ActionResult(
                success=False,
                message=api_config.error_message or f"Unexpected error: {str(e)}",
                error_code="UNKNOWN_ERROR",
            )


class RedirectActionHandler(ActionHandler):
    """Handler for redirect actions (client-side)"""

    @property
    def action_type(self) -> str:
        return "redirect"

    def can_handle(self, action: NotificationAction) -> bool:
        return action.type == ActionType.REDIRECT and action.config.redirect is not None

    async def execute(
        self,
        action: NotificationAction,
        notification: NotificationRecord,
        user_id: str,
        request: Optional[Request],
    ) -> ActionResult:
        redirect_config = action.config.redirect

        if redirect_config is None:
            logging.error(
                f"Redirect configuration missing for action {action.id} in notification {notification.id}"
            )
            return ActionResult(
                success=False,
                message="Redirect configuration is missing",
                error_code="CONFIG_ERROR",
            )

        return ActionResult(
            success=True,
            message="Redirecting...",
            data={
                "redirect_url": redirect_config.url,
                "open_in_new_tab": redirect_config.open_in_new_tab,
            },
            update_notification={
                "status": (
                    NotificationStatus.READ
                    if redirect_config.close_notification
                    else None
                )
            },
        )


class ModalActionHandler(ActionHandler):
    """Handler for modal actions (client-side)"""

    @property
    def action_type(self) -> str:
        return "modal"

    def can_handle(self, action: NotificationAction) -> bool:
        return action.type == ActionType.MODAL and action.config.modal is not None

    async def execute(
        self,
        action: NotificationAction,
        notification: NotificationRecord,
        user_id: str,
        request: Optional[Request],
    ) -> ActionResult:
        modal_config = action.config.modal

        if modal_config is None:
            logging.error(
                f"Modal configuration missing for action {action.id} in notification {notification.id}"
            )
            return ActionResult(
                success=False,
                message="Modal configuration is missing",
                error_code="CONFIG_ERROR",
            )

        # Process template variables in modal props
        processed_props = self._process_template_variables(
            modal_config.props, notification.id, action.id, user_id
        )

        return ActionResult(
            success=True,
            message="Modal action executed successfully",
            data={
                "modal_component": modal_config.component,
                "modal_props": processed_props,
            },
            update_action={
                "executed": True,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _process_template_variables(
        self, props: dict, notification_id: str, action_id: str, user_id: str
    ) -> dict:
        """Process template variables in modal props"""
        if not props:
            return {}

        processed_props = {}
        template_map = {
            "{{notification_id}}": notification_id,
            "{{action_id}}": action_id,
            "{{user_id}}": user_id,
        }

        for key, value in props.items():
            if isinstance(value, str):
                # Replace template variables
                for template, replacement in template_map.items():
                    if template in value:
                        value = value.replace(template, replacement)
                processed_props[key] = value
            else:
                processed_props[key] = value

        return processed_props
