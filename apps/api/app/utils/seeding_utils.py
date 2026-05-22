from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from shared.py.wide_events import log
from app.db.mongodb.collections import conversations_collection
from app.models.chat_models import (
    ConversationModel,
)
from app.models.todo_models import Priority, SubTask, TodoModel
from app.services.conversation_service import (
    create_conversation_service,
)
from app.services.todos.todo_service import TodoService


async def seed_onboarding_todo(user_id: str) -> None:
    """
    Create a comprehensive onboarding todo that showcases all todo features.
    This is separate from the goal-linked todo to demonstrate standalone todo functionality.
    """
    log.set(operation="seed_onboarding_todo", user_id=user_id)
    try:
        due_date = datetime.now(timezone.utc) + timedelta(days=1)

        # Create subtasks that guide users through all todo features
        subtasks = [
            SubTask(
                id=str(uuid4()),
                title="✅ Mark this subtask as complete to see progress tracking",
                completed=False,
            ),
            SubTask(
                id=str(uuid4()),
                title="📝 Edit the todo title or description by clicking on it",
                completed=False,
            ),
            SubTask(
                id=str(uuid4()),
                title="🏷️ Try adding or removing labels for organization",
                completed=False,
            ),
            SubTask(
                id=str(uuid4()),
                title="⭐ Change the priority level (try high, medium, or low)",
                completed=False,
            ),
            SubTask(
                id=str(uuid4()),
                title="📅 Modify the due date to see how scheduling works",
                completed=False,
            ),
            SubTask(
                id=str(uuid4()),
                title="📁 Move this todo to a different project",
                completed=False,
            ),
            SubTask(
                id=str(uuid4()),
                title="➕ Add your own custom subtask to this list",
                completed=False,
            ),
        ]

        # Create the onboarding todo
        todo = TodoModel(
            title="Welcome to Todos! Explore all the features 🎉",
            description=(
                "This interactive todo helps you discover everything you can do with tasks in Gaia.\n\n"
                "**Features to try:**\n"
                "• Complete subtasks to track your progress\n"
                "• Edit title, description, and details\n"
                "• Add labels like #work, #personal, or #learning\n"
                "• Set priorities to organize by importance\n"
                "• Adjust due dates and get reminders\n"
                "• Move between projects (like Inbox, Work, etc.)\n"
                "• Create your own subtasks for breaking down work\n\n"
                "**Pro tips:**\n"
                "✨ Use Gaia AI to auto-generate todos from conversations\n"
                "🔗 Link todos to goals for visual roadmap tracking\n"
                "🔍 Search and filter todos by label, priority, or date\n\n"
                "Complete the subtasks to learn by doing, then create your first real todo!"
            ),
            labels=["tutorial", "getting-started"],
            priority=Priority.HIGH,
            due_date=due_date,
            due_date_timezone="UTC",
            subtasks=subtasks,
            project_id=None,  # Will be added to Inbox
        )

        # Create the todo using the service
        await TodoService.create_todo(todo, user_id)
        log.info(f"Seeded onboarding todo for user {user_id}")

    except Exception as e:
        log.error(f"Failed to seed onboarding todo for user {user_id}: {e}")


async def seed_onboarding_conversation(user_id: str) -> Optional[str]:
    """Create the empty welcome conversation tagged is_onboarding_conversation=True.

    Left empty on purpose: the frontend renders WelcomeChat instead, so mirroring
    the wrap-up message here would create a ghost row.
    """
    log.set(operation="seed_onboarding_conversation", user_id=user_id)
    try:
        conversation_id = str(uuid4())
        conversation = ConversationModel(
            conversation_id=conversation_id,
            description="Your personalized GAIA setup",
            is_system_generated=False,
            is_unread=True,
        )

        user_dict = {"user_id": user_id}
        await create_conversation_service(conversation, user_dict)

        await conversations_collection.update_one(
            {"conversation_id": conversation_id},
            {"$set": {"is_onboarding_conversation": True}},
        )

        log.info(f"Seeded onboarding conversation {conversation_id} for user {user_id}")
        return conversation_id

    except Exception as e:
        log.error(f"Failed to seed onboarding conversation for user {user_id}: {e}")
        return None
