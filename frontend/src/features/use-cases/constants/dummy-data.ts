import type {
  ContentCreator,
  StepInfo,
  ToolInfo,
} from "@/types/shared/contentTypes";

// Re-export shared types with use-case specific names for backwards compatibility
export type UseCaseStep = StepInfo;
export type UseCaseTool = ToolInfo;
export type UseCaseCreator = ContentCreator;

export interface UseCase {
  title: string;
  description: string;
  action_type: "prompt" | "workflow";
  integrations: string[];
  categories: string[];
  published_id: string;
  prompt?: string;
  slug: string;
  tools?: UseCaseTool[];
  steps?: UseCaseStep[];
  creator?: UseCaseCreator;
  detailed_description?: string;
}

export const useCasesData: UseCase[] = [
  // Students
  {
    title: "Study Schedule Generator",
    description:
      "Automatically create personalized study schedules based on your courses, exams, and preferences",
    action_type: "workflow",
    integrations: ["calendar", "notion", "productivity"],
    categories: ["Students", "featured"],
    published_id: "study-schedule-workflow",
    slug: "study-schedule-generator",
    detailed_description:
      "Transform your study routine with an AI-powered schedule generator that analyzes your courses, exam dates, and learning preferences to create a personalized study plan that maximizes your productivity and learning outcomes.",
    tools: [
      {
        name: "Calendar",
        description: "Schedule management",
        category: "calendar",
      },
      {
        name: "Notion",
        description: "Note organization",
        category: "notion",
      },
      {
        name: "Productivity Tools",
        description: "Task management",
        category: "productivity",
      },
    ],
    steps: [
      {
        title: "Input your courses and exam dates",
        description:
          "Provide information about your current courses, deadlines, and assessment dates",
      },
      {
        title: "Set your preferences",
        description:
          "Specify your preferred study times, break intervals, and learning pace",
      },
      {
        title: "Generate schedule",
        description:
          "AI creates an optimized study schedule based on your inputs",
      },
      {
        title: "Sync with calendar",
        description: "Automatically add study blocks to your calendar app",
      },
    ],
  },
  {
    title: "Essay Writing Assistant",
    description:
      "Get structured help with essay planning, research guidance, and writing improvement",
    action_type: "prompt",
    integrations: ["search", "documents", "creative"],
    categories: ["Students"],
    published_id: "essay-writing-prompt",
    slug: "essay-writing-assistant",
    prompt:
      "You are an expert writing tutor. Help me structure and improve my essay on [TOPIC]. First, analyze the topic and suggest a clear thesis statement. Then, provide an outline with main points and supporting evidence. Finally, review my draft and suggest improvements for clarity, flow, and academic style.",
    detailed_description:
      "Elevate your academic writing with an AI writing assistant that helps you craft well-structured essays, provides research guidance, and offers constructive feedback to improve your writing style and argumentation.",
    tools: [
      {
        name: "Search",
        description: "Research and information gathering",
        category: "search",
      },
      {
        name: "Documents",
        description: "Document creation and editing",
        category: "documents",
      },
      {
        name: "Creative AI",
        description: "Writing assistance",
        category: "creative",
      },
    ],
    steps: [
      {
        title: "Provide your essay topic",
        description: "Share the topic or question you need to write about",
      },
      {
        title: "Receive thesis suggestions",
        description: "Get AI-generated thesis statements and approaches",
      },
      {
        title: "Build an outline",
        description: "Work with AI to structure your main points and evidence",
      },
      {
        title: "Get writing feedback",
        description: "Submit your draft for detailed improvement suggestions",
      },
    ],
  },
  {
    title: "Study Buddy Q&A",
    description:
      "Get help understanding complex concepts, practice problems, and exam preparation",
    action_type: "prompt",
    integrations: ["search", "memory", "creative"],
    categories: ["Students"],
    published_id: "study-buddy-prompt",
    slug: "study-buddy-qa",
    prompt:
      "You are a knowledgeable tutor in [SUBJECT]. Help me understand [CONCEPT/TOPIC]. Please: 1) Explain the concept in simple terms with real-world examples, 2) Break down complex ideas into digestible parts, 3) Provide practice questions to test my understanding, 4) Suggest study techniques and memory aids, 5) Connect this topic to related concepts I should know.",
    detailed_description:
      "Your personal AI tutor that helps you master complex subjects through clear explanations, real-world examples, and practice questions tailored to your learning style.",
    tools: [
      {
        name: "Search",
        description: "Information retrieval",
        category: "search",
      },
      {
        name: "Memory",
        description: "Context retention",
        category: "memory",
      },
      {
        name: "Creative AI",
        description: "Explanation generation",
        category: "creative",
      },
    ],
    steps: [
      {
        title: "Ask your question",
        description: "Submit the concept or topic you're struggling with",
      },
      {
        title: "Get clear explanations",
        description: "Receive simplified explanations with examples",
      },
      {
        title: "Practice with questions",
        description: "Test your understanding with custom practice problems",
      },
      {
        title: "Review study techniques",
        description: "Learn effective methods to retain the information",
      },
    ],
  },

  // Founders
  {
    title: "Pitch Deck Generator",
    description:
      "Create compelling investor pitch decks with market analysis, financial projections, and compelling narratives",
    action_type: "workflow",
    integrations: ["creative", "google_docs", "productivity"],
    categories: ["Founders", "featured"],
    published_id: "pitch-deck-workflow",
    slug: "pitch-deck-generator",
    detailed_description:
      "Generate investor-ready pitch decks that tell your startup's story effectively. Includes market analysis, competitive landscape, business model, financial projections, and a compelling narrative that resonates with investors.",
    tools: [
      {
        name: "Creative AI",
        description: "Content generation",
        category: "creative",
      },
      {
        name: "Google Docs",
        description: "Document creation",
        category: "google_docs",
      },
      {
        name: "Productivity Tools",
        description: "Project management",
        category: "productivity",
      },
    ],
    steps: [
      {
        title: "Input startup information",
        description: "Provide details about your startup, market, and vision",
      },
      {
        title: "Generate market analysis",
        description: "AI researches and creates market opportunity slides",
      },
      {
        title: "Create financial projections",
        description: "Build realistic financial forecasts and metrics",
      },
      {
        title: "Finalize presentation",
        description: "Review and export your complete pitch deck",
      },
    ],
  },
  {
    title: "Startup Idea Validator",
    description:
      "Validate your startup idea with market research, feasibility analysis, and competitive assessment",
    action_type: "prompt",
    integrations: ["search", "memory", "documents"],
    categories: ["Founders"],
    published_id: "startup-validator-prompt",
    slug: "startup-idea-validator",
    prompt:
      "You are a startup advisor and venture capitalist. Help me validate my startup idea: [STARTUP IDEA]. Please analyze: 1) Market opportunity and target customer needs, 2) Competitive landscape and differentiation, 3) Business model viability and revenue potential, 4) Technical feasibility and resource requirements, 5) Key risks and mitigation strategies. Provide honest feedback and actionable next steps.",
    detailed_description:
      "Get expert validation for your startup idea through comprehensive market analysis, competitive assessment, and business model evaluation. This AI-powered advisor provides honest, data-driven feedback to help you make informed decisions about pursuing your venture.",
    tools: [
      {
        name: "Search",
        description: "Market research and competitor analysis",
        category: "search",
      },
      {
        name: "Memory",
        description: "Context retention across conversations",
        category: "memory",
      },
      {
        name: "Documents",
        description: "Report generation",
        category: "documents",
      },
    ],
    steps: [
      {
        title: "Describe your startup idea",
        description:
          "Provide details about your product, target market, and unique value proposition",
      },
      {
        title: "Receive market analysis",
        description:
          "Get insights on market size, customer needs, and growth potential",
      },
      {
        title: "Review competitive assessment",
        description:
          "Understand your competition and identify differentiation opportunities",
      },
      {
        title: "Evaluate feasibility",
        description:
          "Assess business model viability, technical requirements, and risks",
      },
      {
        title: "Get actionable recommendations",
        description:
          "Receive next steps and strategic advice for moving forward",
      },
    ],
  },
  {
    title: "Market Research Analyzer",
    description:
      "Analyze market opportunities, competitor landscape, and validate your business idea",
    action_type: "prompt",
    integrations: ["search", "memory", "documents"],
    categories: ["Founders"],
    published_id: "market-research-prompt",
    slug: "market-research-analyzer",
    prompt:
      "Act as a senior business analyst. I'm developing [BUSINESS IDEA] targeting [TARGET MARKET]. Please provide: 1) Market size analysis and growth potential, 2) Key competitors and their positioning, 3) Unique value proposition opportunities, 4) Potential challenges and risks, 5) Go-to-market strategy recommendations. Use data-driven insights and industry best practices.",
    detailed_description:
      "Conduct comprehensive market research with AI-powered analysis of market opportunities, competitive dynamics, and strategic positioning. Get data-driven insights to make informed business decisions and develop effective go-to-market strategies.",
    tools: [
      {
        name: "Search",
        description: "Market data and competitor research",
        category: "search",
      },
      {
        name: "Memory",
        description: "Context retention for analysis",
        category: "memory",
      },
      {
        name: "Documents",
        description: "Research report generation",
        category: "documents",
      },
    ],
    steps: [
      {
        title: "Define your market",
        description: "Specify your business idea and target market segments",
      },
      {
        title: "Analyze market size",
        description:
          "Receive detailed analysis of market opportunity and growth trends",
      },
      {
        title: "Review competitor landscape",
        description:
          "Get insights on key competitors and their market positioning",
      },
      {
        title: "Identify opportunities",
        description:
          "Discover unique value proposition and differentiation strategies",
      },
      {
        title: "Plan go-to-market strategy",
        description:
          "Receive recommendations for entering and capturing the market",
      },
    ],
  },

  // Engineering
  {
    title: "Code Review Automation",
    description:
      "Automatically review code commits, check for best practices, and suggest improvements",
    action_type: "workflow",
    integrations: ["development", "productivity", "mail"],
    categories: ["Engineering"],
    published_id: "code-review-workflow",
    slug: "code-review-automation",
    detailed_description:
      "Streamline your code review process with automated analysis that checks for coding standards, security vulnerabilities, performance issues, and best practices. Get instant feedback and actionable suggestions to improve code quality before merging.",
    tools: [
      {
        name: "Development Tools",
        description: "Code analysis and review",
        category: "development",
      },
      {
        name: "Productivity",
        description: "Task management and tracking",
        category: "productivity",
      },
      {
        name: "Gmail",
        description: "Notification delivery",
        category: "gmail",
      },
    ],
    steps: [
      {
        title: "Connect repository",
        description:
          "Link your code repository and configure review preferences",
      },
      {
        title: "Analyze code changes",
        description:
          "AI automatically reviews commits for issues and improvements",
      },
      {
        title: "Receive review comments",
        description:
          "Get detailed feedback on code quality, security, and best practices",
      },
      {
        title: "Notify team members",
        description:
          "Automatically send review summaries to relevant stakeholders",
      },
    ],
  },
  {
    title: "Debug Helper Assistant",
    description:
      "Get help debugging code issues, understanding error messages, and finding solutions",
    action_type: "prompt",
    integrations: ["development", "search", "memory"],
    categories: ["Engineering"],
    published_id: "debug-helper-prompt",
    slug: "debug-helper-assistant",
    prompt:
      "You are a senior software engineer debugging expert. I'm facing this issue: [ERROR/PROBLEM DESCRIPTION]. Here's my code: [CODE]. Please help me: 1) Identify the root cause of the issue, 2) Explain why this error occurs, 3) Provide step-by-step debugging approach, 4) Suggest specific fixes with code examples, 5) Recommend best practices to prevent similar issues. Be thorough and educational.",
    detailed_description:
      "Your AI debugging companion that helps you quickly identify and fix code issues. Get expert analysis of error messages, step-by-step debugging guidance, and proven solutions with detailed explanations to help you learn and prevent future problems.",
    tools: [
      {
        name: "Development Tools",
        description: "Code analysis and debugging",
        category: "development",
      },
      {
        name: "Search",
        description: "Solution lookup and documentation",
        category: "search",
      },
      {
        name: "Memory",
        description: "Context tracking across debugging sessions",
        category: "memory",
      },
    ],
    steps: [
      {
        title: "Describe the problem",
        description:
          "Share your error message, symptoms, and relevant code snippets",
      },
      {
        title: "Get root cause analysis",
        description:
          "Receive detailed explanation of why the error is occurring",
      },
      {
        title: "Follow debugging steps",
        description:
          "Work through systematic debugging approach to isolate the issue",
      },
      {
        title: "Implement fixes",
        description: "Apply suggested code changes with detailed examples",
      },
      {
        title: "Learn prevention strategies",
        description:
          "Understand best practices to avoid similar issues in the future",
      },
    ],
  },
  {
    title: "Architecture Design Helper",
    description:
      "Get expert guidance on system architecture, design patterns, and technical decisions",
    action_type: "prompt",
    integrations: ["development", "memory", "creative"],
    categories: ["Engineering"],
    published_id: "architecture-design-prompt",
    slug: "architecture-design-helper",
    prompt:
      "You are a senior software architect. I'm building [SYSTEM DESCRIPTION] with requirements: [REQUIREMENTS]. Please provide: 1) Recommended system architecture with key components, 2) Suitable design patterns and why, 3) Technology stack recommendations, 4) Scalability considerations, 5) Potential bottlenecks and mitigation strategies. Focus on maintainability, performance, and best practices.",
    detailed_description:
      "Design robust and scalable system architectures with AI-powered guidance on design patterns, technology choices, and best practices. Get expert recommendations tailored to your specific requirements, ensuring maintainability, performance, and future growth.",
    tools: [
      {
        name: "Development Tools",
        description: "Architecture design and planning",
        category: "development",
      },
      {
        name: "Memory",
        description: "Requirements and context tracking",
        category: "memory",
      },
      {
        name: "Creative AI",
        description: "Diagram and documentation generation",
        category: "creative",
      },
    ],
    steps: [
      {
        title: "Define system requirements",
        description:
          "Specify your system goals, constraints, and key requirements",
      },
      {
        title: "Review architecture proposal",
        description:
          "Get recommended system architecture with component breakdown",
      },
      {
        title: "Evaluate design patterns",
        description:
          "Understand suggested patterns and their benefits for your use case",
      },
      {
        title: "Select technology stack",
        description:
          "Receive recommendations for frameworks, databases, and tools",
      },
      {
        title: "Plan for scalability",
        description:
          "Get guidance on growth considerations and potential bottlenecks",
      },
    ],
  },

  // Marketing
  {
    title: "Social Media Campaign Creator",
    description:
      "Generate comprehensive social media campaigns with content calendar and engagement strategies",
    action_type: "workflow",
    integrations: ["creative", "calendar", "productivity"],
    categories: ["Marketing", "featured"],
    published_id: "social-media-campaign-workflow",
    slug: "social-media-campaign-creator",
    detailed_description:
      "Create engaging social media campaigns with AI-generated content, strategic posting schedules, and data-driven engagement tactics. From content creation to calendar management, streamline your entire social media workflow for maximum impact and reach.",
    tools: [
      {
        name: "Creative AI",
        description: "Content and image generation",
        category: "creative",
      },
      {
        name: "Calendar",
        description: "Post scheduling and planning",
        category: "calendar",
      },
      {
        name: "Productivity Tools",
        description: "Campaign management",
        category: "productivity",
      },
    ],
    steps: [
      {
        title: "Define campaign goals",
        description:
          "Set objectives, target audience, and key messaging for your campaign",
      },
      {
        title: "Generate content",
        description:
          "AI creates posts, captions, and visuals aligned with your brand",
      },
      {
        title: "Build content calendar",
        description:
          "Organize posts across platforms with optimal timing and frequency",
      },
      {
        title: "Schedule and automate",
        description: "Set up automated posting and engagement tracking",
      },
      {
        title: "Monitor and optimize",
        description:
          "Track performance metrics and adjust strategy for better results",
      },
    ],
  },
  {
    title: "Brand Voice Generator",
    description:
      "Develop consistent brand voice, messaging guidelines, and content tone for your business",
    action_type: "prompt",
    integrations: ["creative", "memory", "documents"],
    categories: ["Marketing"],
    published_id: "brand-voice-prompt",
    slug: "brand-voice-generator",
    prompt:
      "You are a brand strategist and copywriter. Help me develop a distinctive brand voice for [BUSINESS/BRAND] targeting [TARGET AUDIENCE]. Please create: 1) Brand personality traits and characteristics, 2) Tone of voice guidelines (formal/casual, friendly/professional, etc.), 3) Key messaging pillars and value propositions, 4) Do's and don'ts for content creation, 5) Example content pieces showing the brand voice in action. Make it authentic and memorable.",
    detailed_description:
      "Establish a distinctive and consistent brand voice that resonates with your target audience. Develop comprehensive messaging guidelines, personality traits, and practical examples to ensure all your content reflects your brand's unique character and values.",
    tools: [
      {
        name: "Creative AI",
        description: "Brand voice development and examples",
        category: "creative",
      },
      {
        name: "Memory",
        description: "Brand context and preferences",
        category: "memory",
      },
      {
        name: "Documents",
        description: "Brand guidelines documentation",
        category: "documents",
      },
    ],
    steps: [
      {
        title: "Describe your brand",
        description:
          "Share information about your business, values, and target audience",
      },
      {
        title: "Define personality traits",
        description: "Receive brand personality characteristics and attributes",
      },
      {
        title: "Establish tone guidelines",
        description:
          "Get specific tone of voice recommendations for different contexts",
      },
      {
        title: "Review messaging pillars",
        description:
          "Understand key messages and value propositions to emphasize",
      },
      {
        title: "Get practical examples",
        description:
          "See sample content demonstrating your brand voice in action",
      },
    ],
  },
  {
    title: "Content Strategy Planner",
    description:
      "Develop content strategies, topics, and distribution plans for your target audience",
    action_type: "prompt",
    integrations: ["creative", "search", "memory"],
    categories: ["Marketing"],
    published_id: "content-strategy-prompt",
    slug: "content-strategy-planner",
    prompt:
      "As a content marketing strategist, help me create a content plan for [BUSINESS/BRAND] targeting [AUDIENCE]. Please provide: 1) Content pillars and themes that resonate with the audience, 2) Content types and formats for maximum engagement, 3) Publishing frequency and optimal timing, 4) Distribution channels and promotion strategy, 5) KPIs to track success. Make it actionable and data-driven.",
    detailed_description:
      "Build a comprehensive content marketing strategy with AI-powered insights on topics, formats, and distribution channels. Get data-driven recommendations for content that resonates with your audience and drives measurable business results.",
    tools: [
      {
        name: "Creative AI",
        description: "Content ideation and planning",
        category: "creative",
      },
      {
        name: "Search",
        description: "Trend analysis and research",
        category: "search",
      },
      {
        name: "Memory",
        description: "Audience and brand context",
        category: "memory",
      },
    ],
    steps: [
      {
        title: "Define audience and goals",
        description:
          "Specify your target audience, business objectives, and content goals",
      },
      {
        title: "Identify content pillars",
        description:
          "Receive key themes and topics that resonate with your audience",
      },
      {
        title: "Select content formats",
        description:
          "Get recommendations for content types and formats to maximize engagement",
      },
      {
        title: "Plan distribution strategy",
        description:
          "Understand optimal channels, timing, and promotion tactics",
      },
      {
        title: "Set success metrics",
        description:
          "Define KPIs and tracking methods to measure content performance",
      },
    ],
  },

  // Knowledge Workers
  {
    title: "Meeting Minutes Summarizer",
    description:
      "Automatically transcribe meetings, extract action items, and distribute summaries to participants",
    action_type: "workflow",
    integrations: ["documents", "mail", "productivity"],
    categories: ["Knowledge Workers"],
    published_id: "meeting-minutes-workflow",
    slug: "meeting-minutes-summarizer",
    detailed_description:
      "Never miss important meeting details again with automated transcription, intelligent summarization, and action item extraction. This workflow captures key decisions, assigns tasks, and automatically distributes meeting summaries to all participants.",
    tools: [
      {
        name: "Documents",
        description: "Minutes creation and formatting",
        category: "documents",
      },
      {
        name: "Gmail",
        description: "Summary distribution",
        category: "gmail",
      },
      {
        name: "Productivity Tools",
        description: "Task and action item management",
        category: "productivity",
      },
    ],
    steps: [
      {
        title: "Record meeting",
        description:
          "Capture meeting audio or provide transcript for processing",
      },
      {
        title: "Generate summary",
        description:
          "AI extracts key discussion points, decisions, and outcomes",
      },
      {
        title: "Identify action items",
        description:
          "Automatically detect tasks, owners, and deadlines from discussion",
      },
      {
        title: "Create formatted minutes",
        description:
          "Generate professional meeting minutes document with all details",
      },
      {
        title: "Distribute to participants",
        description:
          "Automatically email summaries and assign tasks to attendees",
      },
    ],
  },
  {
    title: "Decision Framework Helper",
    description:
      "Structure complex decisions with pros/cons analysis, risk assessment, and recommendation frameworks",
    action_type: "prompt",
    integrations: ["memory", "documents", "productivity"],
    categories: ["Knowledge Workers"],
    published_id: "decision-framework-prompt",
    slug: "decision-framework-helper",
    prompt:
      "You are a strategic decision consultant. I need help making this decision: [DECISION DESCRIPTION]. Please help me: 1) Structure the decision with clear options and criteria, 2) Analyze pros and cons for each option, 3) Assess risks and potential outcomes, 4) Consider short-term vs long-term implications, 5) Provide a recommendation with clear reasoning. Use a systematic decision-making framework.",
    detailed_description:
      "Make better decisions with structured analysis and strategic frameworks. Get comprehensive evaluation of options, risks, and outcomes to confidently choose the best path forward for complex business and professional decisions.",
    tools: [
      {
        name: "Memory",
        description: "Context and criteria tracking",
        category: "memory",
      },
      {
        name: "Documents",
        description: "Decision framework documentation",
        category: "documents",
      },
      {
        name: "Productivity",
        description: "Decision tracking and implementation",
        category: "productivity",
      },
    ],
    steps: [
      {
        title: "Define the decision",
        description:
          "Clearly articulate the decision you need to make and key constraints",
      },
      {
        title: "Structure options",
        description:
          "Receive organized framework with decision criteria and alternatives",
      },
      {
        title: "Analyze trade-offs",
        description:
          "Review comprehensive pros and cons analysis for each option",
      },
      {
        title: "Assess risks",
        description:
          "Understand potential outcomes and implications of each choice",
      },
      {
        title: "Get recommendation",
        description:
          "Receive data-driven recommendation with clear reasoning and next steps",
      },
    ],
  },
  {
    title: "Research Synthesis Assistant",
    description:
      "Synthesize information from multiple sources into coherent insights and recommendations",
    action_type: "prompt",
    integrations: ["search", "memory", "documents"],
    categories: ["Knowledge Workers"],
    published_id: "research-synthesis-prompt",
    slug: "research-synthesis-assistant",
    prompt:
      "You are a research analyst expert. I've gathered information about [RESEARCH TOPIC] from various sources. Please help me: 1) Identify key themes and patterns across the sources, 2) Synthesize main findings and insights, 3) Highlight conflicting viewpoints and their validity, 4) Draw actionable conclusions and recommendations, 5) Suggest areas for further investigation. Present findings in a structured, executive-friendly format.",
    detailed_description:
      "Transform scattered research into actionable insights with AI-powered synthesis. Automatically identify patterns, reconcile conflicting information, and generate executive summaries that distill complex research into clear, strategic recommendations.",
    tools: [
      {
        name: "Search",
        description: "Information gathering and validation",
        category: "search",
      },
      {
        name: "Memory",
        description: "Source tracking and context retention",
        category: "memory",
      },
      {
        name: "Documents",
        description: "Research report generation",
        category: "documents",
      },
    ],
    steps: [
      {
        title: "Provide research sources",
        description:
          "Share the information and materials you've collected on your topic",
      },
      {
        title: "Identify themes",
        description: "AI extracts key themes, patterns, and recurring concepts",
      },
      {
        title: "Synthesize findings",
        description:
          "Receive integrated analysis combining insights from all sources",
      },
      {
        title: "Review conflicts",
        description:
          "Understand contradicting viewpoints and their supporting evidence",
      },
      {
        title: "Get recommendations",
        description:
          "Receive actionable conclusions and suggestions for next steps",
      },
    ],
  },

  // Business & Ops
  {
    title: "Invoice Processing System",
    description:
      "Automate invoice processing, approval workflows, and payment scheduling",
    action_type: "workflow",
    integrations: ["documents", "mail", "productivity"],
    categories: ["Business & Ops"],
    published_id: "invoice-processing-workflow",
    slug: "invoice-processing-system",
    detailed_description:
      "Streamline your accounts payable process with automated invoice data extraction, intelligent approval routing, and scheduled payment management. Reduce manual errors, accelerate processing times, and maintain complete audit trails for all financial transactions.",
    tools: [
      {
        name: "Documents",
        description: "Invoice data extraction and processing",
        category: "documents",
      },
      {
        name: "Gmail",
        description: "Invoice receipt and notifications",
        category: "gmail",
      },
      {
        name: "Productivity Tools",
        description: "Approval workflow management",
        category: "productivity",
      },
    ],
    steps: [
      {
        title: "Receive invoices",
        description:
          "Automatically capture invoices from email or document uploads",
      },
      {
        title: "Extract data",
        description:
          "AI reads and extracts vendor, amount, date, and line items",
      },
      {
        title: "Route for approval",
        description:
          "Automatically send to appropriate approvers based on rules",
      },
      {
        title: "Schedule payment",
        description: "Queue approved invoices for payment on due dates",
      },
      {
        title: "Track and report",
        description: "Monitor payment status and generate financial reports",
      },
    ],
  },
  {
    title: "Team Performance Analyzer",
    description:
      "Analyze team productivity, identify bottlenecks, and recommend improvements for better collaboration",
    action_type: "prompt",
    integrations: ["productivity", "memory", "documents"],
    categories: ["Business & Ops"],
    published_id: "team-performance-prompt",
    slug: "team-performance-analyzer",
    prompt:
      "You are an organizational efficiency expert. Help me analyze my team's performance. Team details: [TEAM DESCRIPTION] and current challenges: [CHALLENGES]. Please provide: 1) Performance metrics and KPI analysis, 2) Identification of productivity bottlenecks, 3) Communication and collaboration improvement suggestions, 4) Process optimization recommendations, 5) Action plan with measurable goals. Focus on practical, implementable solutions.",
    detailed_description:
      "Optimize team performance with data-driven analysis of productivity patterns, collaboration dynamics, and workflow efficiency. Get actionable recommendations to eliminate bottlenecks, improve communication, and boost overall team effectiveness.",
    tools: [
      {
        name: "Productivity",
        description: "Performance tracking and analysis",
        category: "productivity",
      },
      {
        name: "Memory",
        description: "Team context and historical data",
        category: "memory",
      },
      {
        name: "Documents",
        description: "Performance report generation",
        category: "documents",
      },
    ],
    steps: [
      {
        title: "Describe your team",
        description:
          "Provide team structure, roles, and current performance challenges",
      },
      {
        title: "Analyze metrics",
        description:
          "Receive analysis of key performance indicators and productivity data",
      },
      {
        title: "Identify bottlenecks",
        description:
          "Discover specific areas hindering team productivity and efficiency",
      },
      {
        title: "Review recommendations",
        description:
          "Get targeted suggestions for process and collaboration improvements",
      },
      {
        title: "Implement action plan",
        description:
          "Follow structured roadmap with measurable goals and milestones",
      },
    ],
  },
  {
    title: "Process Optimization Consultant",
    description:
      "Analyze business processes and recommend efficiency improvements and automation opportunities",
    action_type: "prompt",
    integrations: ["productivity", "memory", "documents"],
    categories: ["Business & Ops"],
    published_id: "process-optimization-prompt",
    slug: "process-optimization-consultant",
    prompt:
      "Act as a business process consultant. I want to optimize [PROCESS NAME] in my organization. Current process: [PROCESS DESCRIPTION]. Please provide: 1) Process inefficiencies and bottlenecks analysis, 2) Automation opportunities and tools, 3) Workflow improvements and reorganization suggestions, 4) Resource optimization recommendations, 5) Implementation roadmap with priorities. Focus on measurable improvements and ROI.",
    detailed_description:
      "Transform inefficient business processes with expert analysis and optimization strategies. Identify automation opportunities, eliminate waste, and implement improvements that deliver measurable ROI and operational excellence.",
    tools: [
      {
        name: "Productivity",
        description: "Process mapping and optimization",
        category: "productivity",
      },
      {
        name: "Memory",
        description: "Process context and workflow tracking",
        category: "memory",
      },
      {
        name: "Documents",
        description: "Optimization report and roadmap creation",
        category: "documents",
      },
    ],
    steps: [
      {
        title: "Map current process",
        description:
          "Document your existing workflow, steps, and stakeholders involved",
      },
      {
        title: "Identify inefficiencies",
        description:
          "Receive detailed analysis of bottlenecks and waste in current process",
      },
      {
        title: "Explore automation",
        description:
          "Discover opportunities to automate tasks and reduce manual work",
      },
      {
        title: "Design improvements",
        description:
          "Get recommendations for workflow reorganization and optimization",
      },
      {
        title: "Follow implementation roadmap",
        description:
          "Execute prioritized action plan with clear ROI projections",
      },
    ],
  },
];
