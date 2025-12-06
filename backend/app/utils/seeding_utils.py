import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import goals_collection
from app.models.chat_models import (
    ConversationModel,
    MessageModel,
    UpdateMessagesRequest,
)
from app.models.todo_models import Priority
from app.services.conversation_service import (
    create_conversation_service,
    update_messages,
)
from app.services.todos.sync_service import create_goal_project_and_todo


async def seed_initial_goal(user_id: str) -> None:
    """
    Create a dummy goal with a full roadmap to showcase features.
    """
    try:
        # Create a comprehensive instructional roadmap to help users explore all goal features
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

        # Direct DB insert with roadmap included to avoid multiple DB operations
        goal_data = {
            "title": "Explore Gaia's Goal Tracking",
            "description": "A comprehensive guide to help you discover all the powerful features of goal tracking in Gaia. Complete the roadmap to learn everything!",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "roadmap": roadmap_data,
        }

        result = await goals_collection.insert_one(goal_data)
        goal_id = str(result.inserted_id)

        due_date = datetime.now(timezone.utc)
        due_date = due_date.replace(hour=17, minute=0, second=0, microsecond=0)  # 5 PM

        await create_goal_project_and_todo(
            goal_id=goal_id,
            goal_title=str(goal_data.get("title", "")),
            roadmap_data=roadmap_data,
            user_id=user_id,
            labels=["onboarding"],
            priority=Priority.HIGH,
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
            "Hey! I'm Gaia, your personal AI assistant.<NEW_MESSAGE_BREAK>"
            "I'm here to help you organize your life, manage your tasks, and get things done.<NEW_MESSAGE_BREAK>"
            "You can ask me to create todos, set goals, or just chat about your day.<NEW_MESSAGE_BREAK>"
            "What's on your mind?"
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


async def seed_initial_user_data(user_id: str) -> None:
    """
    Seed initial data for a new user (dummy todo, goal, and conversation).
    Runs tasks in parallel to minimize background processing time.
    """
    try:
        logger.info(f"Starting parallel data seeding for user {user_id}")

        # Run seeding tasks in parallel
        # Note: Goal seeding automatically creates a comprehensive linked todo
        await asyncio.gather(
            seed_initial_goal(user_id),
            seed_initial_conversation(user_id),
        )

        logger.info(f"Completed parallel data seeding for user {user_id}")

    except Exception as e:
        logger.error(f"Error in seed_initial_user_data for user {user_id}: {e}")
