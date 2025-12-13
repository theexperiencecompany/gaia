"""
Centralized application logger definitions for the GAIA backend system.

This module provides pre-configured, contextual loggers for all major application components.
Each logger is optimized for its specific domain with appropriate formatting, filtering,
and routing through the advanced logging infrastructure.

Features:
- Domain-specific loggers for different application areas (auth, database, API, etc.)
- Consistent naming and context injection across all loggers
- Automatic integration with the centralized logging configuration
- Easy-to-use logger instances ready for import and immediate use

Usage:
    from app.config.loggers import auth_logger, mongo_logger

    auth_logger.info("User authenticated successfully")
    mongo_logger.error("Database connection failed")

All loggers automatically include contextual information such as timestamps,
log levels, source locations, and are routed through the configured file
handlers for proper log management and retention.
"""

from app.config.logging import get_contextual_logger

# Pre-configured contextual loggers for different application domains
# Each logger includes domain-specific context and routing configuration
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
