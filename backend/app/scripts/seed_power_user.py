import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from bson import ObjectId
import httpx

from app.db.mongodb.mongodb import init_mongodb
from app.db.postgresql import init_postgresql_engine
from app.config.token_repository import token_repository
from app.services.conversation_service import create_conversation_service, update_messages
from app.models.chat_models import ConversationModel, UpdateMessagesRequest, MessageModel
from app.services.todos.todo_service import TodoService, ProjectService
from app.models.todo_models import TodoModel, ProjectCreate, Priority
from app.services.goals_service import create_goal_service, update_goal_with_roadmap_service
from app.models.goals_models import GoalCreate
from app.services.calendar_service import create_calendar_event, list_calendars
from app.models.calendar_models import EventCreateRequest
from app.db.mongodb.collections import calendars_collection

# User ID from the request
USER_ID = "692b8cab6f6cd30e6e87d083"
USER_EMAIL = "s.aryan.randeriya@gmail.com"
USER_NAME = "Aryan"

# Mock User Object
USER = {
    "user_id": USER_ID, # Service expects "user_id" in dict
    "_id": ObjectId(USER_ID),
    "name": USER_NAME,
    "email": USER_EMAIL,
}

async def get_google_access_token(user_id: str) -> str:
    token = await token_repository.get_token(user_id, "google", renew_if_expired=True)
    if not token or "access_token" not in token:
        raise Exception("No Google access token found for user")
    return token["access_token"]

async def create_calendar_if_not_exists(access_token: str, summary: str) -> str:
    """Creates a calendar if it doesn't exist, returns calendar ID."""
    # List existing calendars
    try:
        calendars_data = await list_calendars(access_token, short=True)
        calendars = calendars_data if isinstance(calendars_data, list) else calendars_data.get("items", [])
        for cal in calendars:
            if cal.get("summary") == summary:
                return cal["id"]
    except Exception as e:
        print(f"Error listing calendars: {e}")
    
    # Create new calendar
    url = "https://www.googleapis.com/calendar/v3/calendars"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {"summary": summary}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.json()["id"]
        else:
            print(f"Failed to create calendar {summary}: {response.text}")
            return None

async def seed_calendars(user_id: str):
    print("Seeding Calendars...")
    try:
        access_token = await get_google_access_token(user_id)
    except Exception as e:
        print(f"Skipping calendar seeding: {e}")
        return

    calendar_names = [
        "University", "Work", "Fitness", "Social", "Projects", "Learning", "Content Creation"
    ]
    
    calendar_ids = []
    
    # Create Calendars
    for name in calendar_names:
        cal_id = await create_calendar_if_not_exists(access_token, name)
        if cal_id:
            calendar_ids.append(cal_id)
            print(f"Created/Found calendar: {name} ({cal_id})")

    # Update selected calendars in DB
    if calendar_ids:
        await calendars_collection.update_one(
            {"user_id": user_id},
            {"$set": {"selected_calendars": calendar_ids}},
            upsert=True
        )

    # Seed Events
    now = datetime.now(timezone.utc)
    start_of_week = now - timedelta(days=now.weekday())
    
    for i in range(-7, 14): # Previous week, current week, next week
        day = start_of_week + timedelta(days=i)
        
        # Add some random events
        if calendar_ids:
            # 3-5 events per day
            num_events = random.randint(3, 5)
            for _ in range(num_events):
                cal_id = random.choice(calendar_ids)
                hour = random.randint(8, 18)
                duration = random.choice([30, 60, 90])
                
                start_time = day.replace(hour=hour, minute=0, second=0, microsecond=0)
                end_time = start_time + timedelta(minutes=duration)
                
                event_titles = [
                    "Meeting with Team", "Study Session", "Gym", "Lunch", "Code Review",
                    "Project Planning", "Client Call", "Research", "Writing", "Brainstorming"
                ]
                
                event = EventCreateRequest(
                    summary=random.choice(event_titles),
                    description="Seeded event",
                    start=start_time.isoformat(),
                    end=end_time.isoformat(),
                    calendar_id=cal_id,
                    timezone="Asia/Kolkata" # IST
                )
                
                try:
                    await create_calendar_event(event, access_token, user_id)
                except Exception as e:
                    print(f"Failed to create event: {e}")

    print("Calendars seeded.")

