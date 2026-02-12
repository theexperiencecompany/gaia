export interface GlossaryTerm {
  slug: string;
  term: string;
  metaTitle: string;
  metaDescription: string;
  definition: string;
  extendedDescription: string;
  keywords: string[];
  category: string;
  howGaiaUsesIt: string;
  relatedTerms: string[];
  faqs: Array<{ question: string; answer: string }>;
}

export const glossaryTerms: Record<string, GlossaryTerm> = {
  "ai-agent": {
    slug: "ai-agent",
    term: "AI Agent",
    metaTitle:
      "What Is an AI Agent? Definition and How They Work",
    metaDescription:
      "An AI agent is autonomous software that perceives its environment, makes decisions, and takes actions to achieve goals. Learn how GAIA uses AI agents to manage your productivity.",
    definition:
      "An AI agent is an autonomous software system that perceives its environment, reasons about what to do, and takes actions to achieve specific goals without continuous human direction.",
    extendedDescription:
      "Unlike simple chatbots that respond to prompts, AI agents operate with autonomy. They observe their environment through data inputs, plan a course of action using reasoning capabilities, execute tasks using available tools, and learn from outcomes. Modern AI agents combine large language models for reasoning with tool-use capabilities to interact with external systems like email, calendars, and project management tools. The key distinction is autonomy: an AI agent does not merely answer questions but actively works toward completing objectives on your behalf.",
    keywords: [
      "AI agent",
      "autonomous AI",
      "intelligent agent",
      "AI agent definition",
      "what is an AI agent",
      "agentic software",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "GAIA is built as a multi-agent system powered by LangGraph. Its core agent monitors your email, calendar, and connected tools, then dispatches specialized subagents to handle tasks like drafting replies, scheduling meetings, or executing multi-step workflows across 50+ integrations. Each subagent is purpose-built for a specific domain, allowing GAIA to act proactively on your behalf.",
    relatedTerms: [
      "agentic-ai",
      "ai-orchestration",
      "langgraph",
      "proactive-ai",
    ],
    faqs: [
      {
        question: "What is the difference between an AI agent and a chatbot?",
        answer:
          "A chatbot responds to messages in a conversation. An AI agent autonomously perceives its environment, makes decisions, and takes actions across multiple tools and systems. GAIA is an AI agent that manages your email, calendar, and workflows without waiting for you to ask.",
      },
      {
        question: "How do AI agents improve productivity?",
        answer:
          "AI agents reduce the manual work of managing digital tools by autonomously handling repetitive tasks like email triage, meeting scheduling, and task creation. GAIA's agents work 24/7, monitoring your connected tools and acting before you need to ask.",
      },
    ],
  },

  "agentic-ai": {
    slug: "agentic-ai",
    term: "Agentic AI",
    metaTitle:
      "What Is Agentic AI? The Future of Autonomous Intelligence",
    metaDescription:
      "Agentic AI refers to AI systems that act autonomously, make decisions, and execute multi-step tasks. Learn how GAIA uses agentic AI to manage your digital life.",
    definition:
      "Agentic AI describes artificial intelligence systems designed to operate autonomously, making decisions and executing multi-step tasks with minimal human oversight.",
    extendedDescription:
      "Agentic AI represents a paradigm shift from reactive AI that waits for prompts to proactive AI that takes initiative. These systems combine planning, reasoning, tool use, and memory to accomplish complex objectives. An agentic AI system can break down a high-level goal into subtasks, determine which tools to use, execute actions across multiple platforms, handle errors gracefully, and refine its approach based on outcomes. This approach moves AI from being a question-answering tool to becoming a capable digital worker.",
    keywords: [
      "agentic AI",
      "autonomous AI",
      "AI autonomy",
      "agentic AI definition",
      "proactive artificial intelligence",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "GAIA embodies agentic AI by proactively managing your digital workflow. When an important email arrives, GAIA does not wait for you to read it. It reads the email, understands its context, creates relevant tasks, schedules follow-ups on your calendar, and drafts a reply. This multi-step, autonomous behavior across 50+ integrated tools is what makes GAIA agentic rather than merely conversational.",
    relatedTerms: [
      "ai-agent",
      "proactive-ai",
      "ai-orchestration",
      "human-in-the-loop",
    ],
    faqs: [
      {
        question: "What makes AI agentic?",
        answer:
          "AI becomes agentic when it can autonomously plan, decide, and act across multiple steps without requiring human input at each stage. GAIA demonstrates this by monitoring your tools, identifying what needs to be done, and completing tasks across email, calendar, and workflow systems.",
      },
      {
        question:
          "Is agentic AI safe to use for personal productivity?",
        answer:
          "Yes, when designed with proper guardrails. GAIA implements human-in-the-loop controls for sensitive actions, allowing you to review and approve decisions before execution while still benefiting from autonomous handling of routine tasks.",
      },
    ],
  },

  "proactive-ai": {
    slug: "proactive-ai",
    term: "Proactive AI",
    metaTitle:
      "Proactive vs Reactive AI: Why Proactive AI Matters",
    metaDescription:
      "Proactive AI anticipates your needs and acts before you ask, unlike reactive AI that waits for prompts. Learn how GAIA uses proactive AI to boost your productivity.",
    definition:
      "Proactive AI is an artificial intelligence system that anticipates user needs, monitors for relevant events, and takes autonomous action before being explicitly asked.",
    extendedDescription:
      "Most AI tools today are reactive: you type a prompt, and they respond. Proactive AI flips this dynamic. Instead of waiting for instructions, a proactive AI system continuously monitors your digital environment, identifies situations that require attention, and takes appropriate action. This could mean flagging an urgent email, preparing a meeting brief before your next call, or creating a task when a deadline is mentioned in a Slack message. The shift from reactive to proactive AI is fundamental to reducing cognitive load and truly augmenting human productivity.",
    keywords: [
      "proactive AI",
      "reactive AI",
      "proactive vs reactive AI",
      "anticipatory AI",
      "AI that acts first",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "Proactive behavior is GAIA's core design principle. GAIA continuously monitors your email inbox, calendar events, and notifications across 50+ connected tools. It surfaces urgent items, prepares meeting briefings, creates tasks from messages, and drafts replies without waiting for your prompt. You wake up to an organized inbox and a prepared agenda rather than a wall of unread notifications.",
    relatedTerms: [
      "ai-agent",
      "agentic-ai",
      "context-awareness",
      "cognitive-load",
    ],
    faqs: [
      {
        question:
          "What is the difference between proactive and reactive AI?",
        answer:
          "Reactive AI waits for your input and responds. Proactive AI monitors your environment and acts before you ask. ChatGPT is reactive because it responds to prompts. GAIA is proactive because it monitors your email, calendar, and tools and takes action autonomously.",
      },
      {
        question: "Can I control what a proactive AI does?",
        answer:
          "Yes. GAIA allows you to configure which actions it can take autonomously and which require your approval. You maintain full control while benefiting from proactive monitoring and suggestions.",
      },
    ],
  },

  "workflow-automation": {
    slug: "workflow-automation",
    term: "Workflow Automation",
    metaTitle:
      "What Is Workflow Automation? AI-Powered Workflows Explained",
    metaDescription:
      "Workflow automation uses technology to execute repeatable business processes automatically. Learn how GAIA combines AI with workflow automation for intelligent task management.",
    definition:
      "Workflow automation is the use of technology to execute repeatable business processes and tasks automatically, reducing manual effort and human error.",
    extendedDescription:
      "Traditional workflow automation follows rigid rules: if a condition is met, execute a predefined action. Tools like Zapier and n8n excel at this deterministic approach. AI-powered workflow automation adds intelligence to the process. Instead of requiring you to define every rule, an AI system can understand the context of your work, decide which actions to take, and adapt to new situations. This means workflows can handle ambiguity, make judgment calls, and improve over time. The combination of structured automation with AI reasoning creates workflows that are both reliable and intelligent.",
    keywords: [
      "workflow automation",
      "AI workflow automation",
      "business process automation",
      "automated workflows",
      "intelligent automation",
    ],
    category: "automation",
    howGaiaUsesIt:
      "GAIA offers AI-powered workflow automation that goes beyond rules-based triggers. You can describe a workflow in natural language, and GAIA builds and executes it across your connected tools. For example, you can say 'When I receive an email from a client about a deadline, create a task, block time on my calendar, and notify my team on Slack.' GAIA handles the entire chain intelligently, adapting to variations in how emails are phrased.",
    relatedTerms: [
      "task-automation",
      "ai-orchestration",
      "email-automation",
      "api-integration",
    ],
    faqs: [
      {
        question:
          "How is AI workflow automation different from traditional automation?",
        answer:
          "Traditional automation follows exact rules. AI workflow automation understands context and makes intelligent decisions. GAIA can read an email, determine its urgency, decide who to notify, and create appropriate tasks without you defining explicit rules for every scenario.",
      },
      {
        question:
          "Do I need coding skills to create workflows in GAIA?",
        answer:
          "No. GAIA lets you create workflows using natural language. Describe what you want to automate, and GAIA configures the workflow across your connected tools. No coding or visual workflow building is required.",
      },
    ],
  },

  "model-context-protocol": {
    slug: "model-context-protocol",
    term: "Model Context Protocol (MCP)",
    metaTitle:
      "What Is MCP? Model Context Protocol Explained",
    metaDescription:
      "Model Context Protocol (MCP) is an open standard for connecting AI models to external tools and data sources. Learn how GAIA uses MCP for 50+ integrations.",
    definition:
      "Model Context Protocol (MCP) is an open standard that enables AI models to securely connect with external tools, data sources, and services through a unified interface.",
    extendedDescription:
      "MCP solves a fundamental challenge in AI: connecting language models to the real world. Without MCP, every AI integration requires custom code for each tool. MCP provides a standardized protocol that allows AI agents to discover available tools, understand how to use them, and interact with them securely. Think of MCP as a universal adapter between AI models and external services. It defines how tools describe their capabilities, how agents send requests, and how responses are structured. This standardization makes it possible to build AI systems that work with many tools without custom integration code for each one.",
    keywords: [
      "Model Context Protocol",
      "MCP",
      "MCP AI",
      "AI tool integration",
      "AI integration standard",
      "MCP explained",
    ],
    category: "infrastructure",
    howGaiaUsesIt:
      "MCP is the backbone of GAIA's integration architecture. GAIA connects to 50+ tools including Gmail, Slack, Notion, GitHub, Linear, Todoist, and more through MCP servers. Each integration exposes its capabilities through the MCP standard, allowing GAIA's AI agents to discover and use tools dynamically. This means adding a new integration to GAIA does not require custom AI training. The agent simply discovers the new tool's capabilities through MCP and begins using it.",
    relatedTerms: [
      "api-integration",
      "ai-orchestration",
      "webhook",
      "oauth",
    ],
    faqs: [
      {
        question: "Why does GAIA use MCP instead of direct APIs?",
        answer:
          "MCP provides a standardized interface that allows GAIA's AI agents to discover and use tools without custom code for each integration. This makes it faster to add new integrations, easier to maintain existing ones, and allows the AI to understand tool capabilities dynamically.",
      },
      {
        question: "Can I add custom MCP integrations to GAIA?",
        answer:
          "Yes. GAIA supports custom MCP servers, allowing you to connect any tool or service that implements the MCP standard. You can also browse community-built integrations in the GAIA marketplace.",
      },
    ],
  },

  langgraph: {
    slug: "langgraph",
    term: "LangGraph",
    metaTitle:
      "What Is LangGraph? AI Agent Orchestration Framework",
    metaDescription:
      "LangGraph is a framework for building stateful, multi-agent AI applications with cycles, branching, and persistence. Learn how GAIA uses LangGraph for agent orchestration.",
    definition:
      "LangGraph is a framework for building stateful, multi-agent AI applications that supports complex workflows with cycles, branching, conditional logic, and persistent state management.",
    extendedDescription:
      "Built on top of LangChain, LangGraph models AI agent workflows as directed graphs. Each node in the graph represents an action or decision point, and edges define the flow between them. Unlike simple chain-based approaches, LangGraph supports cycles, allowing agents to iterate and refine their work. It also provides built-in state management, enabling agents to maintain context across multiple steps and sessions. This makes it ideal for building AI systems that need to handle complex, multi-step tasks with branching logic and error recovery.",
    keywords: [
      "LangGraph",
      "LangGraph framework",
      "AI agent framework",
      "agent orchestration",
      "LangChain graph",
      "stateful AI agents",
    ],
    category: "infrastructure",
    howGaiaUsesIt:
      "GAIA's entire agent system is built on LangGraph. The core agent operates as a graph with nodes for reasoning, tool selection, action execution, and response generation. Subagents for email, calendar, task management, and workflow execution are orchestrated through LangGraph's graph-based architecture. This allows GAIA to handle complex multi-step tasks like reading an email, creating a task, scheduling a follow-up meeting, and notifying a team member, all as a single coordinated workflow with state persistence.",
    relatedTerms: [
      "ai-agent",
      "ai-orchestration",
      "graph-based-memory",
      "llm",
    ],
    faqs: [
      {
        question: "Why does GAIA use LangGraph instead of simple chains?",
        answer:
          "LangGraph supports cycles, branching, and persistent state, which are essential for complex productivity workflows. Simple chains cannot handle the iterative reasoning and multi-tool orchestration that GAIA requires for tasks like managing email, scheduling, and cross-tool automation.",
      },
      {
        question:
          "Is LangGraph the same as LangChain?",
        answer:
          "LangGraph is built on top of LangChain but adds graph-based workflow orchestration with cycles, state management, and multi-agent coordination. LangChain provides the foundation for LLM interactions, while LangGraph adds the architecture for complex agent systems.",
      },
    ],
  },

  "graph-based-memory": {
    slug: "graph-based-memory",
    term: "Graph-Based Memory",
    metaTitle:
      "What Is Graph-Based AI Memory? Persistent Context for AI",
    metaDescription:
      "Graph-based memory allows AI systems to store and connect information as nodes and relationships, enabling persistent context. Learn how GAIA uses graph memory.",
    definition:
      "Graph-based memory is an AI memory architecture that stores information as interconnected nodes and relationships, enabling rich contextual understanding and persistent knowledge across interactions.",
    extendedDescription:
      "Traditional AI memory is either short-term, limited to a single conversation, or stored as flat key-value pairs. Graph-based memory organizes information as a network of entities and relationships. A person connects to their projects, which connect to tasks, which connect to meetings and documents. This structure allows an AI system to traverse relationships and build rich context. When you mention a project, the AI can instantly access related tasks, relevant emails, team members involved, and upcoming deadlines. Graph-based memory also enables temporal reasoning, understanding how relationships change over time.",
    keywords: [
      "graph-based memory",
      "AI memory",
      "knowledge graph memory",
      "persistent AI context",
      "AI memory architecture",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "GAIA maintains a graph-based memory system that connects all aspects of your digital life. When you discuss a project, GAIA accesses related emails, tasks, calendar events, documents, and team interactions stored as connected nodes. This means GAIA understands context deeply. It knows that the email from your client relates to the project deadline next week and the task you created yesterday. Over time, GAIA learns your patterns and preferences through this interconnected memory.",
    relatedTerms: [
      "knowledge-graph",
      "vector-embeddings",
      "context-awareness",
      "semantic-search",
    ],
    faqs: [
      {
        question:
          "How does graph-based memory differ from vector memory?",
        answer:
          "Vector memory stores information as numerical embeddings for similarity search. Graph-based memory stores information as connected entities and relationships. GAIA uses both: vector embeddings in ChromaDB for semantic search and graph structures for understanding relationships between your tasks, emails, meetings, and projects.",
      },
      {
        question:
          "Does GAIA's memory persist across sessions?",
        answer:
          "Yes. GAIA's graph-based memory is persistent. It remembers your projects, preferences, communication patterns, and work context across all interactions, building a deeper understanding of your workflow over time.",
      },
    ],
  },

  "vector-embeddings": {
    slug: "vector-embeddings",
    term: "Vector Embeddings",
    metaTitle:
      "What Are Vector Embeddings? AI Search and Similarity",
    metaDescription:
      "Vector embeddings convert text into numerical representations that capture meaning, enabling semantic search and similarity matching. Learn how GAIA uses embeddings.",
    definition:
      "Vector embeddings are numerical representations of text, images, or other data that capture semantic meaning, enabling machines to understand similarity and relationships between pieces of information.",
    extendedDescription:
      "When text is converted into a vector embedding, its meaning is encoded as a list of numbers, typically hundreds or thousands of dimensions. Similar concepts end up close together in this numerical space. The phrase 'schedule a meeting' would be close to 'book a call' but far from 'buy groceries.' This property makes vector embeddings essential for semantic search, where you find information by meaning rather than exact keyword matches. Vector databases store these embeddings and enable fast similarity searches across millions of data points.",
    keywords: [
      "vector embeddings",
      "embeddings AI",
      "semantic embeddings",
      "vector database",
      "embedding model",
      "vector search",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "GAIA uses ChromaDB as its vector database to store embeddings of your emails, tasks, notes, and documents. When you ask GAIA to find information or when the agent needs context for a task, it performs semantic search across your embedded data. This means you can ask 'find that email about the Q3 budget review' and GAIA will find it even if the email subject line says 'Financial Planning Discussion.' The semantic understanding goes beyond keyword matching.",
    relatedTerms: [
      "semantic-search",
      "graph-based-memory",
      "knowledge-graph",
      "llm",
    ],
    faqs: [
      {
        question: "Why are vector embeddings important for AI?",
        answer:
          "Vector embeddings allow AI to understand meaning rather than just matching keywords. GAIA uses embeddings to search your emails, tasks, and documents by meaning, so you can find information even when you do not remember exact words.",
      },
      {
        question: "What is a vector database?",
        answer:
          "A vector database stores and indexes vector embeddings for fast similarity search. GAIA uses ChromaDB as its vector database, enabling semantic search across all your connected data sources.",
      },
    ],
  },

  "task-automation": {
    slug: "task-automation",
    term: "Task Automation",
    metaTitle:
      "AI Task Automation: Automate Repetitive Work with AI",
    metaDescription:
      "AI task automation uses artificial intelligence to handle repetitive tasks automatically. Learn how GAIA automates task creation, management, and execution.",
    definition:
      "Task automation is the use of technology, particularly AI, to automatically create, manage, prioritize, and execute repetitive tasks that would otherwise require manual effort.",
    extendedDescription:
      "Task automation has evolved from simple reminders and rules-based triggers to intelligent systems that understand context. Modern AI task automation can identify when a task needs to be created from an email or message, determine its priority based on deadlines and importance, assign it to the right project or category, set appropriate due dates, and even execute the task itself. The goal is to reduce the cognitive overhead of managing a task list and ensure nothing falls through the cracks.",
    keywords: [
      "task automation",
      "AI task management",
      "automated task creation",
      "intelligent task manager",
      "AI productivity",
    ],
    category: "automation",
    howGaiaUsesIt:
      "GAIA automates the entire task lifecycle. It creates tasks from emails, Slack messages, and calendar events automatically. It prioritizes tasks based on deadlines, sender importance, and project context. It can execute tasks autonomously, such as drafting a response, scheduling a meeting, or updating a project status. GAIA integrates with task management tools like Todoist, Asana, Linear, and ClickUp, keeping everything synchronized across platforms.",
    relatedTerms: [
      "workflow-automation",
      "email-automation",
      "calendar-automation",
      "cognitive-load",
    ],
    faqs: [
      {
        question:
          "Can GAIA create tasks from emails automatically?",
        answer:
          "Yes. GAIA reads your emails, identifies action items, and creates tasks with appropriate titles, descriptions, deadlines, and project assignments. It synchronizes these tasks across your connected tools like Todoist, Asana, or Linear.",
      },
      {
        question:
          "How does AI task automation differ from a simple to-do app?",
        answer:
          "A to-do app requires you to manually create, organize, and complete tasks. AI task automation with GAIA identifies tasks from your communications, prioritizes them intelligently, and can even execute simple tasks autonomously.",
      },
    ],
  },

  "email-automation": {
    slug: "email-automation",
    term: "Email Automation",
    metaTitle:
      "AI Email Automation: Intelligent Inbox Management",
    metaDescription:
      "AI email automation uses intelligent systems to triage, categorize, draft replies, and manage your inbox. Learn how GAIA handles email management proactively.",
    definition:
      "Email automation uses AI to intelligently manage your inbox by triaging messages, categorizing them, drafting contextual replies, extracting action items, and reducing the time spent on email.",
    extendedDescription:
      "The average professional spends over two hours daily on email. AI email automation addresses this by handling the mechanical aspects of email management. An AI system can read incoming messages and understand their content, categorize them by urgency and topic, draft appropriate replies that match your communication style, extract action items and create tasks, schedule follow-ups, and archive or label messages. The key difference from traditional email filters is intelligence: AI understands the content and context of messages, not just sender addresses or keywords.",
    keywords: [
      "email automation",
      "AI email management",
      "inbox automation",
      "email triage AI",
      "smart inbox",
      "AI email assistant",
    ],
    category: "automation",
    howGaiaUsesIt:
      "GAIA connects to your Gmail inbox and proactively manages your email. It reads incoming messages, understands their content and urgency, and takes appropriate actions. GAIA can triage your inbox by priority, draft contextual replies that match your writing style, create tasks from action items mentioned in emails, schedule follow-ups on your calendar, and label or archive messages. You start your day with an organized inbox and drafted replies ready for review.",
    relatedTerms: [
      "task-automation",
      "proactive-ai",
      "workflow-automation",
      "context-awareness",
    ],
    faqs: [
      {
        question:
          "Can GAIA draft email replies for me?",
        answer:
          "Yes. GAIA reads incoming emails, understands the context, and drafts appropriate replies. You can review and send them with a click or configure GAIA to send routine replies automatically.",
      },
      {
        question:
          "Does GAIA work with Gmail and Outlook?",
        answer:
          "GAIA currently integrates deeply with Gmail through its MCP integration. It reads, triages, drafts, and manages your entire inbox proactively.",
      },
    ],
  },

  "calendar-automation": {
    slug: "calendar-automation",
    term: "Calendar Automation",
    metaTitle:
      "AI Calendar Management: Smart Scheduling and Automation",
    metaDescription:
      "AI calendar automation intelligently manages your schedule by finding optimal meeting times, preparing briefings, and coordinating across tools. Learn how GAIA automates calendars.",
    definition:
      "Calendar automation uses AI to intelligently manage your schedule by finding optimal meeting times, preparing briefings, blocking focus time, and coordinating calendar events with your tasks and communications.",
    extendedDescription:
      "Managing a calendar involves more than just booking meetings. It requires understanding priorities, protecting focus time, preparing for upcoming events, and coordinating with others. AI calendar automation handles these tasks by analyzing your schedule for conflicts and opportunities, finding optimal times for meetings based on preferences and energy levels, preparing briefing documents before meetings, blocking focus time for deep work, and syncing calendar events with tasks and project deadlines. The result is a calendar that works for you rather than against you.",
    keywords: [
      "calendar automation",
      "AI calendar management",
      "smart scheduling",
      "AI scheduling assistant",
      "calendar AI",
    ],
    category: "automation",
    howGaiaUsesIt:
      "GAIA integrates with Google Calendar to provide intelligent schedule management. It finds optimal meeting times, prepares briefing documents before your calls by gathering relevant emails and documents, blocks focus time based on your productivity patterns, creates calendar events from email conversations, and ensures your schedule aligns with your task priorities. GAIA treats your calendar as part of your complete workflow, not an isolated tool.",
    relatedTerms: [
      "task-automation",
      "email-automation",
      "workflow-automation",
      "proactive-ai",
    ],
    faqs: [
      {
        question:
          "Can GAIA schedule meetings automatically?",
        answer:
          "Yes. GAIA can find optimal meeting times, check availability, and create calendar events. It can also prepare briefing documents before meetings by gathering relevant context from your emails and tasks.",
      },
      {
        question:
          "Does GAIA protect my focus time?",
        answer:
          "GAIA can block focus time on your calendar based on your productivity patterns and task priorities, ensuring you have uninterrupted time for deep work alongside scheduled meetings.",
      },
    ],
  },

  "knowledge-graph": {
    slug: "knowledge-graph",
    term: "Knowledge Graph",
    metaTitle:
      "What Is a Knowledge Graph? Structured Data for AI",
    metaDescription:
      "A knowledge graph organizes information as entities and relationships, enabling AI to understand connections between data. Learn how GAIA uses knowledge graphs.",
    definition:
      "A knowledge graph is a structured representation of information that organizes data as entities, their attributes, and the relationships between them, enabling machines to understand and reason about connected information.",
    extendedDescription:
      "Knowledge graphs transform isolated pieces of information into a connected network. Instead of storing data in separate tables or documents, a knowledge graph represents facts as triples: subject, predicate, object. For example, 'Alice manages Project X,' 'Project X has deadline March 15,' and 'Alice emailed Bob about Project X.' These triples form a web of interconnected facts that AI systems can traverse to answer complex questions, discover hidden patterns, and understand context. Google, Amazon, and LinkedIn all use knowledge graphs to power their services.",
    keywords: [
      "knowledge graph",
      "knowledge graph AI",
      "entity relationship graph",
      "structured knowledge",
      "graph database AI",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "GAIA builds a personal knowledge graph from your connected tools. It links people to projects, projects to tasks, tasks to emails, emails to calendar events, and so on. This interconnected structure allows GAIA to answer questions like 'What is the status of Project X?' by traversing relationships to find related tasks, recent emails, upcoming meetings, and team members involved, providing a comprehensive answer rather than isolated data points.",
    relatedTerms: [
      "graph-based-memory",
      "semantic-search",
      "vector-embeddings",
      "context-awareness",
    ],
    faqs: [
      {
        question:
          "How does a knowledge graph differ from a database?",
        answer:
          "A traditional database stores data in tables with fixed schemas. A knowledge graph stores data as flexible entities and relationships, making it easy to connect information across different domains. GAIA uses this to link your emails, tasks, calendar events, and documents into a coherent understanding of your work.",
      },
      {
        question:
          "Is my data safe in GAIA's knowledge graph?",
        answer:
          "Yes. GAIA is open source and self-hostable, meaning you can run it on your own infrastructure with complete data control. Your knowledge graph is private to you and never used for training AI models.",
      },
    ],
  },

  "semantic-search": {
    slug: "semantic-search",
    term: "Semantic Search",
    metaTitle:
      "What Is Semantic Search? Search by Meaning, Not Keywords",
    metaDescription:
      "Semantic search finds information based on meaning and intent rather than exact keywords. Learn how GAIA uses semantic search to find your emails, tasks, and documents.",
    definition:
      "Semantic search is a search technique that understands the meaning and intent behind a query, returning results based on conceptual relevance rather than exact keyword matches.",
    extendedDescription:
      "Traditional keyword search matches the exact words in your query against documents. Semantic search goes deeper by understanding what you mean. When you search for 'meeting about budget,' semantic search can find a document titled 'Q3 Financial Planning Discussion' because it understands these concepts are related. This is powered by vector embeddings that capture the meaning of text as numerical representations. Semantic search is more forgiving of different phrasing, handles synonyms naturally, and can find relevant results even when the exact terms do not appear in the document.",
    keywords: [
      "semantic search",
      "AI search",
      "meaning-based search",
      "natural language search",
      "intelligent search",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "GAIA uses semantic search powered by ChromaDB vector embeddings to find information across all your connected tools. When you ask GAIA to find something, it searches by meaning rather than keywords. You can ask 'find the email where Sarah discussed the product launch timeline' and GAIA will find it even if the email subject was 'Re: Q2 Plans.' Semantic search works across emails, tasks, documents, and notes simultaneously.",
    relatedTerms: [
      "vector-embeddings",
      "knowledge-graph",
      "graph-based-memory",
      "context-awareness",
    ],
    faqs: [
      {
        question:
          "How is semantic search different from regular search?",
        answer:
          "Regular search matches exact keywords. Semantic search understands meaning. If you search for 'meeting notes from last week's design review,' GAIA's semantic search finds relevant documents even if they are titled differently, because it understands the conceptual relationship.",
      },
      {
        question:
          "What data sources does GAIA search across?",
        answer:
          "GAIA performs semantic search across all your connected tools: emails, tasks, calendar events, documents, Slack messages, and more. It provides a unified search across your entire digital workspace.",
      },
    ],
  },

  llm: {
    slug: "llm",
    term: "Large Language Model (LLM)",
    metaTitle:
      "What Is an LLM? Large Language Models Explained",
    metaDescription:
      "A Large Language Model is an AI trained on vast text data to understand and generate human language. Learn how GAIA uses LLMs to power its AI agent system.",
    definition:
      "A Large Language Model (LLM) is an artificial intelligence model trained on vast amounts of text data that can understand, generate, and reason about human language with remarkable fluency.",
    extendedDescription:
      "LLMs like GPT-4, Claude, and Gemini are neural networks with billions of parameters trained on diverse text from the internet, books, and other sources. They develop an understanding of language patterns, factual knowledge, and reasoning capabilities. LLMs can generate text, answer questions, summarize documents, write code, and engage in multi-step reasoning. In the context of AI agents, LLMs serve as the reasoning engine that decides what actions to take, how to interpret information, and how to communicate with users. They are the brain of modern AI systems.",
    keywords: [
      "large language model",
      "LLM",
      "LLM explained",
      "AI language model",
      "GPT",
      "foundation model",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "GAIA uses LLMs as the reasoning engine for its AI agents. The LLM reads your emails, understands their content, decides what actions to take, drafts replies in your communication style, and orchestrates multi-step workflows. GAIA supports multiple LLM providers, allowing you to choose the model that best fits your needs for cost, performance, and privacy. The LLM is combined with LangGraph for structured agent behavior and MCP for tool integration.",
    relatedTerms: [
      "ai-agent",
      "langgraph",
      "vector-embeddings",
      "ai-orchestration",
    ],
    faqs: [
      {
        question:
          "Which LLM does GAIA use?",
        answer:
          "GAIA supports multiple LLM providers. You can choose the model that best fits your needs. The LLM serves as the reasoning engine, while GAIA's agent architecture, built on LangGraph, handles the structured workflow orchestration.",
      },
      {
        question:
          "Is an LLM the same as an AI agent?",
        answer:
          "No. An LLM is a language model that understands and generates text. An AI agent uses an LLM as its reasoning engine combined with tools, memory, and planning capabilities to take actions in the real world. GAIA is an AI agent that uses LLMs for reasoning.",
      },
    ],
  },

  "ai-assistant": {
    slug: "ai-assistant",
    term: "AI Assistant",
    metaTitle:
      "AI Assistant vs Chatbot: What Is the Difference?",
    metaDescription:
      "An AI assistant uses artificial intelligence to help users complete tasks, going beyond simple chatbot responses. Learn how GAIA redefines the AI assistant category.",
    definition:
      "An AI assistant is a software system that uses artificial intelligence to help users accomplish tasks, manage information, and automate workflows, going beyond simple question-and-answer interactions.",
    extendedDescription:
      "The term AI assistant encompasses a wide range of systems, from simple voice assistants like Siri to sophisticated productivity platforms. What separates a true AI assistant from a chatbot is the ability to take action. A chatbot answers questions. An AI assistant manages your calendar, drafts your emails, organizes your tasks, and coordinates your workflows. The most advanced AI assistants combine conversational AI with tool integration, persistent memory, and proactive behavior to function as digital workers rather than just conversational partners.",
    keywords: [
      "AI assistant",
      "AI assistant vs chatbot",
      "personal AI assistant",
      "digital assistant",
      "intelligent assistant",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA is a personal AI assistant that redefines the category. Unlike conversational assistants that respond to prompts, GAIA proactively manages your email, calendar, tasks, and workflows across 50+ integrated tools. It acts as a digital chief of staff: triaging your inbox, preparing your schedule, creating and completing tasks, and orchestrating multi-step workflows. GAIA combines the conversational interface of a chatbot with the action capabilities of a full automation platform.",
    relatedTerms: [
      "digital-assistant",
      "ai-agent",
      "proactive-ai",
      "cognitive-load",
    ],
    faqs: [
      {
        question:
          "What makes GAIA different from Siri or Alexa?",
        answer:
          "Siri and Alexa handle simple commands like setting timers or playing music. GAIA manages complex productivity workflows: reading and triaging email, scheduling meetings with context, creating multi-step automated workflows, and proactively managing tasks across 50+ tools.",
      },
      {
        question:
          "Is an AI assistant better than a chatbot?",
        answer:
          "An AI assistant goes beyond conversation to take actions on your behalf. GAIA does not just answer questions about your schedule. It actively manages your calendar, creates tasks from emails, drafts replies, and automates workflows across your connected tools.",
      },
    ],
  },

  "self-hosting": {
    slug: "self-hosting",
    term: "Self-Hosting",
    metaTitle:
      "Self-Hosting AI: Complete Data Control and Privacy",
    metaDescription:
      "Self-hosting means running software on your own infrastructure for complete data control and privacy. Learn how to self-host GAIA for private AI assistance.",
    definition:
      "Self-hosting is the practice of running software on your own servers or infrastructure instead of using a cloud-hosted service, giving you complete control over your data, configuration, and availability.",
    extendedDescription:
      "Self-hosting has become increasingly important as concerns about data privacy, vendor lock-in, and data sovereignty grow. When you self-host software, your data never leaves your infrastructure. You control who has access, how data is stored, and where it is processed. For AI assistants that handle sensitive information like emails, calendar events, and business communications, self-hosting provides an additional layer of security. Self-hosting also means no subscription fees for the software itself, though you bear the infrastructure costs and maintenance responsibility.",
    keywords: [
      "self-hosting",
      "self-host AI",
      "data privacy AI",
      "on-premise AI",
      "private AI deployment",
      "self-hosted assistant",
    ],
    category: "infrastructure",
    howGaiaUsesIt:
      "GAIA is fully open source and designed for self-hosting. You can run the entire GAIA stack on your own infrastructure using Docker Compose. This includes the FastAPI backend, Next.js frontend, PostgreSQL, MongoDB, Redis, ChromaDB, and RabbitMQ. Self-hosting GAIA means your emails, tasks, calendar data, and AI conversations never leave your servers. It is completely free to self-host, with no feature limitations compared to the hosted version.",
    relatedTerms: [
      "open-source-ai",
      "oauth",
      "api-integration",
      "digital-assistant",
    ],
    faqs: [
      {
        question: "Is it hard to self-host GAIA?",
        answer:
          "No. GAIA provides Docker Compose configurations for easy deployment. You can have the entire stack running on your own server with a few commands. The infrastructure includes PostgreSQL, MongoDB, Redis, ChromaDB, and RabbitMQ, all containerized and preconfigured.",
      },
      {
        question:
          "What are the hardware requirements for self-hosting GAIA?",
        answer:
          "GAIA can run on a standard server or cloud instance. The main requirement is sufficient memory for the databases and the AI model inference. Detailed requirements are provided in the GAIA documentation.",
      },
    ],
  },

  "open-source-ai": {
    slug: "open-source-ai",
    term: "Open Source AI",
    metaTitle:
      "Open Source AI: Transparency, Control, and Community",
    metaDescription:
      "Open source AI provides transparency, community development, and data control. Learn why GAIA is built as open source and what it means for your privacy.",
    definition:
      "Open source AI refers to artificial intelligence software whose source code is publicly available, allowing anyone to inspect, modify, distribute, and contribute to the project.",
    extendedDescription:
      "Open source AI is important for several reasons. Transparency allows users to verify what the software does with their data. Community contribution accelerates development and bug fixing. Self-hosting capability gives users complete data control. Vendor independence prevents lock-in. And open inspection of AI behavior builds trust. In the AI assistant space, open source is particularly valuable because these systems handle sensitive personal and business data. Users should be able to verify that their emails, calendar events, and communications are handled securely.",
    keywords: [
      "open source AI",
      "open source AI assistant",
      "transparent AI",
      "community AI",
      "AI source code",
    ],
    category: "infrastructure",
    howGaiaUsesIt:
      "GAIA is fully open source, with the entire codebase available on GitHub. This includes the AI agents, backend API, web frontend, desktop app, mobile app, and all integrations. Anyone can inspect how GAIA processes data, contribute new features, build custom integrations, and self-host the platform. GAIA's open source nature means you never have to trust a black box with your personal data. The community actively contributes integrations, bug fixes, and feature improvements.",
    relatedTerms: [
      "self-hosting",
      "model-context-protocol",
      "api-integration",
      "digital-assistant",
    ],
    faqs: [
      {
        question:
          "Is GAIA really free and open source?",
        answer:
          "Yes. GAIA's entire codebase is available on GitHub. You can self-host it for free with no feature limitations. The hosted version offers convenience with managed infrastructure, but the self-hosted version has full functionality.",
      },
      {
        question:
          "Can I contribute to GAIA?",
        answer:
          "Absolutely. GAIA welcomes community contributions including new integrations, bug fixes, documentation, and feature development. You can also build and publish custom MCP integrations in the GAIA marketplace.",
      },
    ],
  },

  "cognitive-load": {
    slug: "cognitive-load",
    term: "Cognitive Load",
    metaTitle:
      "Cognitive Load Reduction: How AI Reduces Mental Overhead",
    metaDescription:
      "Cognitive load is the mental effort required to manage information and tasks. Learn how GAIA reduces cognitive load by proactively managing your digital workflow.",
    definition:
      "Cognitive load refers to the total amount of mental effort required to process information, make decisions, and manage tasks at any given time.",
    extendedDescription:
      "Every notification, email, task switch, and decision consumes cognitive resources. When cognitive load exceeds capacity, productivity drops, mistakes increase, and stress rises. Knowledge workers face particularly high cognitive load from managing multiple tools, context-switching between tasks, and keeping track of communications across platforms. Reducing cognitive load is not about working less but about offloading the mechanical overhead of information management so you can focus your mental energy on creative and strategic work that only humans can do.",
    keywords: [
      "cognitive load",
      "mental overhead",
      "cognitive load theory",
      "productivity psychology",
      "information overload",
      "decision fatigue",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA directly reduces cognitive load by handling the mechanical aspects of digital work. Instead of manually triaging your inbox, switching between apps to check tasks, and remembering follow-ups, GAIA handles these automatically. It organizes your email, prepares your daily agenda, creates tasks from messages, and reminds you of deadlines. By offloading information management to GAIA, you free your cognitive resources for the creative, strategic work that requires human judgment.",
    relatedTerms: [
      "proactive-ai",
      "task-automation",
      "email-automation",
      "ai-assistant",
    ],
    faqs: [
      {
        question:
          "How does GAIA reduce cognitive load?",
        answer:
          "GAIA reduces cognitive load by proactively managing your inbox, calendar, and tasks across 50+ tools. Instead of manually checking multiple apps, triaging emails, and tracking follow-ups, GAIA handles these automatically, freeing your mental energy for important work.",
      },
      {
        question:
          "What is the impact of high cognitive load on productivity?",
        answer:
          "High cognitive load leads to decision fatigue, increased errors, slower processing, and burnout. By automating information management and task orchestration, GAIA helps maintain manageable cognitive load throughout the day.",
      },
    ],
  },

  "context-awareness": {
    slug: "context-awareness",
    term: "Context Awareness",
    metaTitle:
      "Context-Aware AI: Understanding Your Work Environment",
    metaDescription:
      "Context-aware AI understands the full picture of your work: who is involved, what is urgent, and what happened before. Learn how GAIA uses context awareness.",
    definition:
      "Context awareness in AI is the ability to understand the full situation surrounding a task or interaction, including who is involved, what has happened before, related projects, deadlines, and the user's preferences and patterns.",
    extendedDescription:
      "Context is what separates a truly useful AI from a generic tool. A context-aware AI does not just process your current request in isolation. It understands that the email you received relates to a project discussed last week, involves a client who prefers brief responses, has a deadline connected to three other tasks, and should be prioritized because the sender is your most important stakeholder. Building context awareness requires persistent memory, relationship mapping, temporal understanding, and the ability to synthesize information from multiple sources.",
    keywords: [
      "context-aware AI",
      "contextual AI",
      "AI context understanding",
      "situational awareness AI",
      "contextual intelligence",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "GAIA builds context from every interaction and connected tool. When processing an email, GAIA considers the sender's history, related projects, upcoming deadlines, past conversations, and your communication preferences. This context enables GAIA to make intelligent decisions like prioritizing messages from key stakeholders, drafting replies in the appropriate tone, and creating tasks with the right urgency level. Context awareness is powered by GAIA's graph-based memory and vector embeddings.",
    relatedTerms: [
      "graph-based-memory",
      "knowledge-graph",
      "proactive-ai",
      "semantic-search",
    ],
    faqs: [
      {
        question:
          "How does GAIA build context about my work?",
        answer:
          "GAIA builds context by connecting information from all your integrated tools: emails, calendar events, tasks, Slack messages, documents, and more. It stores this information in a graph-based memory system that captures relationships between people, projects, and tasks.",
      },
      {
        question:
          "Does context awareness improve over time?",
        answer:
          "Yes. As GAIA processes more of your interactions and connected data, its understanding of your work patterns, preferences, and relationships deepens. The more you use GAIA, the more accurately it anticipates your needs.",
      },
    ],
  },

  oauth: {
    slug: "oauth",
    term: "OAuth",
    metaTitle:
      "What Is OAuth? Secure Authorization for AI Integrations",
    metaDescription:
      "OAuth is an authorization standard that lets AI tools securely access your accounts without sharing passwords. Learn how GAIA uses OAuth for secure integrations.",
    definition:
      "OAuth (Open Authorization) is an open standard for token-based authorization that allows third-party applications to access a user's resources without exposing their password.",
    extendedDescription:
      "OAuth is the security protocol behind the 'Sign in with Google' and 'Connect your Slack' buttons you see across the web. Instead of giving an application your password, OAuth provides a secure token with limited permissions. This token can be scoped to only allow specific actions, like reading your calendar but not deleting events. OAuth tokens can be revoked at any time, and they expire automatically. For AI assistants that need access to multiple tools, OAuth provides a secure way to connect without compromising your account security.",
    keywords: [
      "OAuth",
      "OAuth 2.0",
      "authorization protocol",
      "secure AI integration",
      "token-based auth",
      "API authorization",
    ],
    category: "integrations",
    howGaiaUsesIt:
      "GAIA uses OAuth 2.0 to securely connect to your tools. When you connect Gmail, Google Calendar, Slack, GitHub, or other services, you authorize GAIA through the service's official OAuth flow. GAIA receives scoped tokens with only the permissions it needs. You can revoke access at any time from either GAIA or the connected service. Your passwords are never shared with or stored by GAIA.",
    relatedTerms: [
      "api-integration",
      "webhook",
      "model-context-protocol",
      "self-hosting",
    ],
    faqs: [
      {
        question:
          "Is it safe to connect my accounts to GAIA via OAuth?",
        answer:
          "Yes. OAuth is an industry-standard protocol used by Google, Microsoft, Slack, and thousands of other services. GAIA never sees your passwords. It receives limited-permission tokens that you can revoke at any time.",
      },
      {
        question:
          "What permissions does GAIA request?",
        answer:
          "GAIA requests only the permissions necessary for its features. For example, it needs read and compose access for email management, read and write access for calendar management, and message access for Slack integration. Each permission is explicitly listed during the OAuth authorization flow.",
      },
    ],
  },

  webhook: {
    slug: "webhook",
    term: "Webhook",
    metaTitle:
      "What Is a Webhook? Real-Time Event Notifications Explained",
    metaDescription:
      "A webhook is a way for applications to send real-time notifications to other systems when events occur. Learn how GAIA uses webhooks for instant automation.",
    definition:
      "A webhook is an HTTP callback mechanism that allows one application to send real-time data to another application when a specific event occurs, enabling instant communication between systems.",
    extendedDescription:
      "Webhooks are the backbone of real-time integrations. Instead of an application repeatedly polling another service to check for updates, a webhook is triggered instantly when an event occurs. When someone sends you a Slack message, Slack sends a webhook to GAIA immediately. When a GitHub pull request is opened, GitHub notifies GAIA in real time. This push-based approach is more efficient than polling and enables near-instant response to events across your digital tools.",
    keywords: [
      "webhook",
      "webhooks explained",
      "HTTP callback",
      "event-driven architecture",
      "real-time notifications",
      "webhook automation",
    ],
    category: "integrations",
    howGaiaUsesIt:
      "GAIA uses webhooks to receive real-time notifications from your connected tools. When a new email arrives, a calendar event is created, a Slack message is sent, or a GitHub issue is opened, GAIA is notified instantly via webhooks. This enables GAIA's proactive behavior: it can respond to events in real time rather than checking for updates periodically. Webhooks power GAIA's workflow triggers, allowing automated actions to fire the moment a relevant event occurs.",
    relatedTerms: [
      "api-integration",
      "oauth",
      "workflow-automation",
      "model-context-protocol",
    ],
    faqs: [
      {
        question:
          "How do webhooks enable real-time automation?",
        answer:
          "Webhooks send instant notifications when events occur. When someone emails you or mentions you in Slack, GAIA receives a webhook immediately and can take action in real time, like creating a task or drafting a reply, without waiting for a scheduled check.",
      },
      {
        question:
          "Do I need to configure webhooks manually?",
        answer:
          "No. When you connect a tool to GAIA through OAuth or MCP, webhooks are configured automatically. GAIA handles the technical setup of receiving and processing webhook events from your connected services.",
      },
    ],
  },

  "api-integration": {
    slug: "api-integration",
    term: "API Integration",
    metaTitle:
      "API Integration for AI: Connecting Your Digital Tools",
    metaDescription:
      "API integration connects different software applications, enabling AI to act across your digital tools. Learn how GAIA integrates with 50+ tools through APIs and MCP.",
    definition:
      "API integration is the process of connecting different software applications through their Application Programming Interfaces, enabling them to share data and functionality seamlessly.",
    extendedDescription:
      "APIs are the standardized interfaces that allow software systems to communicate with each other. API integration connects these systems so data flows automatically between them. For an AI assistant, API integrations are what allow it to move beyond conversation into action. Through APIs, an AI assistant can read your emails, create calendar events, update project boards, send Slack messages, and manage files. The breadth and depth of API integrations directly determines how useful an AI assistant can be in managing your actual workflow.",
    keywords: [
      "API integration",
      "API integration AI",
      "software integration",
      "tool integration",
      "connected tools",
      "integration platform",
    ],
    category: "integrations",
    howGaiaUsesIt:
      "GAIA connects to 50+ tools through API integrations managed via the Model Context Protocol. Each integration provides GAIA's AI agents with the ability to read data from and take actions in your tools. This includes Gmail, Google Calendar, Slack, Notion, GitHub, Linear, Todoist, Asana, ClickUp, Trello, and many more. The MCP standard means new integrations can be added without modifying GAIA's core agent logic. Community-built integrations are available in the GAIA marketplace.",
    relatedTerms: [
      "model-context-protocol",
      "oauth",
      "webhook",
      "ai-orchestration",
    ],
    faqs: [
      {
        question:
          "How many integrations does GAIA support?",
        answer:
          "GAIA supports 50+ integrations including Gmail, Google Calendar, Slack, Notion, GitHub, Linear, Todoist, Asana, ClickUp, Trello, and more. New integrations are regularly added by the team and community through the MCP standard.",
      },
      {
        question:
          "Can I build custom integrations for GAIA?",
        answer:
          "Yes. GAIA supports custom MCP server integrations, allowing you to connect any tool or service. You can also publish your integrations to the GAIA marketplace for others to use.",
      },
    ],
  },

  "ai-orchestration": {
    slug: "ai-orchestration",
    term: "AI Orchestration",
    metaTitle:
      "What Is AI Orchestration? Coordinating Multiple AI Agents",
    metaDescription:
      "AI orchestration coordinates multiple AI agents and tools to complete complex tasks. Learn how GAIA orchestrates agents across email, calendar, and 50+ tools.",
    definition:
      "AI orchestration is the coordination of multiple AI agents, models, and tools to work together in completing complex, multi-step tasks that no single component could handle alone.",
    extendedDescription:
      "Complex real-world tasks rarely involve a single action. Responding to a client email might require reading the message, checking project status, looking up relevant documents, scheduling a follow-up meeting, and drafting a reply. AI orchestration coordinates multiple specialized agents and tools to handle these multi-step workflows. An orchestration layer decides which agent or tool to invoke at each step, manages the state and context as information flows between steps, handles errors and retries, and ensures the final outcome meets the user's intent.",
    keywords: [
      "AI orchestration",
      "agent orchestration",
      "multi-agent AI",
      "AI coordination",
      "workflow orchestration",
    ],
    category: "ai-concepts",
    howGaiaUsesIt:
      "GAIA's architecture is built around AI orchestration using LangGraph. A core agent receives requests and orchestrates specialized subagents for email, calendar, task management, workflow execution, and tool interaction. When you ask GAIA to 'prepare for my meeting with Sarah tomorrow,' the orchestration layer coordinates checking your calendar for the meeting, searching emails for recent conversations with Sarah, reviewing related tasks and project status, compiling a briefing document, and sending it to you before the meeting starts.",
    relatedTerms: [
      "langgraph",
      "ai-agent",
      "workflow-automation",
      "llm",
    ],
    faqs: [
      {
        question:
          "What is the difference between AI orchestration and automation?",
        answer:
          "Automation executes predefined rules. AI orchestration coordinates multiple intelligent agents that can reason, adapt, and make decisions. GAIA's orchestration layer dynamically decides which agents and tools to use based on the specific task and context.",
      },
      {
        question:
          "How does GAIA coordinate multiple agents?",
        answer:
          "GAIA uses LangGraph to model agent coordination as a directed graph. The core agent routes tasks to specialized subagents, manages shared state, handles tool interactions through MCP, and assembles results into coherent outcomes.",
      },
    ],
  },

  "human-in-the-loop": {
    slug: "human-in-the-loop",
    term: "Human-in-the-Loop",
    metaTitle:
      "Human-in-the-Loop AI: Balancing Automation with Control",
    metaDescription:
      "Human-in-the-loop keeps humans in control of AI decisions for sensitive actions. Learn how GAIA balances autonomous automation with human oversight.",
    definition:
      "Human-in-the-loop (HITL) is a design pattern where an AI system includes human oversight and approval at critical decision points, ensuring that sensitive or high-impact actions require human confirmation before execution.",
    extendedDescription:
      "While autonomous AI can handle routine tasks efficiently, some decisions are too important to leave entirely to an algorithm. Human-in-the-loop design recognizes this by building approval checkpoints into AI workflows. For a productivity assistant, this might mean auto-triaging low-priority emails but requesting approval before sending a reply to a client, automatically creating tasks but confirming before changing project deadlines, or suggesting calendar changes but waiting for confirmation before rescheduling a meeting. HITL provides the best of both worlds: automation for routine work and human judgment for important decisions.",
    keywords: [
      "human-in-the-loop",
      "HITL",
      "AI oversight",
      "human AI collaboration",
      "AI approval workflow",
      "responsible AI",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA implements human-in-the-loop controls that you can configure per action type. Routine tasks like email triage, task creation, and calendar event preparation can run autonomously. Sensitive actions like sending emails, modifying project deadlines, or executing financial workflows can be configured to require your approval before execution. This gives you the efficiency of automation with the safety of human oversight for actions that matter.",
    relatedTerms: [
      "agentic-ai",
      "proactive-ai",
      "ai-agent",
      "workflow-automation",
    ],
    faqs: [
      {
        question:
          "Can I control which actions GAIA takes automatically?",
        answer:
          "Yes. GAIA lets you configure approval requirements per action type. You can set routine tasks like inbox triage to run automatically while requiring approval for sensitive actions like sending emails on your behalf or modifying calendar events.",
      },
      {
        question:
          "Is human-in-the-loop important for AI assistants?",
        answer:
          "Yes. Human-in-the-loop ensures that AI assistants handle sensitive actions responsibly. GAIA balances autonomous efficiency for routine work with human oversight for high-impact decisions, giving you control without sacrificing productivity.",
      },
    ],
  },

  "digital-assistant": {
    slug: "digital-assistant",
    term: "Digital Assistant",
    metaTitle:
      "The Evolution of Digital Assistants: From Siri to AI Agents",
    metaDescription:
      "Digital assistants have evolved from simple voice commands to AI agents that manage your entire workflow. Learn how GAIA represents the next generation.",
    definition:
      "A digital assistant is a software-based agent that helps users perform tasks, access information, and manage their digital life through natural language interaction and increasingly autonomous action.",
    extendedDescription:
      "The digital assistant category has evolved through several generations. First-generation assistants like Siri and Alexa handled simple voice commands: set a timer, play music, check the weather. Second-generation assistants like Google Assistant added contextual understanding and smart home integration. Third-generation assistants powered by LLMs like ChatGPT and Claude brought sophisticated language understanding and reasoning. The emerging fourth generation combines LLM reasoning with autonomous action, persistent memory, and deep tool integration to function as genuine digital workers that manage your entire productivity workflow.",
    keywords: [
      "digital assistant",
      "virtual assistant",
      "AI assistant evolution",
      "personal digital assistant",
      "smart assistant",
      "next-gen assistant",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA represents the next generation of digital assistants. While Siri handles voice commands and ChatGPT handles conversations, GAIA manages your entire digital workflow. It connects to 50+ tools, builds persistent memory of your work, proactively handles email and calendar management, automates multi-step workflows, and learns your preferences over time. GAIA is available on web, desktop, mobile, and through Discord, Slack, and Telegram bots, meeting you wherever you work.",
    relatedTerms: [
      "ai-assistant",
      "ai-agent",
      "proactive-ai",
      "cognitive-load",
    ],
    faqs: [
      {
        question:
          "How is GAIA different from Siri or Google Assistant?",
        answer:
          "Siri and Google Assistant handle simple commands and questions. GAIA manages complex productivity workflows: email triage, calendar orchestration, multi-step task automation, and workflow execution across 50+ integrated tools. GAIA works proactively, not just when you ask.",
      },
      {
        question:
          "Is GAIA replacing traditional digital assistants?",
        answer:
          "GAIA complements traditional assistants by focusing on productivity workflow management. While Siri handles voice commands and smart home control, GAIA manages your email, calendar, tasks, and cross-tool workflows with AI-powered autonomy.",
      },
    ],
  },

  "ai-email-assistant": {
    slug: "ai-email-assistant",
    term: "AI Email Assistant",
    metaTitle:
      "What Is an AI Email Assistant? | GAIA",
    metaDescription:
      "An AI email assistant reads, triages, drafts, and manages your inbox autonomously. Learn how GAIA acts as your AI email assistant across Gmail and beyond.",
    definition:
      "An AI email assistant is software that uses artificial intelligence to read, categorize, prioritize, and respond to emails on your behalf, reducing the time and effort you spend managing your inbox.",
    extendedDescription:
      "The average knowledge worker receives over 120 emails per day. An AI email assistant tackles this by understanding the content and intent of each message, not just scanning for keywords. It can sort emails by urgency and topic, draft replies that match your tone and communication style, extract action items and deadlines, schedule follow-ups, and flag messages that need your personal attention. The best AI email assistants go beyond filtering. They understand relationships between senders, ongoing threads, and project context to make decisions a simple rule-based filter never could.",
    keywords: [
      "AI email assistant",
      "email AI",
      "smart email assistant",
      "AI inbox manager",
      "email productivity AI",
      "automated email replies",
    ],
    category: "automation",
    howGaiaUsesIt:
      "GAIA functions as a full AI email assistant for your Gmail inbox. It reads every incoming message, determines urgency based on sender history and content, categorizes emails by project and topic, drafts contextual replies in your writing style, and extracts action items into your task manager. GAIA works proactively: before you open your inbox in the morning, it has already triaged messages, prepared draft responses for your review, and created tasks from any deadlines or requests.",
    relatedTerms: [
      "email-automation",
      "inbox-zero",
      "proactive-ai",
      "context-awareness",
    ],
    faqs: [
      {
        question: "How does an AI email assistant differ from email filters?",
        answer:
          "Email filters match simple rules like sender address or subject keywords. An AI email assistant understands the content and context of each message. GAIA can determine that an email about 'Q3 deliverables' is urgent because it relates to a project with a deadline next week, something no filter rule can do.",
      },
      {
        question:
          "Can an AI email assistant write replies for me?",
        answer:
          "Yes. GAIA drafts contextual replies based on the email content, your past communication style, and relevant project context. You can review and send with one click, or configure GAIA to auto-send routine responses like meeting confirmations.",
      },
      {
        question:
          "Will an AI email assistant miss important emails?",
        answer:
          "GAIA is designed to catch what humans miss. It reads every message and evaluates urgency based on sender relationships, content analysis, and project context. It surfaces high-priority emails and flags anything that needs your direct attention.",
      },
    ],
  },

  "ai-calendar-management": {
    slug: "ai-calendar-management",
    term: "AI Calendar Management",
    metaTitle:
      "What Is AI Calendar Management? | GAIA",
    metaDescription:
      "AI calendar management uses intelligent automation to schedule meetings, protect focus time, and prepare briefings. See how GAIA manages your calendar.",
    definition:
      "AI calendar management is the use of artificial intelligence to schedule, organize, and optimize your calendar by finding ideal meeting times, protecting focus blocks, preparing meeting briefs, and coordinating events with your tasks and communications.",
    extendedDescription:
      "Calendar management is deceptively complex. It involves balancing meeting requests against focus time, preparing for upcoming events, avoiding back-to-back meetings that drain energy, aligning your schedule with task deadlines, and respecting time zone differences for remote teams. AI calendar management handles these trade-offs by learning your preferences, analyzing your energy patterns, and coordinating with your broader workflow. It moves beyond basic scheduling into genuine calendar intelligence: knowing when to protect your time and when a meeting is worth the interruption.",
    keywords: [
      "AI calendar management",
      "AI scheduling",
      "smart calendar",
      "calendar AI assistant",
      "intelligent scheduling",
      "automated calendar",
    ],
    category: "automation",
    howGaiaUsesIt:
      "GAIA connects to Google Calendar and manages your schedule as part of your complete workflow. It finds optimal meeting times by analyzing your availability and energy patterns, prepares briefing documents by pulling relevant emails and tasks before each meeting, blocks focus time for deep work based on your deadlines, and creates calendar events directly from email conversations. GAIA also alerts you to scheduling conflicts and suggests resolutions before they become problems.",
    relatedTerms: [
      "calendar-automation",
      "time-blocking",
      "ai-meeting-assistant",
      "deep-work",
    ],
    faqs: [
      {
        question:
          "How does AI calendar management differ from tools like Calendly?",
        answer:
          "Calendly shares your availability for others to book. AI calendar management with GAIA actively organizes your entire schedule: finding meeting times, protecting focus blocks, preparing briefings, creating events from emails, and ensuring your calendar aligns with your task priorities. It manages your calendar rather than just exposing it.",
      },
      {
        question:
          "Can GAIA schedule meetings across time zones?",
        answer:
          "Yes. GAIA considers time zones when scheduling and finds times that work for all participants. It factors in your preferred meeting hours and avoids scheduling calls at inconvenient times for any attendee.",
      },
    ],
  },

  "ai-task-prioritization": {
    slug: "ai-task-prioritization",
    term: "AI Task Prioritization",
    metaTitle:
      "What Is AI Task Prioritization? | GAIA",
    metaDescription:
      "AI task prioritization uses intelligence to rank your tasks by urgency, importance, and context. Learn how GAIA automatically prioritizes your work.",
    definition:
      "AI task prioritization is the use of artificial intelligence to automatically rank and order tasks based on deadlines, importance, dependencies, context, and your personal work patterns.",
    extendedDescription:
      "Deciding what to work on next is one of the biggest drains on productivity. Traditional prioritization frameworks like Eisenhower Matrix or MoSCoW require manual assessment of every task. AI task prioritization automates this by analyzing multiple signals: hard deadlines, sender importance, project dependencies, your historical work patterns, energy levels throughout the day, and the relative impact of each task. The result is a dynamically ordered task list that reflects reality rather than a static priority you assigned days ago when circumstances were different.",
    keywords: [
      "AI task prioritization",
      "task prioritization AI",
      "smart task ranking",
      "automated prioritization",
      "AI to-do list",
      "intelligent task management",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA prioritizes your tasks using signals from across your connected tools. It considers deadlines from calendar events, urgency cues from email content, project dependencies from tools like Linear or Asana, sender importance based on your communication history, and your own productivity patterns. When a new email creates a task or a deadline shifts, GAIA automatically re-ranks your task list. You always know what to work on next without spending time triaging your to-do list.",
    relatedTerms: [
      "task-automation",
      "cognitive-load",
      "ai-personal-productivity",
      "inbox-zero",
    ],
    faqs: [
      {
        question:
          "How does GAIA decide which tasks are most important?",
        answer:
          "GAIA analyzes multiple signals: hard deadlines, sender importance, project dependencies, email urgency cues, and your historical work patterns. It dynamically re-prioritizes as new information arrives rather than relying on a static priority you set once.",
      },
      {
        question:
          "Can I override GAIA's task prioritization?",
        answer:
          "Absolutely. GAIA's prioritization is a recommendation. You can pin tasks to the top, manually reorder items, or adjust the weight GAIA gives to different signals. Over time, GAIA learns from your overrides and adjusts its ranking model.",
      },
    ],
  },

  "workflow-orchestration": {
    slug: "workflow-orchestration",
    term: "Workflow Orchestration",
    metaTitle:
      "What Is Workflow Orchestration? | GAIA",
    metaDescription:
      "Workflow orchestration coordinates multi-step processes across tools and teams. Learn how GAIA orchestrates workflows across 50+ integrations with AI.",
    definition:
      "Workflow orchestration is the automated coordination of multiple tasks, tools, and processes into a structured sequence, managing dependencies, error handling, and data flow across each step.",
    extendedDescription:
      "While workflow automation handles individual tasks, workflow orchestration manages the coordination between them. An orchestrated workflow understands that step three depends on steps one and two completing successfully, that a failure in step four should trigger a specific recovery path, and that data produced in step two needs to be transformed before step five can use it. Orchestration adds reliability, observability, and error recovery to multi-step processes. In an AI context, orchestration also involves deciding which tools and agents to invoke at each step based on the current state of the workflow.",
    keywords: [
      "workflow orchestration",
      "process orchestration",
      "orchestration engine",
      "multi-step automation",
      "workflow coordination",
      "orchestration platform",
    ],
    category: "automation",
    howGaiaUsesIt:
      "GAIA orchestrates workflows across 50+ connected tools using LangGraph as its orchestration engine. When you create a workflow like 'When a client emails about a project update, check the project status in Linear, compile recent changes, draft a summary email, and schedule a follow-up meeting,' GAIA coordinates each step, passes data between them, handles failures gracefully, and ensures the entire chain completes reliably. Each step can involve different tools and different AI subagents, all managed by the orchestration layer.",
    relatedTerms: [
      "ai-orchestration",
      "workflow-automation",
      "langgraph",
      "no-code-automation",
    ],
    faqs: [
      {
        question:
          "What is the difference between workflow automation and workflow orchestration?",
        answer:
          "Workflow automation executes individual automated tasks. Workflow orchestration coordinates multiple automated tasks into a reliable sequence, managing dependencies, data flow, and error handling between steps. GAIA's orchestration ensures that multi-step workflows across different tools complete reliably.",
      },
      {
        question:
          "Can GAIA handle workflows that span multiple tools?",
        answer:
          "Yes. GAIA's orchestration engine coordinates actions across 50+ tools. A single workflow can read from Gmail, create tasks in Linear, update a Notion database, post in Slack, and schedule a meeting in Google Calendar, all as a coordinated sequence.",
      },
    ],
  },

  "ai-meeting-assistant": {
    slug: "ai-meeting-assistant",
    term: "AI Meeting Assistant",
    metaTitle:
      "What Is an AI Meeting Assistant? | GAIA",
    metaDescription:
      "An AI meeting assistant prepares agendas, gathers context, and handles follow-ups automatically. Learn how GAIA manages your meetings end to end.",
    definition:
      "An AI meeting assistant is software that uses artificial intelligence to prepare meeting briefs, gather relevant context, suggest agenda items, and automate post-meeting follow-ups like task creation and summary distribution.",
    extendedDescription:
      "Meetings consume a significant portion of the workweek, yet most people walk in unprepared and walk out without clear action items. An AI meeting assistant addresses both problems. Before a meeting, it gathers relevant emails, documents, and task updates related to the topic and attendees. It can suggest agenda items based on recent activity. After the meeting, it creates follow-up tasks, sends summaries to attendees, and schedules any agreed-upon next steps. The goal is to make every meeting productive by eliminating the preparation and follow-up overhead that most people skip due to time pressure.",
    keywords: [
      "AI meeting assistant",
      "meeting preparation AI",
      "meeting follow-up automation",
      "smart meeting notes",
      "AI meeting scheduler",
      "meeting productivity",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA manages the full meeting lifecycle. Before each meeting, it compiles a briefing with relevant emails, open tasks, and recent activity involving the attendees. It suggests talking points based on pending items and recent communications. After the meeting, you can tell GAIA the outcomes, and it creates tasks, schedules follow-ups, sends summary emails, and updates project status across your connected tools. GAIA turns meetings from time sinks into action-generating events.",
    relatedTerms: [
      "ai-calendar-management",
      "calendar-automation",
      "task-automation",
      "context-awareness",
    ],
    faqs: [
      {
        question:
          "How does GAIA prepare for my meetings?",
        answer:
          "GAIA pulls relevant context from your connected tools before each meeting. It gathers recent emails with attendees, open tasks related to the meeting topic, relevant documents, and previous meeting notes. This briefing arrives before the meeting starts so you walk in fully prepared.",
      },
      {
        question:
          "Can GAIA create tasks from meeting outcomes?",
        answer:
          "Yes. After a meeting, tell GAIA the action items and it creates tasks in your connected tools with appropriate assignees, deadlines, and project associations. It also schedules any follow-up meetings and sends summary emails to attendees.",
      },
      {
        question:
          "Does GAIA join and record meetings?",
        answer:
          "GAIA focuses on meeting preparation and follow-up rather than in-meeting recording. It excels at gathering context before meetings and turning outcomes into actions afterward, integrating with your calendar, email, and task management tools.",
      },
    ],
  },

  "smart-notifications": {
    slug: "smart-notifications",
    term: "Smart Notifications",
    metaTitle:
      "What Are Smart Notifications? | GAIA",
    metaDescription:
      "Smart notifications use AI to filter, prioritize, and batch alerts so only important items interrupt you. Learn how GAIA reduces notification overload.",
    definition:
      "Smart notifications are AI-filtered alerts that prioritize and batch notifications based on urgency, relevance, and your current context, replacing the constant stream of interruptions with timely, meaningful updates.",
    extendedDescription:
      "The average professional receives dozens of notifications per hour across email, Slack, project tools, and other apps. Most are low-priority, yet each one breaks focus and adds cognitive load. Smart notifications solve this by using AI to evaluate each alert against several factors: Is the sender important? Is the content urgent? Are you in a focus block? Can this wait until your next break? Instead of forwarding every alert, a smart notification system batches low-priority items, surfaces urgent ones immediately, and delivers the rest at optimal times. The result is fewer interruptions without missing anything critical.",
    keywords: [
      "smart notifications",
      "intelligent notifications",
      "AI notification filtering",
      "notification management",
      "alert prioritization",
      "notification fatigue",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA acts as an intelligent filter between your tools and your attention. Instead of letting every Slack message, email, and GitHub notification interrupt you, GAIA evaluates each one and decides how to handle it. Urgent messages from key contacts are surfaced immediately. Routine updates are batched into a digest delivered at times you choose. During focus blocks, GAIA holds non-critical notifications and presents them when your deep work session ends. You stay informed without being constantly interrupted.",
    relatedTerms: [
      "cognitive-load",
      "deep-work",
      "proactive-ai",
      "context-awareness",
    ],
    faqs: [
      {
        question:
          "How does GAIA decide which notifications are important?",
        answer:
          "GAIA evaluates notifications based on sender importance, content urgency, your current calendar status, and historical patterns. A message from your manager about a deadline gets through immediately. A newsletter or low-priority update gets batched for later.",
      },
      {
        question:
          "Can I customize how GAIA handles my notifications?",
        answer:
          "Yes. You can configure priority rules for specific contacts, channels, and tools. You can set focus hours when only critical notifications come through, and choose how often you receive batched digests for non-urgent items.",
      },
    ],
  },

  "ai-personal-productivity": {
    slug: "ai-personal-productivity",
    term: "AI Personal Productivity",
    metaTitle:
      "What Is AI Personal Productivity? | GAIA",
    metaDescription:
      "AI personal productivity uses artificial intelligence to manage your tasks, email, calendar, and workflows. Learn how GAIA boosts productivity with AI.",
    definition:
      "AI personal productivity refers to the use of artificial intelligence tools and systems to manage individual work output, including task management, email handling, calendar optimization, and workflow automation.",
    extendedDescription:
      "Personal productivity has traditionally relied on methodologies like Getting Things Done (GTD), time blocking, and the Pomodoro Technique. AI personal productivity takes these concepts further by automating the overhead that makes productivity systems hard to maintain. Instead of manually capturing tasks, organizing your inbox, and planning your day, AI handles the mechanical work. It captures tasks from your communications, organizes your inbox by priority, plans your day around deadlines and energy levels, and executes routine actions autonomously. The human focuses on creative and strategic work while AI manages the system.",
    keywords: [
      "AI personal productivity",
      "AI productivity tools",
      "personal productivity AI",
      "productivity automation",
      "AI for productivity",
      "AI work management",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA is an AI-first personal productivity platform. It manages your email inbox, organizes your calendar, prioritizes your tasks, and automates repetitive workflows across 50+ connected tools. Rather than requiring you to maintain a productivity system manually, GAIA runs the system for you. It captures action items from emails and messages, schedules your day around priorities, protects your focus time, and handles routine tasks autonomously. You get the benefits of rigorous productivity practices without the overhead of maintaining them.",
    relatedTerms: [
      "ai-task-prioritization",
      "inbox-zero",
      "deep-work",
      "time-blocking",
    ],
    faqs: [
      {
        question:
          "How does AI improve personal productivity?",
        answer:
          "AI improves personal productivity by automating the overhead of managing tasks, email, and calendars. GAIA captures tasks from your communications, prioritizes your work, schedules focus time, and handles routine actions. You spend less time organizing and more time on meaningful work.",
      },
      {
        question:
          "Does GAIA replace productivity apps like Todoist or Notion?",
        answer:
          "GAIA integrates with your existing productivity tools rather than replacing them. It connects to Todoist, Notion, Asana, Linear, and others, adding an AI layer that automates task creation, prioritization, and cross-tool coordination.",
      },
    ],
  },

  "inbox-zero": {
    slug: "inbox-zero",
    term: "Inbox Zero",
    metaTitle:
      "What Is Inbox Zero? Achieve It with AI | GAIA",
    metaDescription:
      "Inbox Zero is the practice of keeping your email inbox empty or near-empty. Learn how GAIA helps you reach and maintain Inbox Zero with AI automation.",
    definition:
      "Inbox Zero is an email management approach where the goal is to keep your inbox empty or near-empty at all times by processing every message through a system of actions: reply, delegate, defer, archive, or delete.",
    extendedDescription:
      "Coined by productivity expert Merlin Mann, Inbox Zero is not about having zero emails. It is about having zero unprocessed emails. Every message in your inbox should be acted on: replied to, turned into a task, delegated, scheduled for later, or archived. The challenge is that processing 50 to 100 emails daily is exhausting and time-consuming. Most people abandon Inbox Zero within weeks because the manual effort is unsustainable. AI changes this equation by automating the processing step. An AI system can triage, categorize, draft replies, extract tasks, and archive messages, making Inbox Zero achievable without the daily grind.",
    keywords: [
      "Inbox Zero",
      "inbox zero method",
      "email management",
      "empty inbox",
      "inbox zero AI",
      "email productivity",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA makes Inbox Zero sustainable by automating the processing step. It reads every incoming email, categorizes it by urgency and topic, drafts replies for your review, extracts action items into tasks, schedules follow-ups on your calendar, and archives processed messages. You start each day with a triaged inbox where every message has been processed. Instead of spending an hour clearing your inbox, you spend minutes reviewing GAIA's work and approving actions.",
    relatedTerms: [
      "ai-email-assistant",
      "email-automation",
      "cognitive-load",
      "ai-personal-productivity",
    ],
    faqs: [
      {
        question: "Is Inbox Zero realistic?",
        answer:
          "With manual effort alone, most people find Inbox Zero unsustainable. With AI assistance from GAIA, it becomes practical. GAIA processes every email automatically: triaging, drafting replies, creating tasks, and archiving. You review and approve rather than doing everything manually.",
      },
      {
        question:
          "How does GAIA help achieve Inbox Zero?",
        answer:
          "GAIA processes every incoming email by categorizing it, drafting a reply or flagging it for your attention, extracting action items into tasks, and archiving messages that need no response. This automated processing is what makes Inbox Zero achievable day after day.",
      },
      {
        question:
          "Does Inbox Zero mean I have to respond to every email?",
        answer:
          "No. Inbox Zero means every email is processed, not necessarily replied to. Some emails need replies, some become tasks, some get archived. GAIA handles this triage automatically, deciding the right action for each message based on its content and context.",
      },
    ],
  },

  "deep-work": {
    slug: "deep-work",
    term: "Deep Work",
    metaTitle:
      "What Is Deep Work? Protect Focus Time with AI | GAIA",
    metaDescription:
      "Deep work is focused, distraction-free concentration on cognitively demanding tasks. Learn how GAIA protects your deep work time with AI calendar management.",
    definition:
      "Deep work is a state of focused, uninterrupted concentration on cognitively demanding tasks that produces high-quality results, as defined by computer science professor Cal Newport.",
    extendedDescription:
      "Cal Newport's concept of deep work argues that the ability to focus without distraction is becoming both increasingly rare and increasingly valuable. Deep work produces your most meaningful output: writing, coding, strategic thinking, creative problem-solving. The enemy of deep work is the constant stream of emails, Slack messages, notifications, and meetings that fragment your attention. Research shows it takes an average of 23 minutes to regain full focus after an interruption. Protecting blocks of uninterrupted time for deep work is essential for producing your best work, yet modern digital tools make this harder than ever.",
    keywords: [
      "deep work",
      "deep focus",
      "Cal Newport deep work",
      "focused work",
      "distraction-free work",
      "concentration techniques",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA protects your deep work by managing the distractions that interrupt it. It blocks focus time on your calendar based on your deadlines and energy patterns, holds non-urgent notifications during focus blocks, batches emails and messages for review after your session ends, and prevents meeting scheduling during your deep work hours. When you enter a focus block, GAIA becomes your gatekeeper, ensuring only truly urgent items reach you while everything else waits until you are ready.",
    relatedTerms: [
      "time-blocking",
      "smart-notifications",
      "cognitive-load",
      "ai-calendar-management",
    ],
    faqs: [
      {
        question:
          "How does GAIA help me do more deep work?",
        answer:
          "GAIA automatically blocks focus time on your calendar, holds non-urgent notifications during those blocks, prevents meeting scheduling over your deep work hours, and batches low-priority communications for review afterward. It protects your concentration so you can do your best work.",
      },
      {
        question:
          "Can GAIA schedule deep work blocks automatically?",
        answer:
          "Yes. GAIA analyzes your calendar, deadlines, and energy patterns to find optimal times for deep work. It blocks these periods on your calendar and defends them from meeting requests, rescheduling only when something genuinely urgent arises.",
      },
    ],
  },

  "time-blocking": {
    slug: "time-blocking",
    term: "Time Blocking",
    metaTitle:
      "What Is Time Blocking? AI-Powered Scheduling | GAIA",
    metaDescription:
      "Time blocking assigns specific tasks to specific time slots on your calendar. Learn how GAIA automates time blocking with AI scheduling.",
    definition:
      "Time blocking is a scheduling method where you divide your day into dedicated blocks of time, each assigned to a specific task or type of work, turning your calendar into a concrete plan for the day.",
    extendedDescription:
      "Time blocking is used by executives, engineers, and creators to ensure important work gets scheduled rather than squeezed between meetings. Instead of a vague to-do list, each task gets a specific time slot on your calendar. This eliminates the decision of what to work on next and creates accountability for completing focused work. The challenge is that time blocking requires constant maintenance. Meetings shift, new priorities emerge, and tasks take longer than expected. Manually adjusting your time blocks throughout the day is tedious, which is why many people start time blocking but struggle to maintain it.",
    keywords: [
      "time blocking",
      "time blocking method",
      "calendar blocking",
      "time block scheduling",
      "time management technique",
      "schedule blocking",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA automates time blocking by analyzing your tasks, deadlines, and calendar availability to build a realistic daily schedule. It assigns your highest-priority tasks to time blocks that match your energy patterns, groups similar work together to reduce context switching, and dynamically adjusts blocks when meetings shift or new priorities arrive. Instead of spending 15 minutes each morning planning your day, GAIA presents a ready-made schedule that you can accept or adjust.",
    relatedTerms: [
      "deep-work",
      "ai-calendar-management",
      "ai-task-prioritization",
      "calendar-automation",
    ],
    faqs: [
      {
        question:
          "How does GAIA automate time blocking?",
        answer:
          "GAIA reads your task list, calendar, and deadlines, then creates time blocks for each task at optimal times. It considers your energy patterns, groups similar work to reduce context switching, and adjusts the schedule dynamically when things change.",
      },
      {
        question:
          "Does GAIA adjust time blocks when my schedule changes?",
        answer:
          "Yes. When a meeting moves, a task takes longer than expected, or a new priority arrives, GAIA reshuffles your remaining time blocks to accommodate the change. Your schedule stays realistic throughout the day.",
      },
    ],
  },

  "no-code-automation": {
    slug: "no-code-automation",
    term: "No-Code Automation",
    metaTitle:
      "What Is No-Code Automation? | GAIA",
    metaDescription:
      "No-code automation lets you build workflows without programming. Learn how GAIA uses natural language to create automations across 50+ tools.",
    definition:
      "No-code automation is the creation of automated workflows and processes using visual tools or natural language interfaces instead of writing code, making automation accessible to non-technical users.",
    extendedDescription:
      "Tools like Zapier, Make, and n8n popularized no-code automation with visual drag-and-drop workflow builders. These tools made automation accessible but still require understanding triggers, actions, data mapping, and logical conditions. The next evolution is natural language automation, where you describe what you want in plain words and AI builds the workflow. This removes even the visual builder learning curve, making automation truly accessible to anyone. Natural language automation also handles edge cases and variations that rigid no-code flows cannot, because the AI understands intent rather than following a fixed diagram.",
    keywords: [
      "no-code automation",
      "no-code workflow",
      "automation without coding",
      "natural language automation",
      "no-code AI",
      "visual workflow builder",
    ],
    category: "automation",
    howGaiaUsesIt:
      "GAIA takes no-code automation further by letting you create workflows with natural language. Instead of dragging and dropping blocks in a visual builder, you describe what you want: 'When a client emails me with a question, check our knowledge base, draft a reply with the answer, and log the question in our Notion tracker.' GAIA builds and runs the workflow across your connected tools. No technical knowledge, no visual builder, no code. Just describe the outcome and GAIA handles the implementation.",
    relatedTerms: [
      "workflow-automation",
      "workflow-orchestration",
      "ai-orchestration",
      "api-integration",
    ],
    faqs: [
      {
        question:
          "How is GAIA different from Zapier or Make?",
        answer:
          "Zapier and Make use visual builders where you connect triggers and actions with drag-and-drop. GAIA lets you describe workflows in natural language. You do not need to understand triggers, actions, or data mapping. GAIA's AI figures out the implementation from your description.",
      },
      {
        question:
          "Do I need any technical skills to create automations with GAIA?",
        answer:
          "No. GAIA accepts plain language descriptions of what you want automated. You describe the workflow in your own words and GAIA creates it across your connected tools. If the workflow needs adjustment, you describe the change conversationally.",
      },
      {
        question:
          "Can GAIA handle complex automations with conditions and branching?",
        answer:
          "Yes. GAIA's AI understands conditional logic expressed in natural language. You can say 'If the email is from a VIP client, respond within the hour and notify me on Slack. Otherwise, batch it in my daily digest.' GAIA creates the branching workflow automatically.",
      },
    ],
  },

  "digital-executive-assistant": {
    slug: "digital-executive-assistant",
    term: "Digital Executive Assistant",
    metaTitle:
      "What Is a Digital Executive Assistant? | GAIA",
    metaDescription:
      "A digital executive assistant is AI that handles executive-level tasks like inbox management, scheduling, and briefings. See how GAIA works as your AI EA.",
    definition:
      "A digital executive assistant is an AI-powered system that performs the functions of a human executive assistant: managing your inbox, scheduling meetings, preparing briefings, coordinating follow-ups, and handling administrative work.",
    extendedDescription:
      "Human executive assistants are invaluable because they understand context, anticipate needs, and manage the operational overhead that drains leadership time. They triage the inbox, prepare meeting materials, manage the calendar, coordinate with stakeholders, and ensure nothing falls through the cracks. A digital executive assistant replicates these functions with AI, offering 24/7 availability, instant processing speed, and the ability to work across dozens of digital tools simultaneously. The key requirement is the same as for a human EA: deep understanding of context, priorities, and the principal's working style.",
    keywords: [
      "digital executive assistant",
      "AI executive assistant",
      "virtual executive assistant",
      "AI EA",
      "AI chief of staff",
      "automated executive assistant",
    ],
    category: "productivity",
    howGaiaUsesIt:
      "GAIA functions as a digital executive assistant available around the clock. It triages your inbox and surfaces what matters, schedules and reschedules meetings while protecting your focus time, prepares briefings before every meeting with relevant context from email and tasks, creates follow-up actions after meetings, coordinates multi-step workflows across your tools, and learns your preferences and working style over time. GAIA gives every professional the kind of operational support that was previously reserved for C-suite executives with dedicated staff.",
    relatedTerms: [
      "ai-assistant",
      "digital-assistant",
      "ai-email-assistant",
      "ai-meeting-assistant",
    ],
    faqs: [
      {
        question:
          "Can GAIA really replace a human executive assistant?",
        answer:
          "GAIA handles the operational and administrative tasks that consume most of an EA's time: inbox management, scheduling, meeting prep, follow-ups, and task coordination. For relationship-heavy tasks that require human judgment and personal touch, human EAs remain valuable. Many users pair GAIA with their EA for the best of both.",
      },
      {
        question:
          "What executive tasks can GAIA handle?",
        answer:
          "GAIA manages inbox triage, calendar scheduling, meeting preparation and follow-up, task creation and prioritization, cross-tool workflow coordination, and stakeholder communication drafting. It works across 50+ integrated tools to handle the full scope of executive administrative support.",
      },
      {
        question:
          "Is a digital executive assistant only for executives?",
        answer:
          "No. Anyone who manages a busy inbox, attends multiple meetings, and coordinates across tools benefits from a digital EA. GAIA is designed for knowledge workers at every level who want to offload administrative overhead and focus on their most impactful work.",
      },
    ],
  },
};

export function getGlossaryTerm(
  slug: string,
): GlossaryTerm | undefined {
  return glossaryTerms[slug];
}

export function getAllGlossaryTermSlugs(): string[] {
  return Object.keys(glossaryTerms);
}

export function getAllGlossaryTerms(): GlossaryTerm[] {
  return Object.values(glossaryTerms);
}

export function getGlossaryTermsByCategory(
  category: string,
): GlossaryTerm[] {
  return Object.values(glossaryTerms).filter(
    (term) => term.category === category,
  );
}
