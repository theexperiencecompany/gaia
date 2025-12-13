from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import goals_collection
from app.models.chat_models import (
    ConversationModel,
    MessageModel,
    UpdateMessagesRequest,
)
from app.models.todo_models import Priority, SubTask, TodoModel
from app.services.conversation_service import (
    create_conversation_service,
    update_messages,
)
from app.services.todos.sync_service import create_goal_project_and_todo
from app.services.todos.todo_service import TodoService


async def seed_initial_goal(user_id: str) -> None:
    """
    Create a dummy goal with a full roadmap to showcase features.
    """
    try:
        roadmap_data = {
            "nodes": [
                {
                    "id": "start",
                    "type": "default",
                    "data": {
                        "label": "Welcome to Goals! 🎯",
                        "description": "Goals help you break down big objectives into visual roadmaps. This sample shows you how!",
                        "isComplete": True,
                    },
                    "position": {"x": 400, "y": 0},
                },
                {
                    "id": "node1",
                    "type": "default",
                    "data": {
                        "label": "Check Your Todos 📝",
                        "description": "Look in your 'Goals' project! This goal automatically created a linked todo with subtasks for each node.",
                        "isComplete": False,
                    },
                    "position": {"x": 100, "y": 150},
                },
                {
                    "id": "node2",
                    "type": "default",
                    "data": {
                        "label": "Try Two-Way Sync ⚡",
                        "description": "Mark a subtask complete in your todo and watch this roadmap update automatically! Or mark this node complete and see the todo change.",
                        "isComplete": False,
                    },
                    "position": {"x": 400, "y": 150},
                },
                {
                    "id": "node3",
                    "type": "default",
                    "data": {
                        "label": "Explore the Roadmap 🗺️",
                        "description": "Drag nodes around, zoom in/out, and navigate this visual map of your goal's milestones.",
                        "isComplete": False,
                    },
                    "position": {"x": 700, "y": 150},
                },
                {
                    "id": "node4",
                    "type": "default",
                    "data": {
                        "label": "AI Roadmap Generation ✨",
                        "description": "Create a new goal and use AI to automatically generate a roadmap! Just enter your goal title.",
                        "isComplete": False,
                    },
                    "position": {"x": 200, "y": 300},
                },
                {
                    "id": "node5",
                    "type": "default",
                    "data": {
                        "label": "Track Your Progress 📊",
                        "description": "See completion percentages and track which milestones are done. Goals keep you focused on the big picture!",
                        "isComplete": False,
                    },
                    "position": {"x": 600, "y": 300},
                },
                {
                    "id": "end",
                    "type": "default",
                    "data": {
                        "label": "Create Your First Real Goal! 🚀",
                        "description": "Now that you know how goals work, create one that matters to you. Delete this sample goal when you're ready!",
                        "isComplete": False,
                    },
                    "position": {"x": 400, "y": 450},
                },
            ],
            "edges": [
                {
                    "id": "e-start-1",
                    "source": "start",
                    "target": "node1",
                    "animated": True,
                },
                {
                    "id": "e-start-2",
                    "source": "start",
                    "target": "node2",
                    "animated": True,
                },
                {
                    "id": "e-start-3",
                    "source": "start",
                    "target": "node3",
                    "animated": True,
                },
                {"id": "e-1-4", "source": "node1", "target": "node4", "animated": True},
                {"id": "e-2-5", "source": "node2", "target": "node5", "animated": True},
                {"id": "e-3-5", "source": "node3", "target": "node5", "animated": True},
                {"id": "e-4-end", "source": "node4", "target": "end", "animated": True},
                {"id": "e-5-end", "source": "node5", "target": "end", "animated": True},
            ],
        }

        goal_data = {
            "title": "Explore Gaia's Goal Tracking",
            "description": "A comprehensive guide to help you discover all the powerful features of goal tracking in Gaia. Complete the roadmap to learn everything!",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "roadmap": roadmap_data,
        }

        result = await goals_collection.insert_one(goal_data)

        due_date = datetime.now(timezone.utc)

        await create_goal_project_and_todo(
            goal_id=str(result.inserted_id),
            goal_title="This is a todo linked to your Goals roadmap!",
            roadmap_data=roadmap_data,
            user_id=user_id,
            labels=["onboarding"],
            priority=Priority.MEDIUM,
            due_date=due_date,
            due_date_timezone="UTC",
        )

        logger.info(f"Seeded initial goal for user {user_id}")

    except Exception as e:
        logger.error(f"Failed to seed initial goal for user {user_id}: {e}")


async def seed_initial_conversation(user_id: str) -> None:
    """
    Seed an initial conversation with Gaia to welcome the user.
    """
    try:
        # Create a new conversation
        conversation_id = str(uuid4())
        conversation = ConversationModel(
            conversation_id=conversation_id,
            description="Welcome to Gaia",
            is_system_generated=False,
        )

        # We need to pass a dict with user_id to create_conversation_service
        user_dict = {"user_id": user_id}
        await create_conversation_service(conversation, user_dict)

        # Create the welcome message with breaks for bubbles
        welcome_message = (
            "Hey! I'm Gaia, your personal AI assistant—I'm here to help you actually get things done. 👋<NEW_MESSAGE_BREAK>"
            "Here's what I can help with: \n - 📧 Manage your Gmail inbox\n - 📅 Schedule calendar events\n - ✅ Create and track todos with smart workflows\n - 🎯 Set goals with visual roadmaps\n - 🔍 Search the web and generate images\n - 🧠 Remember important things about you and a lot more!<NEW_MESSAGE_BREAK>"
            "Try asking me to: Check your unread emails, create a task for something you need to do, set up a goal with a roadmap, search for information, or just tell me about your day so I can get to know you better!<NEW_MESSAGE_BREAK>"
            "What would you like to explore first?"
        )

        message = MessageModel(
            type="ai",
            response=welcome_message,
            date=datetime.now(timezone.utc).isoformat(),
        )

        update_request = UpdateMessagesRequest(
            conversation_id=conversation_id, messages=[message]
        )

        await update_messages(update_request, user_dict)
        logger.info(f"Seeded initial conversation for user {user_id}")

    except Exception as e:
        logger.error(f"Failed to seed initial conversation for user {user_id}: {e}")


async def seed_onboarding_todo(user_id: str) -> None:
    """
    Create a comprehensive onboarding todo that showcases all todo features.
    This is separate from the goal-linked todo to demonstrate standalone todo functionality.
    """
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
            labels=["onboarding", "tutorial", "getting-started"],
            priority=Priority.HIGH,
            due_date=due_date,
            due_date_timezone="UTC",
            subtasks=subtasks,
            project_id=None,  # Will be added to Inbox
        )

        # Create the todo using the service
        await TodoService.create_todo(todo, user_id)
        logger.info(f"Seeded onboarding todo for user {user_id}")

    except Exception as e:
        logger.error(f"Failed to seed onboarding todo for user {user_id}: {e}")