async def seed_chats(user_id: str):
    print("Seeding Chats...")
    chat_topics = [
        "Python Learning Strategy", "Project Management Help", "Weekly Review", 
        "Debug Login Issue", "Brainstorming Marketing Ideas", "React Performance Tuning",
        "Database Schema Design", "API Documentation", "User Interview Questions",
        "Competitor Analysis", "Content Calendar Planning", "System Architecture Review",
        "Deployment Pipeline Setup", "Security Audit", "UX Design Critique"
    ]
    
    for topic in chat_topics:
        # Generate a new conversation ID
        convo_id = str(ObjectId())
        convo = ConversationModel(
            conversation_id=convo_id,
            description=topic,
            is_system_generated=False
        )
        # Service expects conversation object and user dict
        await create_conversation_service(convo, USER)
        
        # Add some messages
        messages = [
            MessageModel(type="human", response=f"Let's talk about {topic}"),
            MessageModel(type="ai", response=f"Sure, I can help with {topic}. What's on your mind?"),
            MessageModel(type="human", response="I need some specific advice."),
            MessageModel(type="ai", response="Go ahead, I'm listening.")
        ]
        
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=convo_id,
                messages=messages
            ),
            USER
        )
    print("Chats seeded.")

async def seed_todos(user_id: str):
    print("Seeding Todos...")
    
    # Create Projects
    projects_config = [
        {"name": "Work", "color": "#FF5733"},      # Red-ish
        {"name": "Personal", "color": "#33FF57"},  # Green-ish
        {"name": "Learning", "color": "#3357FF"},  # Blue-ish
    ]
    project_ids = {}
    
    for config in projects_config:
        proj = await ProjectService.create_project(
            ProjectCreate(name=config["name"], color=config["color"]),
            user_id
        )
        # proj is a Pydantic model
        project_ids[config["name"]] = proj.id
        
    # Create Todos
    todo_data = [
        ("Finish Q4 Report", "Work", Priority.HIGH, 2),
        ("Buy Groceries", "Personal", Priority.MEDIUM, 0),
        ("Read 'Clean Code'", "Learning", Priority.LOW, 5),
        ("Gym Workout", "Personal", Priority.HIGH, 0),
        ("Update Portfolio", "Learning", Priority.MEDIUM, 3),
        ("Email Client", "Work", Priority.HIGH, 1),
        ("Plan Weekend Trip", "Personal", Priority.LOW, 7),
        ("Learn Rust Basics", "Learning", Priority.MEDIUM, 10),
        ("Dentist Appointment", "Personal", Priority.HIGH, 4),
        ("Fix Bug #123", "Work", Priority.HIGH, 0),
        ("Call Mom", "Personal", Priority.MEDIUM, 0),
        ("Watch Tutorial", "Learning", Priority.LOW, 1),
        ("Meal Prep", "Personal", Priority.MEDIUM, 1),
        ("Deploy App", "Work", Priority.HIGH, 2),
        ("Review PRs", "Work", Priority.HIGH, 0),
    ]
    
    for title, proj_name, priority, days_due in todo_data:
        due_date = None
        if days_due > 0:
            due_date = datetime.now(timezone.utc) + timedelta(days=days_due)
            
        todo = TodoModel(
            title=title,
            project_id=project_ids.get(proj_name),
            priority=priority,
            due_date=due_date,
            labels=[proj_name.lower(), "important"] if random.random() > 0.5 else []
        )
        await TodoService.create_todo(todo, user_id)
        
    print("Todos seeded.")

async def seed_goals(user_id: str):
    print("Seeding Goals...")
    
    goal_title = "Master Python Programming"
    goal = GoalCreate(
        title=goal_title,
        description="Become proficient in Python for data science and web dev."
    )
    
    created_goal = await create_goal_service(goal, USER)
    # created_goal is a Pydantic model
    goal_id = created_goal.id
    
    # Comprehensive Roadmap
    roadmap = {
        "nodes": [
            {"id": "1", "label": "Python Basics", "status": "completed"},
            {"id": "2", "label": "Data Structures", "status": "in_progress"},
            {"id": "3", "label": "OOP Concepts", "status": "pending"},
            {"id": "4", "label": "Web Development (FastAPI)", "status": "pending"},
            {"id": "5", "label": "Data Science (Pandas/NumPy)", "status": "pending"},
            {"id": "6", "label": "Testing & CI/CD", "status": "pending"},
            {"id": "7", "label": "Final Project", "status": "pending"}
        ],
        "edges": [
            {"source": "1", "target": "2"},
            {"source": "2", "target": "3"},
            {"source": "3", "target": "4"},
            {"source": "3", "target": "5"},
            {"source": "4", "target": "6"},
            {"source": "5", "target": "6"},
            {"source": "6", "target": "7"}
        ]
    }
    
    await update_goal_with_roadmap_service(goal_id, roadmap)
    print("Goals seeded.")

async def main():
    init_mongodb()
    
    # Register the provider (returns LazyLoader, don't await)
    init_postgresql_engine()
    
    # Force initialization by getting the engine
    from app.core.lazy_loader import providers
    await providers.aget("postgresql_engine")
    
    await asyncio.gather(
        seed_chats(USER_ID),
        seed_todos(USER_ID),
        seed_goals(USER_ID),
        seed_calendars(USER_ID)
    )
    print("Seeding complete!")

if __name__ == "__main__":
    asyncio.run(main())
