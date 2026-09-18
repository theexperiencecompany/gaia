"""Jev decides every browser step as Browser-Use's chat model.

observation.py indexes the page into an element table, policy.py picks the operation and target
from it, and chat_model.py answers Browser-Use's calls. Policy and prompts derived from
browser-use/jev-ultrafast (MIT)."""

from app.services.browser.jev.chat_model import JevChatModel, build_jev_chat_model
from app.services.browser.jev.gateway import JevGatewayClient, JevGatewayError

__all__ = ["JevChatModel", "JevGatewayClient", "JevGatewayError", "build_jev_chat_model"]
