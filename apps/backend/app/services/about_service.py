"""
Service layer for about page functionality.
"""

from app.models.about_models import AboutResponse, Author


async def get_about_content() -> AboutResponse:
    """
    Get the about page content.

    Returns:
        AboutResponse: The about page content with authors and markdown content
    """

    # About content in markdown format
    about_content = """
# About GAIA

GAIA is your personal AI assistant designed to enhance productivity, automate tasks, and assist in daily activities. Built with cutting-edge artificial intelligence technology, GAIA helps you manage your digital life more efficiently.

## Our Mission

We believe that AI should be accessible, helpful, and seamlessly integrated into your daily workflow. GAIA is designed to understand your needs and provide intelligent assistance across various tasks, from managing your calendar and emails to helping with research and productivity.

## What Makes GAIA Special

### 🎯 **Personalized Experience**
GAIA learns from your preferences and adapts to your working style, providing increasingly personalized assistance over time.

### 🔗 **Seamless Integration**
Connect with your favorite tools and services. GAIA integrates with Google Calendar, Gmail, and many other popular platforms.

### 🛡️ **Privacy First**
Your data security and privacy are our top priorities. GAIA processes your information securely and transparently.

### 🚀 **Continuous Learning**
Our AI models are constantly improving, bringing you the latest advancements in artificial intelligence technology.

## Key Features

- **Smart Calendar Management**: Schedule meetings, set reminders, and manage your time effectively
- **Email Intelligence**: Compose, organize, and manage your emails with AI assistance
- **Task Organization**: Keep track of your todos, goals, and projects
- **Research Assistant**: Get help with research, data analysis, and information gathering
- **Memory System**: GAIA remembers important information to provide better context
- **Multi-modal Support**: Work with text, images, and documents seamlessly

## Technology Stack

GAIA is built using modern, scalable technologies:

- **Frontend**: Next.js with TypeScript and Tailwind CSS
- **Backend**: FastAPI with Python
- **AI Models**: Advanced language models for natural language processing
- **Database**: MongoDB for flexible data storage
- **Security**: OAuth 2.0 and enterprise-grade security measures

## Our Vision

We envision a future where AI assistants are not just tools, but intelligent companions that understand, learn, and grow with you. GAIA represents our commitment to making this vision a reality.

## Get Started

Ready to experience the future of personal AI assistance? Get started with GAIA today and discover how AI can transform your productivity and workflow.

---

*Thank you for choosing GAIA. We're excited to be part of your journey toward enhanced productivity and intelligent automation.*
"""

    # Author information
    authors = [
        Author(
            name="Aryan Randeriya",
            avatar="https://i.pravatar.cc/150?u=AryanRanderiya",
            role="Founder & Lead Developer",
            linkedin="https://linkedin.com/in/aryanranderiya",
            twitter="https://twitter.com/aryanranderiya",
        ),
        Author(
            name="GAIA Development Team",
            avatar="https://i.pravatar.cc/150?u=GAIATeam",
            role="Core Contributors",
            linkedin="https://linkedin.com/company/gaia-ai",
            twitter="https://twitter.com/gaia_ai",
        ),
    ]

    return AboutResponse(content=about_content, authors=authors)
