"""
Centralized application logger definitions for the GAIA backend system.

This module re-exports loggers from gaia_shared and provides additional
domain-specific loggers for the API application.

Usage:
    from app.config.loggers import auth_logger, mongo_logger

    auth_logger.info("User authenticated successfully")
    mongo_logger.error("Database connection failed")
"""

# Re-export from shared library
from shared.py.logging import get_contextual_logger, configure_loguru, logger

# Pre-configured contextual loggers for different application domains
app_logger = get_contextual_logger("main")
worker_logger = get_contextual_logger("worker")
arq_worker_logger = get_contextual_logger("arq:worker")
llm_logger = get_contextual_logger("llm")
audio_logger = get_contextual_logger("audio")
goals_logger = get_contextual_logger("goals")
auth_logger = get_contextual_logger("auth")
cloudinary_logger = get_contextual_logger("cloudinary")
mongo_logger = get_contextual_logger("mongodb")
chroma_logger = get_contextual_logger("chromadb")
redis_logger = get_contextual_logger("redis")
calendar_logger = get_contextual_logger("calendar")
chat_logger = get_contextual_logger("chat")
image_logger = get_contextual_logger("image")
notes_logger = get_contextual_logger("notes")
search_logger = get_contextual_logger("search")
profiler_logger = get_contextual_logger("profiler")
general_logger = get_contextual_logger("general")
langchain_logger = get_contextual_logger("langchain")
request_logger = get_contextual_logger("requests")
notification_logger = get_contextual_logger("notification")
mail_webhook_logger = get_contextual_logger("mail_webhook")
common_logger = get_contextual_logger("common")
todos_logger = get_contextual_logger("todos")
memory_logger = get_contextual_logger("memory")
blogs_logger = get_contextual_logger("blogs")
reminders_logger = get_contextual_logger("reminders")
usage_logger = get_contextual_logger("usage")
token_repository_logger = get_contextual_logger("token_repository")

__all__ = [
    "logger",
    "configure_loguru",
    "get_contextual_logger",
    "app_logger",
    "worker_logger",
    "arq_worker_logger",
    "llm_logger",
    "audio_logger",
    "goals_logger",
    "auth_logger",
    "cloudinary_logger",
    "mongo_logger",
    "chroma_logger",
    "redis_logger",
    "calendar_logger",
    "chat_logger",
    "image_logger",
    "notes_logger",
    "search_logger",
    "profiler_logger",
    "general_logger",
    "langchain_logger",
    "request_logger",
    "notification_logger",
    "mail_webhook_logger",
    "common_logger",
    "todos_logger",
    "memory_logger",
    "blogs_logger",
    "reminders_logger",
    "usage_logger",
    "token_repository_logger",
]
