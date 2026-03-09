import { combosBatchB } from "./combosData-b";
import { combosBatchC } from "./combosData-c";
import { combosBatchD } from "./combosData-d";
import { combosBatchE } from "./combosData-e";
import { combosBatchF } from "./combosData-f";
import { combosBatchG } from "./combosData-g";
import { combosBatchH } from "./combosData-h";

export interface IntegrationCombo {
  slug: string;
  toolA: string;
  toolASlug: string;
  toolB: string;
  toolBSlug: string;
  tagline: string;
  metaTitle: string;
  metaDescription: string;
  keywords: string[];
  intro: string;
  useCases: Array<{ title: string; description: string }>;
  howItWorks: Array<{ step: string; description: string }>;
  faqs: Array<{ question: string; answer: string }>;
  /** When set, this page's canonical points to /automate/{canonicalSlug} — use for reverse-order duplicate combos (e.g. github-slack → slack-github). */
  canonicalSlug?: string;
}

export const combos: Record<string, IntegrationCombo> = {
  "gmail-slack": {
    slug: "gmail-slack",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline: "Turn emails into Slack messages and vice versa automatically",
    metaTitle: "Gmail + Slack Automation - Connect Email and Team Chat | GAIA",
    metaDescription:
      "Automate Gmail and Slack together with GAIA. Forward important emails to Slack channels, create email drafts from Slack messages, and keep your team in sync without manual copy-pasting.",
    keywords: [
      "Gmail Slack integration",
      "Gmail Slack automation",
      "forward email to Slack",
      "email to Slack notification",
      "connect Gmail and Slack",
      "Gmail Slack workflow",
    ],
    intro:
      "Gmail and Slack are the two communication tools most teams live inside every day, yet they operate in completely separate silos. Important client emails sit unread while the team is active on Slack. Urgent Slack messages get missed because a colleague is heads-down in their inbox. The result is duplicated effort, missed context, and a constant scramble to keep both channels synchronized.\n\nGAIA bridges Gmail and Slack so information flows between them automatically. When a high-priority email arrives in Gmail, GAIA can route it to the relevant Slack channel with full context. When a decision is made in a Slack thread, GAIA can draft a follow-up email and queue it for review. Instead of manually translating between two communication platforms, your team gets a unified workflow where email and chat reinforce each other.\n\nThis integration is especially powerful for customer-facing teams who receive client emails but collaborate internally on Slack, and for operations teams who need to loop in colleagues on important vendor communications without forwarding chains that lose context.",
    useCases: [
      {
        title: "Route VIP emails to Slack channels",
        description:
          "GAIA monitors your Gmail for emails from key clients, executives, or priority senders and automatically posts a formatted summary to the designated Slack channel so the right people are notified instantly.",
      },
      {
        title: "Convert Slack decisions into email drafts",
        description:
          "When a decision is finalized in a Slack thread, ask GAIA to draft the corresponding client email. It reads the thread context and composes a professional reply ready for your review in Gmail.",
      },
      {
        title: "Daily email digest to Slack",
        description:
          "GAIA compiles a morning digest of your most important unread Gmail messages and posts a structured summary to your personal Slack DM so you start each day knowing exactly what needs attention.",
      },
      {
        title: "Support ticket escalation",
        description:
          "Customer support emails that exceed response SLAs trigger an automatic Slack alert in your support channel, including the sender, subject, and time since receipt so nothing slips through.",
      },
      {
        title: "Meeting confirmation sync",
        description:
          "When a meeting confirmation lands in Gmail, GAIA posts a heads-up to the relevant Slack channel so everyone knows the meeting is confirmed without requiring a manual announcement.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Slack to GAIA",
        description:
          "Authenticate your Gmail account and Slack workspace in GAIA's integration settings. Both connections use OAuth so your credentials stay secure and GAIA only accesses what it needs.",
      },
      {
        step: "Define your automation rules",
        description:
          "Tell GAIA which emails should route to which Slack channels, what format the notifications should take, and when you want digests delivered. You can use natural language to describe the rules.",
      },
      {
        step: "GAIA runs the workflow automatically",
        description:
          "Once configured, GAIA monitors Gmail continuously and executes your rules without you lifting a finger. You can adjust rules anytime by simply telling GAIA what you want changed.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA forward entire emails to Slack or just summaries?",
        answer:
          "Both. GAIA can post the full email body, a concise AI-generated summary, or just the key metadata (sender, subject, time) depending on what you specify. For long emails, summaries are usually more practical for Slack.",
      },
      {
        question:
          "Will GAIA send emails from Slack automatically or always ask me first?",
        answer:
          "By default GAIA drafts emails for your review before sending. You can configure it to auto-send for specific low-stakes scenarios like meeting confirmations, but GAIA will always respect your preference for human approval on outbound communications.",
      },
      {
        question:
          "Does this work with Gmail labels and Slack channels together?",
        answer:
          "Yes. You can instruct GAIA to monitor specific Gmail labels and route them to corresponding Slack channels. For example, emails labeled 'Urgent' can go to a #urgent Slack channel while emails labeled 'Newsletters' are silently archived.",
      },
    ],
  },

  "gmail-notion": {
    slug: "gmail-notion",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Transform emails into structured Notion pages and databases",
    metaTitle: "Gmail + Notion Automation - Email to Knowledge Base | GAIA",
    metaDescription:
      "Automate Gmail and Notion with GAIA. Convert important emails into Notion pages, update databases from email content, and build a searchable knowledge base from your inbox.",
    keywords: [
      "Gmail Notion integration",
      "email to Notion automation",
      "Gmail Notion workflow",
      "save emails to Notion",
      "connect Gmail and Notion",
    ],
    intro:
      "Your inbox is full of valuable information: client briefs, project updates, research summaries, and decisions that need to be preserved and searchable. But Gmail is a poor knowledge base. Emails get buried, threads become hard to navigate, and colleagues who weren't CC'd lack context.\n\nGAIA connects Gmail and Notion so important email content flows automatically into your knowledge management system. Client emails become structured Notion database entries. Project update threads get converted into linked pages with proper context. Research compiled over email gets organized into searchable Notion documents.\n\nThe result is an inbox that feeds your knowledge base rather than competing with it. Information captured in Gmail becomes accessible in Notion without the manual work of copy-pasting and reformatting.",
    useCases: [
      {
        title: "Client communication log",
        description:
          "GAIA automatically creates a Notion database entry for each significant client email, including sender, date, key points, and action items extracted by AI, giving your team a searchable client communication history.",
      },
      {
        title: "Project update capture",
        description:
          "Status update emails from stakeholders and vendors get converted into structured Notion pages linked to the relevant project, keeping your project documentation up to date without manual effort.",
      },
      {
        title: "Action item extraction",
        description:
          "GAIA reads incoming emails, identifies commitments and action items, and adds them as tasks to your Notion workspace so nothing gets buried in your inbox.",
      },
      {
        title: "Meeting notes from email threads",
        description:
          "When a meeting is confirmed over email, GAIA creates a Notion page pre-populated with attendees, agenda items mentioned in the email chain, and a space for notes.",
      },
      {
        title: "Research email archive",
        description:
          "Newsletter and research emails you mark for reading get saved to a structured Notion database with AI-generated summaries so you can find and reference them later without digging through Gmail.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Notion to GAIA",
        description:
          "Authenticate both accounts in GAIA. For Notion, GAIA will ask which workspace and databases it should have access to write to.",
      },
      {
        step: "Map email types to Notion destinations",
        description:
          "Tell GAIA which types of emails should go to which Notion databases or pages. You can use labels, senders, keywords, or AI classification to categorize incoming email.",
      },
      {
        step: "Review and refine the automation",
        description:
          "GAIA begins routing emails to Notion automatically. You can review what it creates and give feedback to improve accuracy. Most workflows are fully automated within a day or two of setup.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA update existing Notion pages or only create new ones?",
        answer:
          "GAIA can do both. It can create new database entries for each email or append information to an existing page. For example, follow-up emails from the same client can be appended to their existing Notion contact page rather than creating duplicates.",
      },
      {
        question: "Will GAIA extract attachments from emails into Notion?",
        answer:
          "GAIA can reference attachments and summarize their content, but uploading binary files to Notion directly depends on your Notion plan's storage limits. GAIA will note attachment details and can store links to them.",
      },
      {
        question: "Does this work with team Notion workspaces?",
        answer:
          "Yes. GAIA can write to shared Notion workspaces so email intelligence is available to your whole team. Each team member can connect their own Gmail, and GAIA will route their emails to the shared workspace.",
      },
    ],
  },

  "gmail-todoist": {
    slug: "gmail-todoist",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Todoist",
    toolBSlug: "todoist",
    tagline:
      "Turn emails into tasks automatically, zero inbox means zero missed tasks",
    metaTitle: "Gmail + Todoist Automation - Email to Task Automation | GAIA",
    metaDescription:
      "Automate Gmail and Todoist with GAIA. Convert emails into Todoist tasks automatically, set due dates from email context, and keep your task list in sync with your inbox.",
    keywords: [
      "Gmail Todoist integration",
      "email to task automation",
      "Gmail Todoist workflow",
      "create Todoist task from email",
      "inbox to task list automation",
    ],
    intro:
      "Every email that requires action is a potential task — but manually transferring action items from Gmail to Todoist is time-consuming and easy to forget. Emails accumulate, the mental overhead of deciding what needs to go on your task list grows, and important commitments get buried in threads.\n\nGAIA automates the Gmail-to-Todoist pipeline. It reads your emails, identifies action items and commitments, and creates corresponding Todoist tasks with appropriate due dates, priorities, and project assignments. Your inbox becomes a source of tasks rather than a second to-do list you have to manage separately.",
    useCases: [
      {
        title: "Auto-create tasks from action emails",
        description:
          "GAIA identifies emails that require a response or action and creates a Todoist task for each one, including the sender's name, subject, and a summary of what's needed.",
      },
      {
        title: "Extract deadlines from email content",
        description:
          "When an email mentions a deadline ('please send by Friday' or 'due March 15'), GAIA sets the Todoist task due date automatically so the deadline is captured without manual entry.",
      },
      {
        title: "Follow-up task scheduling",
        description:
          "After you send an important email, GAIA creates a follow-up task in Todoist for three days later so you never forget to chase a response.",
      },
      {
        title: "Project assignment from email context",
        description:
          "GAIA reads email content and assigns new tasks to the right Todoist project based on keywords, sender, or email label, keeping your task list organized automatically.",
      },
      {
        title: "Newsletter-triggered learning tasks",
        description:
          "When an industry newsletter arrives with an article you want to read, GAIA adds a 'Read later' task to Todoist with the link and a brief description so valuable content doesn't disappear into your inbox.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Todoist to GAIA",
        description:
          "Authorize GAIA to access your Gmail inbox and your Todoist account. Setup takes under two minutes using OAuth authentication.",
      },
      {
        step: "Tell GAIA your task creation preferences",
        description:
          "Specify which types of emails should become tasks, which Todoist projects to use for different email categories, and how you want tasks named and prioritized.",
      },
      {
        step: "GAIA manages the pipeline continuously",
        description:
          "As new emails arrive, GAIA evaluates each one and creates Todoist tasks as configured. You get a clean task list that reflects your inbox without any manual work.",
      },
    ],
    faqs: [
      {
        question: "How does GAIA decide which emails need a task?",
        answer:
          "GAIA uses AI to classify emails by intent. Emails that include requests, deadlines, commitments, or follow-up requirements are flagged as action items. You can also set explicit rules like 'all emails from my manager become tasks'.",
      },
      {
        question: "Can GAIA complete Todoist tasks when I reply to an email?",
        answer:
          "Yes. GAIA can monitor your sent mail and mark the corresponding Todoist task as complete when it detects you've replied to the triggering email, keeping your task list accurate automatically.",
      },
      {
        question: "Will tasks created by GAIA clutter my Todoist inbox?",
        answer:
          "GAIA routes tasks to the appropriate Todoist projects rather than dumping everything in the inbox. You control the project mapping, so tasks land where they belong from the start.",
      },
    ],
  },

  "gmail-linear": {
    slug: "gmail-linear",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline: "Bridge customer emails and engineering issues automatically",
    metaTitle: "Gmail + Linear Automation - Email to Engineering Issues | GAIA",
    metaDescription:
      "Automate Gmail and Linear with GAIA. Convert customer bug reports and feature requests from email into Linear issues, and notify customers when their issues are resolved.",
    keywords: [
      "Gmail Linear integration",
      "email to Linear issue",
      "bug report email to Linear",
      "Gmail Linear automation",
      "customer email to engineering ticket",
    ],
    intro:
      "Customer bug reports and feature requests arrive over email. Engineering teams track work in Linear. Manually translating between these two worlds creates delays, loses context, and frustrates both customers and engineers.\n\nGAIA connects Gmail and Linear so customer-facing emails flow directly into your engineering workflow. Bug reports become Linear issues with proper formatting and priority. Feature requests get logged to the backlog. When an issue is resolved in Linear, GAIA drafts the customer reply in Gmail. The loop closes automatically.",
    useCases: [
      {
        title: "Bug report emails to Linear issues",
        description:
          "GAIA reads customer emails reporting bugs, extracts the relevant details, and creates a properly formatted Linear issue with title, description, and suggested priority based on the email's urgency.",
      },
      {
        title: "Feature request logging",
        description:
          "Feature requests arriving over email get converted into Linear backlog items with the customer's exact wording preserved so product teams have authentic user voice attached to each request.",
      },
      {
        title: "Customer status update drafts",
        description:
          "When a Linear issue is moved to 'Done', GAIA drafts a reply to the original customer email explaining the resolution, ready for a support agent to review and send.",
      },
      {
        title: "Issue triage from email volume",
        description:
          "When multiple customers email about the same problem, GAIA detects the pattern and creates a single high-priority Linear issue rather than duplicating the ticket for each email.",
      },
      {
        title: "Internal email-to-issue for team requests",
        description:
          "Internal emails from non-technical stakeholders requesting changes or fixes get converted into properly formatted Linear issues so engineering teams receive structured requests rather than vague email threads.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Linear to GAIA",
        description:
          "Authorize GAIA with your Gmail and Linear accounts. Specify which Linear team and project incoming email issues should be assigned to.",
      },
      {
        step: "Configure issue creation rules",
        description:
          "Tell GAIA which emails should become Linear issues — by sender domain, Gmail label, subject keywords, or AI classification. Set default priority and assignee rules.",
      },
      {
        step: "Close the loop with automated replies",
        description:
          "Configure GAIA to draft Gmail replies when Linear issues reach specific statuses. You review drafts before sending, ensuring quality customer communication.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA link Linear issues back to the original Gmail thread?",
        answer:
          "Yes. GAIA adds the Gmail thread URL to the Linear issue description so engineers always have a link back to the original customer communication for full context.",
      },
      {
        question:
          "Does GAIA deduplicate issues when multiple customers report the same bug?",
        answer:
          "GAIA uses semantic similarity to detect when new emails describe already-existing Linear issues and can add a comment to the existing issue instead of creating a duplicate.",
      },
      {
        question:
          "Can non-engineering teams use this for their own Linear workspaces?",
        answer:
          "Absolutely. Any team using Linear for project tracking can use this automation. Marketing teams can log campaign requests from email, operations teams can log vendor requests, and design teams can log feedback.",
      },
    ],
  },

  "gmail-asana": {
    slug: "gmail-asana",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline: "Convert emails into Asana tasks without leaving your inbox",
    metaTitle: "Gmail + Asana Automation - Email to Project Tasks | GAIA",
    metaDescription:
      "Automate Gmail and Asana with GAIA. Create Asana tasks from emails, assign them to team members, set due dates from email context, and keep projects on track automatically.",
    keywords: [
      "Gmail Asana integration",
      "email to Asana task",
      "Gmail Asana automation",
      "create Asana task from email",
      "inbox to project management",
    ],
    intro:
      "Project managers and team leads spend significant time triaging emails and manually creating Asana tasks. Client emails contain deliverables, internal emails contain action items, and stakeholder updates contain decisions that need to be tracked — all requiring manual entry into Asana.\n\nGAIA eliminates this manual work by automatically converting emails into Asana tasks with proper context, assignments, and due dates. Your inbox becomes a project management input rather than a separate system you manage in parallel.",
    useCases: [
      {
        title: "Client deliverable tracking",
        description:
          "When a client emails requesting a deliverable, GAIA creates an Asana task in the client project with the request details, due date extracted from the email, and assignment to the appropriate team member.",
      },
      {
        title: "Stakeholder request management",
        description:
          "Internal requests arriving by email get converted to Asana tasks assigned to the right team, ensuring requests don't get lost in inboxes and are properly tracked to completion.",
      },
      {
        title: "Meeting outcome tracking",
        description:
          "After meetings where decisions are communicated over email, GAIA extracts the action items and creates Asana tasks with owners and deadlines so follow-through is tracked.",
      },
      {
        title: "Vendor communication tracking",
        description:
          "Emails from vendors and suppliers become Asana tasks tracking expected deliveries, quote responses, and contract milestones so procurement workflows stay on schedule.",
      },
      {
        title: "Task completion confirmation",
        description:
          "When an Asana task is marked complete, GAIA drafts a completion confirmation email to the original requester so clients and stakeholders stay informed without extra effort.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Asana to GAIA",
        description:
          "Authorize GAIA with your Gmail and Asana accounts. Grant access to the relevant Asana workspaces and projects you want email tasks routed to.",
      },
      {
        step: "Set your task routing rules",
        description:
          "Configure which emails map to which Asana projects, how tasks should be named, and which team members should be assigned based on email content or sender.",
      },
      {
        step: "Monitor and iterate",
        description:
          "GAIA creates tasks from incoming emails automatically. Review the tasks it creates and provide feedback to refine the automation over time.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA assign Asana tasks to specific team members based on email content?",
        answer:
          "Yes. You can configure rules like 'emails about design go to the design team' or 'emails from client X go to account manager Y'. GAIA uses email content and sender rules to determine assignment.",
      },
      {
        question: "Does GAIA work with Asana subtasks and sections?",
        answer:
          "Yes. GAIA can create tasks in specific sections and add subtasks if the email contains multiple action items. You specify the structure you want in your configuration.",
      },
      {
        question: "What happens if an email has no clear action item?",
        answer:
          "GAIA only creates tasks when it detects actionable content. FYI emails, newsletters, and automated notifications are filtered out. You can always manually trigger task creation for any email by asking GAIA directly.",
      },
    ],
  },

  "slack-notion": {
    slug: "slack-notion",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Save Slack conversations and decisions to Notion automatically",
    metaTitle:
      "Slack + Notion Automation - Save Conversations to Knowledge Base | GAIA",
    metaDescription:
      "Automate Slack and Notion with GAIA. Save important Slack threads to Notion, create meeting notes from Slack conversations, and build a team knowledge base from your chat history.",
    keywords: [
      "Slack Notion integration",
      "save Slack to Notion",
      "Slack Notion automation",
      "Slack thread to Notion page",
      "team knowledge base from Slack",
    ],
    intro:
      "Slack is where decisions get made and knowledge gets shared — and then immediately buried under the next conversation. Important context, architectural decisions, and team agreements disappear into an ever-scrolling chat history that becomes impossible to search meaningfully after a few months.\n\nGAIA preserves Slack knowledge in Notion automatically. When a decision is made in a Slack thread, GAIA captures it as a decision log in Notion. When a helpful how-to is shared in a channel, GAIA converts it into a Notion page. The institutional knowledge your team generates in Slack becomes permanently accessible in your knowledge base.",
    useCases: [
      {
        title: "Decision log from Slack threads",
        description:
          "GAIA monitors Slack channels for decision discussions and automatically creates structured Notion entries capturing the decision, rationale, and participants so decisions are documented without extra effort.",
      },
      {
        title: "Meeting notes from Slack huddles",
        description:
          "After a Slack huddle or quick sync, GAIA compiles a summary from the post-meeting Slack thread and creates a formatted meeting notes page in Notion with action items and owners.",
      },
      {
        title: "Knowledge sharing capture",
        description:
          "When a team member shares a useful tip, guide, or process explanation in Slack, GAIA can save it to the relevant Notion section so it doesn't disappear from the channel.",
      },
      {
        title: "Project update documentation",
        description:
          "Regular status updates posted in Slack project channels get automatically appended to the corresponding Notion project page, creating a living project history.",
      },
      {
        title: "Onboarding content creation",
        description:
          "Frequently asked questions in Slack channels get flagged and converted to Notion FAQ entries, building your team onboarding documentation from real new-hire questions.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Notion to GAIA",
        description:
          "Authorize GAIA in your Slack workspace and Notion account. Select which Slack channels GAIA should monitor and which Notion workspace it should write to.",
      },
      {
        step: "Define capture rules",
        description:
          "Specify what GAIA should capture — threads with a specific emoji reaction, messages in designated channels, or content matching certain keywords. Set the Notion destination for each rule.",
      },
      {
        step: "Build your knowledge base automatically",
        description:
          "GAIA runs continuously in the background. Team members can also trigger capture manually by reacting to a Slack message with a specific emoji that tells GAIA to save it.",
      },
    ],
    faqs: [
      {
        question:
          "Can team members trigger Notion saves from Slack without GAIA's intervention?",
        answer:
          "Yes. You can configure a specific emoji reaction (like a bookmark emoji) that any team member can add to a Slack message to trigger GAIA to save it to Notion. This gives the team control while automating the capture.",
      },
      {
        question:
          "Does GAIA capture entire threads or just individual messages?",
        answer:
          "By default GAIA captures entire threads when a capture is triggered, preserving the full conversation context. You can configure it to capture only the parent message or a summarized version of the thread.",
      },
      {
        question: "Will GAIA create new Notion pages or add to existing ones?",
        answer:
          "Both behaviors are configurable. Project updates can append to existing project pages while standalone knowledge snippets create new pages. You define the logic based on your Notion structure.",
      },
    ],
  },

  "slack-linear": {
    slug: "slack-linear",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline:
      "Create and update Linear issues directly from Slack conversations",
    metaTitle: "Slack + Linear Automation - Manage Issues from Slack | GAIA",
    metaDescription:
      "Automate Slack and Linear with GAIA. Create Linear issues from Slack messages, get issue updates in Slack, and keep your engineering team aligned without switching tools.",
    keywords: [
      "Slack Linear integration",
      "create Linear issue from Slack",
      "Slack Linear automation",
      "Linear Slack notifications",
      "engineering workflow automation",
    ],
    intro:
      "Engineering teams live in Slack. Bugs get reported there, features get discussed there, and incidents get triaged there. But work tracking happens in Linear. The friction of switching between them and manually creating issues means some work never gets properly tracked.\n\nGAIA makes Slack a first-class interface for Linear. Team members can create issues, update statuses, and check progress without leaving Slack. GAIA also brings Linear updates back into Slack so the right channels are always informed when issues are resolved or status changes.",
    useCases: [
      {
        title: "Create Linear issues from Slack messages",
        description:
          "Any Slack message can become a Linear issue with a simple emoji reaction or GAIA command. GAIA extracts the message content and formats it into a proper issue with title, description, and suggested priority.",
      },
      {
        title: "Incident tracking from Slack",
        description:
          "When an incident is being discussed in a Slack channel, GAIA creates a tracking issue in Linear automatically, links it to the Slack thread, and updates the issue as the incident evolves.",
      },
      {
        title: "Linear status updates to Slack",
        description:
          "When a Linear issue changes status, GAIA posts an update to the relevant Slack channel or DMs the issue creator so the team knows about progress without checking Linear manually.",
      },
      {
        title: "Sprint planning from Slack",
        description:
          "During Slack-based sprint planning discussions, GAIA can create multiple Linear issues at once from a structured list shared in the channel, saving the manual entry work.",
      },
      {
        title: "Standup reporting from Linear to Slack",
        description:
          "GAIA compiles each engineer's Linear activity (completed issues, in-progress work, blockers) and posts personalized standup summaries to Slack every morning.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Linear to GAIA",
        description:
          "Add GAIA to your Slack workspace and connect your Linear account. Specify which Slack channels correspond to which Linear teams and projects.",
      },
      {
        step: "Set up issue creation triggers",
        description:
          "Choose how issues are created — via emoji reactions, slash commands, or GAIA monitoring specific channels for bug reports. Configure default assignees and labels for each channel.",
      },
      {
        step: "Configure Slack notifications for Linear events",
        description:
          "Specify which Linear status changes should notify which Slack channels or users. Set your notification preferences to avoid alert fatigue while staying informed.",
      },
    ],
    faqs: [
      {
        question:
          "Can I update Linear issue status from Slack without opening Linear?",
        answer:
          "Yes. You can ask GAIA in Slack to update an issue status, change assignee, add a comment, or close an issue. GAIA handles the Linear API call and confirms the update in Slack.",
      },
      {
        question: "How does GAIA handle Linear issue linking to Slack threads?",
        answer:
          "GAIA adds the Slack thread permalink to the Linear issue description automatically, and can also post the Linear issue URL back into Slack so both sides are linked for easy navigation.",
      },
      {
        question: "Can non-engineers use this integration?",
        answer:
          "Yes. Product managers, designers, and support teams can use Slack to create and check Linear issues without needing Linear access or training. GAIA acts as the translation layer.",
      },
    ],
  },

  "slack-github": {
    slug: "slack-github",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "GitHub",
    toolBSlug: "github",
    tagline: "Get GitHub notifications in Slack and manage PRs from chat",
    metaTitle:
      "Slack + GitHub Automation - GitHub Notifications in Slack | GAIA",
    metaDescription:
      "Automate Slack and GitHub with GAIA. Get smart GitHub PR and issue notifications in Slack, manage code reviews from chat, and keep your engineering team aligned on repository activity.",
    keywords: [
      "Slack GitHub integration",
      "GitHub notifications Slack",
      "Slack GitHub automation",
      "PR review notifications Slack",
      "GitHub Slack bot",
    ],
    intro:
      "GitHub generates a torrent of notifications — pull request reviews, issue comments, CI failures, and deployment statuses. Most engineers mute GitHub emails and miss important events. The official GitHub Slack integration delivers too much noise without enough intelligence.\n\nGAIA brings smart GitHub activity to Slack with filtering and context. PR review requests go to the right engineer's DM. CI failures post to the team channel with a summary of what broke. Merged PRs trigger release notes drafts. Your team gets the GitHub signal it needs in Slack without the noise it doesn't.",
    useCases: [
      {
        title: "Smart PR review notifications",
        description:
          "When you're requested for a code review, GAIA sends a Slack DM with the PR title, description, diff size, and a direct link — giving you just enough context to prioritize reviews without opening GitHub.",
      },
      {
        title: "CI/CD failure alerts",
        description:
          "When a GitHub Actions workflow fails, GAIA posts a structured failure summary to the engineering Slack channel including the failing step, error message, and a link to the run.",
      },
      {
        title: "PR merge announcements",
        description:
          "When a significant PR is merged, GAIA posts a changelog entry to the team channel summarizing what was changed, who contributed, and any related issues that were closed.",
      },
      {
        title: "Issue triage in Slack",
        description:
          "New GitHub issues that meet priority criteria trigger Slack notifications to the relevant team channel with issue details and a prompt to assign and label.",
      },
      {
        title: "Deploy status updates",
        description:
          "Deployment events from GitHub trigger Slack notifications confirming successful deploys or alerting on deployment failures with rollback instructions.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Slack to GAIA",
        description:
          "Authorize GAIA with your GitHub organization and Slack workspace. Configure which repositories and branches GAIA should monitor.",
      },
      {
        step: "Configure notification rules",
        description:
          "Define which GitHub events should post to which Slack channels or users. Set filters so only relevant activity generates notifications — reducing noise while maintaining signal.",
      },
      {
        step: "Interact with GitHub from Slack",
        description:
          "Once connected, you can ask GAIA to check PR status, list open issues, or trigger actions directly from Slack without visiting GitHub.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA filter GitHub notifications so I only see what matters?",
        answer:
          "Yes. GAIA applies intelligent filtering based on your role, which repositories you're assigned to, and the priority you've set for different event types. You control the signal-to-noise ratio.",
      },
      {
        question: "Does GAIA replace the official GitHub Slack app?",
        answer:
          "GAIA provides more intelligent and configurable notifications than the official GitHub app. You can use both, or replace the official app with GAIA for a cleaner notification experience.",
      },
      {
        question:
          "Can GAIA handle GitHub notifications for multiple repositories?",
        answer:
          "Yes. GAIA supports monitoring multiple repositories and can route notifications from different repos to different Slack channels based on your team's structure.",
      },
    ],
  },

  "slack-asana": {
    slug: "slack-asana",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline: "Create Asana tasks from Slack and track progress in chat",
    metaTitle: "Slack + Asana Automation - Task Management from Slack | GAIA",
    metaDescription:
      "Automate Slack and Asana with GAIA. Create Asana tasks from Slack messages, get task updates in Slack, and manage project work without switching between apps.",
    keywords: [
      "Slack Asana integration",
      "create Asana task from Slack",
      "Slack Asana automation",
      "Asana Slack notifications",
      "project management Slack automation",
    ],
    intro:
      "Project teams coordinate in Slack but track work in Asana. The gap between the two means tasks get agreed upon in Slack but never formally created in Asana, and Asana updates don't reach the team in Slack. GAIA closes this loop so your team can coordinate in Slack while maintaining proper project tracking in Asana.",
    useCases: [
      {
        title: "Create tasks from Slack messages",
        description:
          "React to any Slack message with a task emoji or GAIA command to instantly create an Asana task. GAIA uses the message content as the task description and prompts for due date and assignee.",
      },
      {
        title: "Task completion notifications",
        description:
          "When an Asana task is completed, GAIA notifies the relevant Slack channel or thread so teammates know work is done without manually checking Asana.",
      },
      {
        title: "Daily project standup digest",
        description:
          "GAIA compiles a morning summary of Asana tasks due today and overdue tasks and posts it to the team Slack channel to align everyone on daily priorities.",
      },
      {
        title: "Blocked task alerts",
        description:
          "When a task is marked blocked in Asana, GAIA sends a Slack alert to the task owner and project manager so blockers get attention quickly.",
      },
      {
        title: "Milestone celebration posts",
        description:
          "When a project milestone is reached in Asana, GAIA posts a celebratory update to the team Slack channel recognizing contributors and announcing the achievement.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Asana to GAIA",
        description:
          "Add GAIA to your Slack workspace and connect your Asana account with access to the relevant workspaces and projects.",
      },
      {
        step: "Map Slack channels to Asana projects",
        description:
          "Tell GAIA which Slack channels correspond to which Asana projects so tasks created from Slack automatically go to the right project.",
      },
      {
        step: "Configure bidirectional notifications",
        description:
          "Set which Asana events should notify which Slack channels. Start with task completion and due-date reminders, then add more events as needed.",
      },
    ],
    faqs: [
      {
        question: "Can I update Asana task details from Slack?",
        answer:
          "Yes. You can ask GAIA in Slack to update a task's due date, assignee, description, or status. GAIA confirms the change and updates Asana in real time.",
      },
      {
        question: "Does GAIA work with Asana templates and custom fields?",
        answer:
          "GAIA can create tasks from templates and populate custom fields if you specify them in your instructions. Advanced custom field automation may require initial configuration.",
      },
      {
        question: "Can multiple Slack channels map to the same Asana project?",
        answer:
          "Yes. Multiple Slack channels can feed into the same Asana project, which is useful when different teams contribute to the same project from their own channels.",
      },
    ],
  },

  "slack-todoist": {
    slug: "slack-todoist",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Todoist",
    toolBSlug: "todoist",
    tagline: "Capture tasks from Slack into Todoist without breaking your flow",
    metaTitle:
      "Slack + Todoist Automation - Create Todoist Tasks from Slack | GAIA",
    metaDescription:
      "Automate Slack and Todoist with GAIA. Create personal Todoist tasks from Slack messages, get reminders in Slack, and never lose track of action items from team conversations.",
    keywords: [
      "Slack Todoist integration",
      "create Todoist task from Slack",
      "Slack Todoist automation",
      "Slack action items to Todoist",
      "personal task management Slack",
    ],
    intro:
      "You get assigned things in Slack all day long. 'Can you handle X?' and 'Don't forget Y' messages pile up and then scroll away. Without a system to capture these, important tasks fall through the cracks. GAIA captures action items from Slack and adds them to Todoist immediately, so your personal task list reflects everything you've committed to.",
    useCases: [
      {
        title: "Save action items with a reaction",
        description:
          "React to any Slack message with a designated emoji and GAIA creates a corresponding Todoist task. The message content becomes the task description, timestamped and linked back to the Slack thread.",
      },
      {
        title: "Morning Todoist briefing in Slack",
        description:
          "GAIA sends you a Slack DM every morning summarizing your Todoist tasks due today and tomorrow so you can plan your day without opening another app.",
      },
      {
        title: "Task reminders in Slack",
        description:
          "Instead of relying on Todoist's push notifications, GAIA sends overdue task reminders as Slack DMs when you're active in Slack so reminders reach you where you're already working.",
      },
      {
        title: "Team commitment tracking",
        description:
          "When you commit to something in a Slack thread, GAIA detects the commitment ('I'll have that ready by Thursday') and automatically adds a Todoist task with the appropriate due date.",
      },
      {
        title: "Channel-specific task capture",
        description:
          "Configure GAIA to monitor specific Slack channels and automatically add action items mentioned there to the corresponding Todoist project, keeping channel work and personal tasks in sync.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Todoist to GAIA",
        description:
          "Add GAIA to your Slack workspace and authorize your Todoist account. This takes under two minutes.",
      },
      {
        step: "Choose your capture method",
        description:
          "Pick how you want to save tasks: emoji reactions, GAIA mentions, or automatic detection of assignment language. Configure the default Todoist project for Slack-created tasks.",
      },
      {
        step: "GAIA keeps your task list current",
        description:
          "GAIA monitors Slack for tasks and commitments and adds them to Todoist. You can also ask GAIA at any time to 'add this to my tasks' directly in Slack.",
      },
    ],
    faqs: [
      {
        question: "Which emoji should I use to trigger task creation?",
        answer:
          "You can configure any emoji as your task trigger in GAIA settings. Common choices are the white check mark, clipboard, or bookmark emoji. GAIA will confirm the task was created with a reaction back on the message.",
      },
      {
        question:
          "Can GAIA detect when tasks are completed in Todoist and react in Slack?",
        answer:
          "Yes. When you complete a Todoist task that was created from a Slack message, GAIA can post a completion confirmation to the original Slack thread so collaborators know the work is done.",
      },
      {
        question:
          "Does this integration work for personal Todoist accounts or only teams?",
        answer:
          "It works for both personal and team Todoist accounts. Individual users can use it to capture personal tasks from Slack, while teams can use it to manage shared project tasks.",
      },
    ],
  },

  "github-linear": {
    slug: "github-linear",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline: "Sync GitHub PRs and issues with Linear tickets automatically",
    metaTitle: "GitHub + Linear Automation - Sync Code and Issues | GAIA",
    metaDescription:
      "Automate GitHub and Linear with GAIA. Sync pull requests with Linear issues, auto-update issue status when PRs merge, and keep your code and project management in perfect sync.",
    keywords: [
      "GitHub Linear integration",
      "GitHub Linear sync",
      "PR to Linear issue",
      "GitHub Linear automation",
      "code review project management sync",
    ],
    intro:
      "Engineering teams use GitHub for code and Linear for project management, but the two rarely stay in sync. A PR gets merged but the Linear issue stays 'In Progress'. An issue is closed in Linear but the related branch is still open. This drift between code reality and project management causes confusion and makes planning unreliable.\n\nGAIA keeps GitHub and Linear synchronized. PR status changes update Linear issues. Merged PRs mark issues complete. New GitHub issues can trigger Linear tickets. The result is a project management system that accurately reflects your codebase state.",
    useCases: [
      {
        title: "Auto-update Linear issue status from PR events",
        description:
          "When a PR is opened referencing a Linear issue, GAIA moves the issue to 'In Review'. When the PR merges, GAIA marks the issue as 'Done'. The Linear board always reflects actual code state.",
      },
      {
        title: "Create Linear issues from GitHub issues",
        description:
          "Bug reports and feature requests filed in GitHub can automatically create corresponding Linear tickets, ensuring engineering backlog and GitHub issue tracker stay in sync.",
      },
      {
        title: "PR cycle time reporting",
        description:
          "GAIA tracks the time from Linear issue creation to GitHub PR merge and generates weekly reports showing cycle time by team member and issue type to identify bottlenecks.",
      },
      {
        title: "Branch naming convention enforcement",
        description:
          "GAIA monitors new GitHub branches and alerts if the branch name doesn't follow the convention that links it to a Linear issue, ensuring all work is properly tracked.",
      },
      {
        title: "Release notes generation",
        description:
          "When PRs are merged to main, GAIA compiles the linked Linear issues into structured release notes organized by feature area, ready for the changelog or product announcement.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Linear to GAIA",
        description:
          "Authorize GAIA with your GitHub organization and Linear workspace. Select which repositories and Linear teams to synchronize.",
      },
      {
        step: "Configure sync rules",
        description:
          "Define which GitHub events update which Linear issue states. The most common setup: PR opened → In Review, PR merged → Done, PR closed without merge → Back to Todo.",
      },
      {
        step: "Monitor sync accuracy",
        description:
          "GAIA runs the sync automatically. You can ask GAIA to audit sync status at any time and it will surface any issues or inconsistencies between GitHub and Linear.",
      },
    ],
    faqs: [
      {
        question: "How does GAIA link a GitHub PR to a Linear issue?",
        answer:
          "GAIA looks for Linear issue IDs in PR titles and branch names (like 'ENG-123' or 'feature/ENG-123-user-auth'). It can also parse PR descriptions for Linear issue URLs. Most engineering teams already use these conventions.",
      },
      {
        question: "What happens if a PR references multiple Linear issues?",
        answer:
          "GAIA updates all referenced Linear issues when the PR status changes. This is common for large PRs that resolve several related issues simultaneously.",
      },
      {
        question: "Can GAIA sync Linear issue fields to GitHub PR labels?",
        answer:
          "Yes. Linear issue priority, type, and labels can be mirrored as GitHub PR labels so code reviewers see project context directly in GitHub without switching to Linear.",
      },
    ],
  },

  "github-notion": {
    slug: "github-notion",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline:
      "Document your GitHub projects and decisions in Notion automatically",
    metaTitle:
      "GitHub + Notion Automation - Code Documentation in Notion | GAIA",
    metaDescription:
      "Automate GitHub and Notion with GAIA. Generate Notion documentation from GitHub repositories, save architectural decisions, and keep your engineering wiki up to date automatically.",
    keywords: [
      "GitHub Notion integration",
      "GitHub Notion automation",
      "code documentation Notion",
      "GitHub to Notion sync",
      "engineering wiki automation",
    ],
    intro:
      "Documentation is the first casualty of fast-moving engineering teams. GitHub repositories accumulate context — in commit messages, PR descriptions, and issue discussions — that never makes it into Notion's engineering wiki. GAIA bridges the gap by automatically surfacing GitHub intelligence into Notion documentation.",
    useCases: [
      {
        title: "ADR documentation from PR discussions",
        description:
          "When significant architectural decisions are made in GitHub PR reviews, GAIA extracts the decision and creates an Architecture Decision Record (ADR) in Notion for permanent reference.",
      },
      {
        title: "Release notes in Notion",
        description:
          "Every release gets a Notion page automatically populated with merged PRs, resolved issues, and contributor list, providing a permanent changelog in your knowledge base.",
      },
      {
        title: "Repository README sync",
        description:
          "GAIA monitors GitHub README updates and propagates changes to the corresponding Notion project page, keeping documentation consistent across both platforms.",
      },
      {
        title: "Sprint retrospective data",
        description:
          "GAIA compiles GitHub activity data (PRs merged, issues closed, review turnaround time) into a Notion retrospective template before each sprint review.",
      },
      {
        title: "Open issue dashboard",
        description:
          "GAIA maintains a live Notion database of open GitHub issues across repositories, organized by priority and team, giving product and engineering leadership a single view.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Notion to GAIA",
        description:
          "Authorize GAIA with your GitHub organization and Notion workspace. Define which repositories to monitor and which Notion sections to write to.",
      },
      {
        step: "Set up documentation workflows",
        description:
          "Configure which GitHub events generate Notion content. Start with release notes and grow to include issue tracking, ADRs, and retrospective data.",
      },
      {
        step: "GAIA keeps documentation current",
        description:
          "Documentation stays up to date automatically as GitHub activity occurs, ending the cycle of stale wikis that nobody trusts.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA read existing Notion pages to avoid creating duplicates?",
        answer:
          "Yes. Before creating new Notion content, GAIA checks whether a page for the same repository, release, or topic already exists and appends to it rather than duplicating.",
      },
      {
        question: "Does GAIA work with private GitHub repositories?",
        answer:
          "Yes. GAIA uses your authorized GitHub credentials and can access private repositories you have access to, subject to your organization's permissions.",
      },
      {
        question:
          "Can non-engineers use this to stay informed about GitHub activity?",
        answer:
          "This is one of the primary use cases. Product managers and stakeholders can get GitHub project summaries in Notion without needing GitHub access or understanding the code review workflow.",
      },
    ],
  },

  "github-asana": {
    slug: "github-asana",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline: "Link GitHub development work to Asana project milestones",
    metaTitle:
      "GitHub + Asana Automation - Dev Work to Project Milestones | GAIA",
    metaDescription:
      "Automate GitHub and Asana with GAIA. Link PRs to Asana tasks, update project status when code ships, and keep product and engineering aligned without manual status updates.",
    keywords: [
      "GitHub Asana integration",
      "GitHub Asana automation",
      "link PR to Asana task",
      "engineering project management sync",
      "GitHub Asana workflow",
    ],
    intro:
      "Product teams track work in Asana. Engineers write code in GitHub. Keeping the two aligned requires constant manual status updates that neither side has time for. GAIA automates the bridge, linking GitHub development activity to Asana project tasks so product and engineering always share the same understanding of progress.",
    useCases: [
      {
        title: "Update Asana task status from PR events",
        description:
          "When a PR referencing an Asana task is merged, GAIA moves the Asana task to 'Complete' automatically, eliminating the need for engineers to manually update project management tools.",
      },
      {
        title: "Development milestone notifications",
        description:
          "When a development milestone is reached in GitHub (feature branch merged, tests passing), GAIA notifies the Asana project owner so they can update product stakeholders.",
      },
      {
        title: "Bug fix tracking",
        description:
          "GitHub issues linked to Asana bug tasks update the Asana task status as the issue progresses from open to in-progress to closed, giving product teams real-time fix visibility.",
      },
      {
        title: "Sprint completion reports in Asana",
        description:
          "At sprint end, GAIA generates an Asana task summarizing completed GitHub PRs, outstanding issues, and code metrics, providing a development report attached to the project.",
      },
      {
        title: "Deployment confirmation tasks",
        description:
          "After a successful GitHub deployment, GAIA creates an Asana task for the QA team to verify the deployed features, linking deployment details and affected features.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Asana to GAIA",
        description:
          "Authorize GAIA with your GitHub organization and Asana workspace. Map repositories to Asana projects.",
      },
      {
        step: "Define the status mapping",
        description:
          "Configure which GitHub PR and issue events update which Asana task statuses. The mapping is flexible to match your team's specific workflow.",
      },
      {
        step: "Let GAIA maintain alignment",
        description:
          "GAIA monitors GitHub continuously and keeps Asana updated. Engineers focus on code, product teams trust their project board.",
      },
    ],
    faqs: [
      {
        question: "How does GAIA link a GitHub PR to an Asana task?",
        answer:
          "GAIA looks for Asana task URLs or IDs mentioned in PR descriptions and commit messages. You can also configure GAIA to match PRs to tasks by branch name patterns or labels.",
      },
      {
        question:
          "Can product managers see GitHub activity in Asana without GitHub access?",
        answer:
          "Yes. GAIA posts GitHub activity summaries as Asana task comments or subtasks so product managers get full development visibility without needing GitHub accounts.",
      },
      {
        question: "Does this work with Asana portfolios and goals?",
        answer:
          "GAIA can update Asana tasks that roll up to portfolios and goals. As tasks complete via GitHub events, portfolio progress updates automatically.",
      },
    ],
  },

  "notion-todoist": {
    slug: "notion-todoist",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Todoist",
    toolBSlug: "todoist",
    tagline: "Turn Notion pages into Todoist tasks and keep both in sync",
    metaTitle: "Notion + Todoist Automation - Plans to Action Items | GAIA",
    metaDescription:
      "Automate Notion and Todoist with GAIA. Convert Notion action items into Todoist tasks, sync project plans with task lists, and bridge your planning and execution tools.",
    keywords: [
      "Notion Todoist integration",
      "Notion to Todoist tasks",
      "Notion Todoist automation",
      "sync Notion and Todoist",
      "planning to task list automation",
    ],
    intro:
      "Notion is where plans live. Todoist is where tasks get done. The divide between planning documents and actionable to-do lists means action items get buried in Notion pages while your Todoist inbox doesn't reflect what your plans require. GAIA connects the two so plans translate automatically into tasks.",
    useCases: [
      {
        title: "Extract tasks from Notion project pages",
        description:
          "GAIA reads Notion project pages, identifies action items and checkbox items, and creates corresponding Todoist tasks with due dates pulled from any dates mentioned in the Notion content.",
      },
      {
        title: "Weekly review sync",
        description:
          "During weekly reviews in Notion, action items you capture in your review page automatically flow to Todoist as tasks for the coming week, closing the loop between reflection and execution.",
      },
      {
        title: "Meeting notes to tasks",
        description:
          "Action items captured in Notion meeting notes become Todoist tasks assigned to the right project, so next-step commitments from meetings don't live only in documents.",
      },
      {
        title: "Todoist completion synced to Notion",
        description:
          "When you complete a Todoist task, GAIA marks the corresponding Notion checkbox as checked, keeping your Notion project pages current with actual task completion status.",
      },
      {
        title: "Goal tracking across both tools",
        description:
          "Quarterly goals set in Notion generate Todoist tasks that break down each goal into actionable steps, ensuring your big-picture plans have concrete daily actions attached.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Todoist to GAIA",
        description:
          "Authorize GAIA with your Notion workspace (selecting the relevant pages/databases) and your Todoist account.",
      },
      {
        step: "Configure sync direction and frequency",
        description:
          "Choose whether sync flows one-way (Notion to Todoist), the other direction, or bidirectionally. Set how often GAIA should check for new items to sync.",
      },
      {
        step: "GAIA bridges planning and execution",
        description:
          "Plans in Notion translate to tasks in Todoist automatically. Completed tasks flow back to Notion. Your planning and execution systems become one coherent workflow.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync Notion database items (not just page content) to Todoist?",
        answer:
          "Yes. GAIA can read Notion databases and create Todoist tasks from database entries, mapping Notion database properties (like due date, assignee, priority) to Todoist task attributes.",
      },
      {
        question:
          "What happens if I edit a task in Todoist after GAIA synced it from Notion?",
        answer:
          "By default, Todoist edits don't overwrite the Notion source. GAIA treats Todoist as the execution layer and Notion as the planning layer. You can configure bidirectional sync if you want changes in either tool to update the other.",
      },
      {
        question: "Does GAIA handle Notion's checkbox blocks specifically?",
        answer:
          "Yes. GAIA recognizes Notion checkbox blocks as tasks and can toggle them when the corresponding Todoist task is completed, keeping your Notion pages accurate.",
      },
    ],
  },

  "notion-linear": {
    slug: "notion-linear",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline: "Bridge product specs in Notion with engineering issues in Linear",
    metaTitle:
      "Notion + Linear Automation - Specs to Engineering Issues | GAIA",
    metaDescription:
      "Automate Notion and Linear with GAIA. Convert product specs into Linear issues, link engineering work to Notion documentation, and keep product and engineering aligned.",
    keywords: [
      "Notion Linear integration",
      "Notion to Linear issues",
      "product spec to Linear",
      "Notion Linear automation",
      "product engineering alignment",
    ],
    intro:
      "Product teams write specs in Notion. Engineers build from Linear issues. The handoff between the two is often a lossy manual process where context gets dropped, scope shifts, and spec intent doesn't make it into the actual implementation. GAIA automates the spec-to-issue pipeline so engineering always works from current product intent.",
    useCases: [
      {
        title: "Convert Notion specs to Linear issues",
        description:
          "GAIA reads product requirement pages in Notion and generates a set of structured Linear issues covering each requirement, preserving context and linking back to the source spec.",
      },
      {
        title: "Spec change notifications to engineering",
        description:
          "When a Notion spec page is updated, GAIA detects the change and comments on related Linear issues to alert engineers that requirements have changed and linking to the updated section.",
      },
      {
        title: "Acceptance criteria in Linear from Notion",
        description:
          "GAIA extracts acceptance criteria defined in Notion spec pages and adds them to the description of corresponding Linear issues so engineers have clear completion criteria.",
      },
      {
        title: "Linear progress reflected in Notion",
        description:
          "GAIA updates Notion spec pages with current Linear issue status so product teams can see development progress in the tool they use without checking Linear.",
      },
      {
        title: "Sprint planning from product roadmap",
        description:
          "During sprint planning, GAIA reads the Notion product roadmap and creates a Linear sprint with issues pre-populated from the roadmap items scheduled for the sprint period.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Linear to GAIA",
        description:
          "Authorize GAIA with your Notion workspace and Linear account. Specify which Notion databases contain specs and which Linear teams and projects receive issues.",
      },
      {
        step: "Define the spec-to-issue mapping",
        description:
          "Tell GAIA how to interpret your Notion spec structure — which sections become issue titles, which become descriptions, and how to infer priority and labels from the spec content.",
      },
      {
        step: "Create issues and maintain sync",
        description:
          "GAIA creates the initial Linear issues from Notion specs and monitors for updates to either, keeping both sides aligned throughout the development cycle.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA handle Notion databases with multiple spec formats?",
        answer:
          "Yes. GAIA adapts to your Notion database structure. You describe how your specs are organized and GAIA learns to extract the right information from each page type.",
      },
      {
        question:
          "Can engineers update Linear issues without affecting Notion specs?",
        answer:
          "Linear updates only flow back to Notion where you configure them to (like updating a status field). Engineers can work freely in Linear without risking spec content changes.",
      },
      {
        question: "Does this work with Notion templates?",
        answer:
          "Yes. If your team uses a Notion spec template, GAIA can be configured to recognize the template structure and create consistent Linear issues from every spec that uses it.",
      },
    ],
  },

  "calendar-slack": {
    slug: "calendar-slack",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline: "Get calendar updates in Slack and manage meetings from chat",
    metaTitle:
      "Google Calendar + Slack Automation - Meeting Updates in Slack | GAIA",
    metaDescription:
      "Automate Google Calendar and Slack with GAIA. Get meeting reminders in Slack, share availability, set your Slack status from calendar events, and coordinate scheduling from chat.",
    keywords: [
      "Google Calendar Slack integration",
      "calendar Slack automation",
      "meeting reminder Slack",
      "Slack status from calendar",
      "calendar Slack bot",
    ],
    intro:
      "Your calendar and your team chat should work together, but they operate independently. Meetings start and nobody was reminded in Slack. Your status shows as Available while you're in back-to-back calls. Colleagues don't know when to reach you versus when you're heads-down. GAIA synchronizes Google Calendar with Slack so your team always has accurate context about your availability.",
    useCases: [
      {
        title: "Automatic Slack status from calendar",
        description:
          "GAIA sets your Slack status to 'In a meeting' with the meeting name during calendar events and clears it when the event ends, keeping your team informed without manual status updates.",
      },
      {
        title: "Meeting reminders in Slack",
        description:
          "GAIA sends Slack DMs five minutes before each meeting with the join link, agenda, and attendee list so you're always prepared and never scrambling for the video call link.",
      },
      {
        title: "Daily schedule digest",
        description:
          "GAIA posts your day's schedule to your personal Slack DM each morning so you can plan your focus time and know when you have back-to-back meetings coming.",
      },
      {
        title: "Meeting notes follow-up",
        description:
          "After a meeting ends, GAIA sends a Slack message prompting you to capture notes and action items while the context is fresh, with a quick link to your preferred note-taking app.",
      },
      {
        title: "Team availability sharing",
        description:
          "GAIA can post a team's combined availability from Google Calendar to a Slack channel so scheduling group meetings doesn't require round-robin calendar checking.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Slack to GAIA",
        description:
          "Authorize GAIA with your Google Calendar and Slack workspace. If managing team availability, each team member connects their own calendar.",
      },
      {
        step: "Configure status and notification rules",
        description:
          "Choose which calendar event types trigger Slack status changes, which reminders to receive, and what information to include in meeting prep notifications.",
      },
      {
        step: "GAIA manages calendar-Slack sync automatically",
        description:
          "From the moment you connect, GAIA keeps your Slack status accurate and your team informed about your availability without any ongoing manual effort.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA differentiate between important and routine meetings for Slack status?",
        answer:
          "Yes. You can configure which calendar event types trigger status changes. You might set 'Focus time' blocks to show as 'Do Not Disturb' while optional meetings don't change your status at all.",
      },
      {
        question:
          "Does GAIA share meeting details publicly in Slack or only in DMs?",
        answer:
          "By default, meeting details are sent only to your personal Slack DM. You can configure team availability sharing for specific channels, but individual meeting content stays private.",
      },
      {
        question: "Can GAIA help schedule meetings from Slack?",
        answer:
          "Yes. You can ask GAIA in Slack to find a time for a meeting with specific people, and it will check Google Calendar availability for all attendees and propose times.",
      },
    ],
  },

  "calendar-notion": {
    slug: "calendar-notion",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Sync calendar events to Notion and prep meetings automatically",
    metaTitle:
      "Google Calendar + Notion Automation - Meeting Prep in Notion | GAIA",
    metaDescription:
      "Automate Google Calendar and Notion with GAIA. Create Notion meeting notes from calendar events, sync your schedule to a Notion calendar, and prepare for meetings automatically.",
    keywords: [
      "Google Calendar Notion integration",
      "calendar Notion automation",
      "meeting notes Notion automation",
      "sync calendar to Notion",
      "meeting prep automation",
    ],
    intro:
      "Meeting preparation and notes capture are productivity fundamentals that most professionals do inconsistently. Notion is the ideal home for meeting notes and context, but creating notes pages for each meeting and populating them with attendee and agenda information is tedious enough to skip. GAIA automates the entire calendar-Notion pipeline from meeting prep to notes archiving.",
    useCases: [
      {
        title: "Auto-create Notion meeting notes pages",
        description:
          "GAIA creates a Notion page for each upcoming meeting, pre-populated with date, time, attendees, agenda from the calendar invite, and sections for notes and action items.",
      },
      {
        title: "Meeting context compilation",
        description:
          "Before each meeting, GAIA researches attendees, pulls related Notion pages, and adds context to the meeting notes page so you walk in prepared with relevant background.",
      },
      {
        title: "Calendar database in Notion",
        description:
          "GAIA maintains a Notion database of all your calendar events with properties like attendees, meeting type, and outcome, creating a searchable log of your meetings.",
      },
      {
        title: "Post-meeting action item capture",
        description:
          "After a meeting ends, GAIA prompts you to review the notes page and can extract action items to your task manager of choice, closing the gap between meetings and execution.",
      },
      {
        title: "Weekly planning from calendar",
        description:
          "GAIA reads your upcoming week's calendar and creates a weekly planning page in Notion with your schedule, prep notes for each meeting, and time blocked for focused work.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Notion to GAIA",
        description:
          "Authorize both accounts and specify which Notion section or database should receive meeting notes.",
      },
      {
        step: "Configure meeting note templates",
        description:
          "Choose which calendar event types get Notion pages, what the page template should look like, and which properties map from calendar to Notion fields.",
      },
      {
        step: "Review prep and capture notes",
        description:
          "Meeting notes pages appear in Notion automatically before each meeting. You add your notes during and after the meeting, and GAIA handles the administrative setup.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create meeting notes for all calendar events or only selected ones?",
        answer:
          "You can configure GAIA to create notes for all events, only events with attendees (excluding solo focus blocks), only events above a certain duration, or based on calendar tags. Full flexibility.",
      },
      {
        question:
          "Does GAIA update Notion when a calendar event is rescheduled?",
        answer:
          "Yes. When a calendar event time changes, GAIA updates the corresponding Notion page's date and time properties to stay accurate.",
      },
      {
        question:
          "Can multiple team members share the same Notion meeting notes?",
        answer:
          "Yes. GAIA can create shared meeting notes accessible to all attendees in a shared Notion workspace, ensuring everyone has the same notes page rather than fragmented individual copies.",
      },
    ],
  },

  "calendar-todoist": {
    slug: "calendar-todoist",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Todoist",
    toolBSlug: "todoist",
    tagline: "Turn calendar events into tasks and prep todos automatically",
    metaTitle:
      "Google Calendar + Todoist Automation - Schedule to Task List | GAIA",
    metaDescription:
      "Automate Google Calendar and Todoist with GAIA. Create Todoist prep tasks from calendar events, block calendar time for Todoist tasks, and keep your schedule and task list aligned.",
    keywords: [
      "Google Calendar Todoist integration",
      "calendar Todoist automation",
      "meeting prep tasks Todoist",
      "sync calendar and task list",
      "schedule to Todoist automation",
    ],
    intro:
      "Your calendar tells you when things happen. Your Todoist list tells you what to do. But the two rarely inform each other — meetings happen without prep tasks, Todoist deadlines exist without corresponding calendar blocks, and the result is a fragmented picture of your day. GAIA connects your calendar and Todoist so both reflect the same reality.",
    useCases: [
      {
        title: "Auto-create meeting prep tasks",
        description:
          "For every calendar event with external attendees, GAIA creates a Todoist task to review the agenda and prepare talking points, due the morning before the meeting.",
      },
      {
        title: "Deadline tasks from calendar events",
        description:
          "When a calendar event represents a deadline (project due dates, presentation dates), GAIA creates Todoist tasks working backwards from the deadline with intermediate milestones.",
      },
      {
        title: "Post-meeting follow-up tasks",
        description:
          "After meetings end, GAIA creates a Todoist task to capture and send meeting notes, due within an hour of the meeting conclusion so follow-through happens promptly.",
      },
      {
        title: "Time block creation in calendar for Todoist tasks",
        description:
          "When a Todoist task has a due date, GAIA can suggest or automatically create a Google Calendar time block for working on that task, ensuring you have scheduled time to complete it.",
      },
      {
        title: "Overloaded day warnings",
        description:
          "When GAIA sees a heavy meeting day in Calendar with many Todoist tasks also due that day, it alerts you in advance so you can reschedule tasks or meetings proactively.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Todoist to GAIA",
        description:
          "Authorize both accounts and configure the bidirectional sync preferences.",
      },
      {
        step: "Set prep task and time block rules",
        description:
          "Specify which meeting types generate prep tasks, how far in advance prep tasks should appear, and whether GAIA should create calendar blocks for important Todoist tasks.",
      },
      {
        step: "GAIA keeps schedule and tasks aligned",
        description:
          "New calendar events generate prep tasks automatically. New Todoist tasks with due dates can get calendar time blocked. The two systems work as one.",
      },
    ],
    faqs: [
      {
        question:
          "Will GAIA create prep tasks for every calendar event including internal syncs?",
        answer:
          "You control which event types generate prep tasks. You can exclude recurring internal syncs, personal events, and events without agendas. Only meaningful meetings that benefit from preparation get tasks.",
      },
      {
        question:
          "Can GAIA reschedule Todoist tasks if a meeting conflict appears in Calendar?",
        answer:
          "Yes. GAIA can detect when a new calendar event creates a conflict with time you had blocked for a Todoist task and suggest rescheduling the task or time block.",
      },
      {
        question: "Does this work with recurring calendar events?",
        answer:
          "Yes. GAIA creates prep tasks for each instance of recurring events individually, so your weekly 1-on-1 gets a fresh prep task each week rather than a single task for all occurrences.",
      },
    ],
  },

  "todoist-notion": {
    slug: "todoist-notion",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Sync Todoist tasks with Notion projects for full visibility",
    metaTitle: "Todoist + Notion Automation - Task and Project Sync | GAIA",
    metaDescription:
      "Automate Todoist and Notion with GAIA. Sync tasks between Todoist and Notion, capture completed tasks in your Notion journal, and keep your planning and execution tools connected.",
    keywords: [
      "Todoist Notion integration",
      "Todoist Notion sync",
      "sync tasks to Notion",
      "Todoist Notion automation",
      "task list to knowledge base",
    ],
    intro:
      "Todoist is optimized for capturing and completing tasks. Notion is optimized for organizing projects and knowledge. Used together with GAIA, they become a complete personal productivity system where task completion in Todoist feeds back into the project context in Notion.",
    useCases: [
      {
        title: "Daily task completion log in Notion",
        description:
          "GAIA compiles your completed Todoist tasks each day and appends them to your Notion daily journal, creating a searchable record of what you accomplished.",
      },
      {
        title: "Project task sync",
        description:
          "Todoist tasks linked to specific projects sync their completion status to the corresponding Notion project page, keeping project trackers accurate without manual updates.",
      },
      {
        title: "Weekly review automation",
        description:
          "GAIA compiles your Todoist weekly activity (completed, pending, overdue) and creates a weekly review Notion page populated with the data you need for your review session.",
      },
      {
        title: "Notion task creation to Todoist",
        description:
          "When you add a checkbox item to a Notion page, GAIA can add it to Todoist so it shows up in your active task list rather than being buried in a Notion document.",
      },
      {
        title: "Goal progress tracking",
        description:
          "Quarterly goals defined in Notion link to Todoist projects, and GAIA tracks task completion rates to report progress against goals automatically.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Notion to GAIA",
        description:
          "Authorize GAIA with your Todoist account and Notion workspace. Select which Notion databases and pages to sync with.",
      },
      {
        step: "Configure sync direction and triggers",
        description:
          "Choose whether completed tasks flow to Notion daily or in real time, and whether Notion checkboxes should create Todoist tasks. Start simple and add more rules as needed.",
      },
      {
        step: "Build your productivity archive",
        description:
          "Over time, GAIA builds a rich archive in Notion of your Todoist activity, creating a searchable record of everything you've accomplished and the projects it contributed to.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA handle Todoist projects and labels when syncing to Notion?",
        answer:
          "Yes. Todoist project names, labels, and priorities map to Notion database properties. A Todoist task in the 'Work' project with label 'Urgent' creates a Notion entry with those properties preserved.",
      },
      {
        question:
          "Does this create duplicates if I edit a task in both Todoist and Notion?",
        answer:
          "GAIA manages the sync so edits in Todoist are the source of truth for task status. Notion entries reflect the last Todoist state. If you configure bidirectional sync, GAIA resolves conflicts using the most recently modified version.",
      },
      {
        question: "Can I use this for team Todoist and Notion accounts?",
        answer:
          "Yes. GAIA supports Todoist Business and shared Notion workspaces, making this integration useful for teams that use both tools collaboratively.",
      },
    ],
  },

  "asana-notion": {
    slug: "asana-notion",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Connect Asana project management with Notion documentation",
    metaTitle: "Asana + Notion Automation - Projects and Knowledge Base | GAIA",
    metaDescription:
      "Automate Asana and Notion with GAIA. Sync Asana projects with Notion wikis, document project decisions, and keep your project management and knowledge base in sync.",
    keywords: [
      "Asana Notion integration",
      "Asana Notion automation",
      "sync Asana to Notion",
      "project management knowledge base",
      "Asana Notion workflow",
    ],
    intro:
      "Asana tracks the work. Notion holds the context. Most teams use them in isolation, leading to project documentation that doesn't reflect current task status and task lists that lack the strategic context needed to prioritize correctly. GAIA creates a live connection between them.",
    useCases: [
      {
        title: "Project briefs from Asana to Notion",
        description:
          "When a new Asana project is created, GAIA generates a corresponding Notion project brief page with goals, stakeholders, and timeline extracted from the Asana project description.",
      },
      {
        title: "Milestone documentation",
        description:
          "When Asana milestones are reached, GAIA creates Notion documentation entries capturing what was delivered, decisions made, and lessons learned.",
      },
      {
        title: "Asana task status in Notion",
        description:
          "Notion project pages show live Asana task completion percentages, giving stakeholders project health visibility in the tool they already use.",
      },
      {
        title: "Project retrospective generation",
        description:
          "At project completion, GAIA compiles Asana task history into a structured Notion retrospective template covering what went well, what didn't, and key learnings.",
      },
      {
        title: "Resource documentation sync",
        description:
          "Files and documents linked in Asana tasks are automatically referenced in the corresponding Notion project page, creating a unified resource hub.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Asana and Notion to GAIA",
        description:
          "Authorize GAIA with your Asana workspace and Notion account. Select which projects to sync.",
      },
      {
        step: "Map Asana projects to Notion sections",
        description:
          "Define which Notion section receives documentation for each Asana project or project type. GAIA handles all the content creation and updates.",
      },
      {
        step: "Maintain living project documentation",
        description:
          "As Asana project status evolves, Notion documentation stays current automatically. Your knowledge base reflects project reality without manual maintenance.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync Asana custom fields to Notion database properties?",
        answer:
          "Yes. Asana custom fields (like budget, client name, or phase) map to Notion database properties, preserving all project metadata in your knowledge base.",
      },
      {
        question: "Does GAIA work with Asana portfolios?",
        answer:
          "Yes. GAIA can create Notion pages for Asana portfolios that aggregate status across all included projects, giving leadership a portfolio-level view in Notion.",
      },
      {
        question: "Can Notion documents link back to the source Asana tasks?",
        answer:
          "Yes. GAIA includes the Asana task or project URL in every Notion entry it creates, so readers can navigate directly to the source for full task history.",
      },
    ],
  },

  "asana-github": {
    slug: "asana-github",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "GitHub",
    toolBSlug: "github",
    tagline: "Link Asana project tasks to GitHub development work",
    metaTitle: "Asana + GitHub Automation - Product Tasks to Code | GAIA",
    metaDescription:
      "Automate Asana and GitHub with GAIA. Link Asana tasks to GitHub PRs, update project status when code ships, and keep product and engineering aligned automatically.",
    keywords: [
      "Asana GitHub integration",
      "Asana GitHub automation",
      "link Asana to GitHub",
      "product engineering sync",
      "Asana GitHub workflow",
    ],
    intro:
      "Product work lives in Asana. Engineering work lives in GitHub. The handoff between them is where context gets lost and communication breaks down. GAIA automates the link between Asana tasks and GitHub development work so both tools stay accurate and both teams stay aligned.",
    useCases: [
      {
        title: "Link GitHub PRs to Asana tasks",
        description:
          "GAIA detects when a GitHub PR references an Asana task and creates a bidirectional link, so engineers see the product context in GitHub and product managers see code progress in Asana.",
      },
      {
        title: "Asana task completion from PR merge",
        description:
          "When a GitHub PR that implements an Asana task is merged, GAIA marks the task complete automatically, eliminating the need for engineers to update project management tools.",
      },
      {
        title: "Development progress in Asana",
        description:
          "Asana tasks linked to GitHub work show PR status (open, in review, merged) so product managers have real-time development visibility without asking engineers for updates.",
      },
      {
        title: "Bug task from GitHub issue",
        description:
          "High-priority GitHub issues automatically create corresponding Asana tasks in the QA or bug project, ensuring all reported bugs enter the product management workflow.",
      },
      {
        title: "Release coordination",
        description:
          "When a GitHub release is published, GAIA updates all linked Asana tasks to 'Released' and notifies stakeholders, closing the product delivery loop.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Asana and GitHub to GAIA",
        description:
          "Authorize GAIA with your Asana workspace and GitHub organization. Map repositories to Asana projects.",
      },
      {
        step: "Configure the linking convention",
        description:
          "Decide how PRs reference Asana tasks — by task URL in the PR description, by task ID in branch names, or by GAIA's intelligent matching based on content.",
      },
      {
        step: "Let GAIA maintain cross-tool accuracy",
        description:
          "Once configured, GAIA handles all status syncing automatically. Both teams work in their preferred tools while GAIA keeps them aligned.",
      },
    ],
    faqs: [
      {
        question:
          "How should engineers reference Asana tasks in their GitHub PRs?",
        answer:
          "GAIA supports several conventions: including the Asana task URL in the PR description, adding the task ID to the branch name, or using a specific PR description format you define. GAIA adapts to your existing workflow.",
      },
      {
        question: "Can product managers trigger GitHub actions from Asana?",
        answer:
          "Limited GitHub actions can be triggered from Asana via GAIA, such as creating an issue or requesting a review. Full repository access stays with engineers for security reasons.",
      },
      {
        question: "Does this work with Asana's approval tasks for QA sign-off?",
        answer:
          "Yes. GAIA can be configured to create an Asana approval task when a PR is merged, routing a QA sign-off step to the appropriate team member before marking the feature complete.",
      },
    ],
  },

  "linear-github": {
    slug: "linear-github",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "GitHub",
    toolBSlug: "github",
    tagline: "Keep Linear issues and GitHub PRs perfectly synchronized",
    metaTitle: "Linear + GitHub Automation - Issue and PR Sync | GAIA",
    metaDescription:
      "Automate Linear and GitHub with GAIA. Sync Linear issues with GitHub PRs automatically, update issue status from code events, and give your engineering team a unified workflow.",
    keywords: [
      "Linear GitHub integration",
      "Linear GitHub sync",
      "Linear GitHub automation",
      "issue PR sync",
      "engineering workflow automation",
    ],
    intro:
      "Linear and GitHub are the two tools engineering teams rely on most. Linear for planning and tracking, GitHub for writing and reviewing code. When they're not synchronized, the overhead of keeping both current undermines the efficiency gains each tool provides. GAIA makes them work as one unified engineering workflow.",
    useCases: [
      {
        title: "Bidirectional issue and PR sync",
        description:
          "Linear issues and GitHub PRs stay synchronized in both directions. PR events update Linear, and Linear status changes can reflect in GitHub labels, keeping both views current.",
      },
      {
        title: "Automated cycle tracking",
        description:
          "GAIA tracks each issue from Linear creation through GitHub PR open, review, merge, and deployment, giving engineering leads full cycle time data without manual tracking.",
      },
      {
        title: "Branch creation from Linear",
        description:
          "When a Linear issue moves to 'In Progress', GAIA can create the corresponding GitHub branch automatically with the correct naming convention, saving engineers the branch setup step.",
      },
      {
        title: "Review assignment from Linear metadata",
        description:
          "GAIA assigns GitHub PR reviewers based on Linear issue metadata — the team that owns the component, the reviewers listed in the Linear issue, or rotation rules.",
      },
      {
        title: "Deployment tracking",
        description:
          "GitHub deployment events trigger Linear issue status updates to 'Deployed', and GAIA notifies the issue creator and stakeholders that their work is live.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Linear and GitHub to GAIA",
        description:
          "Authorize GAIA with your Linear workspace and GitHub organization. Select which teams, projects, and repositories to synchronize.",
      },
      {
        step: "Configure sync rules and conventions",
        description:
          "Define your issue-PR linking convention, which Linear states correspond to which GitHub PR states, and any automation rules for review assignment or branch creation.",
      },
      {
        step: "Ship with confidence in both tools",
        description:
          "Engineers work in GitHub. Product and engineering leads view progress in Linear. GAIA keeps both accurate automatically.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA work with Linear's native GitHub integration?",
        answer:
          "GAIA complements Linear's native integration by adding intelligence it lacks — like smart review assignment, cycle time tracking, deployment notifications, and cross-team analytics.",
      },
      {
        question:
          "Can GAIA handle monorepos with many packages mapping to different Linear teams?",
        answer:
          "Yes. GAIA supports path-based routing in monorepos, mapping changes to different directories to different Linear teams so the right team sees activity relevant to their work.",
      },
      {
        question:
          "How does GAIA handle hotfix branches that skip normal workflow?",
        answer:
          "GAIA detects hotfix branches by naming convention and applies expedited status transitions in Linear, moving issues directly from the backlog to deployed status when a hotfix is merged.",
      },
    ],
  },

  "zoom-notion": {
    slug: "zoom-notion",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Transform Zoom meetings into searchable Notion documentation",
    metaTitle: "Zoom + Notion Automation - Meeting Notes in Notion | GAIA",
    metaDescription:
      "Automate Zoom and Notion with GAIA. Create Notion meeting notes from Zoom calls, save transcripts and action items, and build a searchable meeting archive automatically.",
    keywords: [
      "Zoom Notion integration",
      "Zoom meeting notes Notion",
      "Zoom Notion automation",
      "meeting transcript to Notion",
      "Zoom notes automation",
    ],
    intro:
      "Zoom calls generate valuable information — decisions, action items, insights, and commitments — that typically lives in someone's personal notes or disappears entirely. GAIA captures Zoom meeting intelligence and organizes it in Notion automatically, turning every call into a permanent, searchable knowledge asset.",
    useCases: [
      {
        title: "Automatic meeting notes pages",
        description:
          "After each Zoom call, GAIA creates a Notion page with meeting date, attendees, duration, and structured sections for key discussion points, decisions made, and action items.",
      },
      {
        title: "Action item extraction and task creation",
        description:
          "GAIA identifies commitments and action items from Zoom meeting context and creates tasks in Notion (or your connected task manager) with assigned owners and due dates.",
      },
      {
        title: "Meeting series documentation",
        description:
          "For recurring Zoom meetings like weekly standups or monthly reviews, GAIA maintains a running Notion page that appends each meeting's notes, creating a longitudinal record.",
      },
      {
        title: "Client call summaries",
        description:
          "After client Zoom calls, GAIA generates a professional summary in Notion that can be shared with the client or kept internally as a CRM-style call log.",
      },
      {
        title: "Team knowledge base from calls",
        description:
          "Insights, decisions, and tribal knowledge shared in Zoom calls get captured in the relevant Notion sections, preserving institutional knowledge that would otherwise be lost.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Notion to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Notion workspace. GAIA will monitor your Zoom meeting activity and create Notion content after each call.",
      },
      {
        step: "Configure note structure and destinations",
        description:
          "Choose your preferred Notion meeting notes template and which Notion section receives notes from different types of Zoom calls (team, client, one-on-one, etc.).",
      },
      {
        step: "Review and refine automatically generated notes",
        description:
          "GAIA creates a draft notes page after each call. You review, add any context, and the note becomes part of your permanent Notion knowledge base.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA require Zoom's cloud recording feature?",
        answer:
          "GAIA can work with calendar context and Zoom meeting metadata without recording. However, for richer notes including action item extraction, Zoom cloud recording with auto-transcription significantly improves accuracy.",
      },
      {
        question:
          "How does GAIA handle sensitive meetings that shouldn't be documented?",
        answer:
          "You can configure GAIA to exclude specific meeting types, meeting names containing certain keywords, or calendar events tagged as confidential from automatic documentation.",
      },
      {
        question:
          "Can notes be shared with Zoom meeting attendees automatically?",
        answer:
          "Yes. GAIA can be configured to share the Notion meeting notes page link with all attendees via email or Slack after the notes are created, keeping everyone aligned.",
      },
    ],
  },

  "zoom-todoist": {
    slug: "zoom-todoist",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Todoist",
    toolBSlug: "todoist",
    tagline:
      "Capture meeting action items in Todoist automatically after every Zoom call",
    metaTitle:
      "Zoom + Todoist Automation - Meeting Action Items as Tasks | GAIA",
    metaDescription:
      "Automate Zoom and Todoist with GAIA. Create Todoist tasks from Zoom meeting action items automatically, so follow-through from meetings happens without manual task entry.",
    keywords: [
      "Zoom Todoist integration",
      "Zoom action items Todoist",
      "meeting tasks automation",
      "Zoom Todoist workflow",
      "post-meeting task creation",
    ],
    intro:
      "Most action items from Zoom calls never make it into a task manager. People leave calls with good intentions, and then the next meeting starts. GAIA closes the gap between Zoom meeting commitments and Todoist execution so every follow-up and deliverable is captured and tracked.",
    useCases: [
      {
        title: "Post-meeting task creation",
        description:
          "After each Zoom call, GAIA creates Todoist tasks for each action item discussed, with task descriptions that preserve enough context to act on them without rewatching the recording.",
      },
      {
        title: "Pre-meeting prep tasks",
        description:
          "For scheduled Zoom calls, GAIA creates Todoist prep tasks the day before — reviewing agendas, preparing materials, and sending pre-read documents.",
      },
      {
        title: "Follow-up task scheduling",
        description:
          "When you commit to following up with a Zoom participant, GAIA creates a Todoist task with the person's name and context so the follow-up is captured before the call ends.",
      },
      {
        title: "Recurring meeting task generation",
        description:
          "For recurring Zoom meetings, GAIA generates a fresh set of prep and follow-up tasks for each instance, ensuring nothing is overlooked because it was 'same as last week'.",
      },
      {
        title: "Meeting objective tracking",
        description:
          "Meeting objectives set before a Zoom call that weren't completed get carried forward as Todoist tasks to the next instance, preventing important topics from falling through.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Todoist to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Todoist. GAIA monitors your Zoom meeting schedule via your connected calendar.",
      },
      {
        step: "Define task creation rules",
        description:
          "Configure which meeting types generate prep tasks, which project receives post-meeting tasks, and how tasks should be named and prioritized.",
      },
      {
        step: "Review tasks after each call",
        description:
          "After each meeting, GAIA creates tasks based on available meeting context. You review, edit if needed, and execute from Todoist without retracing steps.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA need to be in the Zoom call to capture action items?",
        answer:
          "GAIA can generate prep and follow-up tasks based on calendar context and meeting metadata without joining the call. For action item extraction, Zoom transcript access (via cloud recording) provides the most accurate results.",
      },
      {
        question:
          "Can GAIA assign Todoist tasks to different team members from the Zoom meeting?",
        answer:
          "Yes. If you use Todoist's team features, GAIA can assign tasks to team members based on who was in the Zoom call and who the action was assigned to.",
      },
      {
        question:
          "What if multiple people from my team are on the same Zoom call?",
        answer:
          "GAIA creates personalized task lists for each connected team member, so each person gets only the action items assigned to them from the shared call rather than a duplicate of all tasks.",
      },
    ],
  },

  "hubspot-gmail": {
    slug: "hubspot-gmail",
    toolA: "HubSpot",
    toolASlug: "hubspot",
    toolB: "Gmail",
    toolBSlug: "gmail",
    tagline: "Sync Gmail with HubSpot CRM and automate sales email workflows",
    metaTitle: "HubSpot + Gmail Automation - CRM and Email Sync | GAIA",
    metaDescription:
      "Automate HubSpot and Gmail with GAIA. Log Gmail emails to HubSpot contacts automatically, draft personalized outreach from CRM data, and keep your sales pipeline up to date from your inbox.",
    keywords: [
      "HubSpot Gmail integration",
      "HubSpot Gmail automation",
      "log email to HubSpot",
      "CRM email sync",
      "sales email automation",
    ],
    intro:
      "Sales teams live in Gmail but are accountable in HubSpot. Manually logging emails to contact records, updating deal stages after email exchanges, and crafting personalized outreach from CRM data takes hours that should be spent selling. GAIA automates the HubSpot-Gmail connection so your CRM reflects reality and your outreach is informed by full contact context.",
    useCases: [
      {
        title: "Auto-log emails to HubSpot contacts",
        description:
          "Every Gmail email from or to a HubSpot contact gets automatically logged to their contact record with sender, subject, date, and a summary, keeping the CRM current without manual data entry.",
      },
      {
        title: "Deal stage updates from email signals",
        description:
          "GAIA reads email content and updates HubSpot deal stages based on signals — a positive reply advances a deal to 'Proposal Sent', a rejection triggers a 'Closed Lost' update.",
      },
      {
        title: "Personalized outreach from HubSpot data",
        description:
          "GAIA drafts Gmail outreach emails using HubSpot contact data — company, role, last interaction, and deal history — so every email is personalized without manual CRM research.",
      },
      {
        title: "Follow-up sequence triggers",
        description:
          "When a contact doesn't reply within a set period, GAIA drafts a follow-up email in Gmail using HubSpot contact context, queued for your review before sending.",
      },
      {
        title: "New contact creation from email",
        description:
          "When you receive an email from someone not in HubSpot, GAIA creates a contact record with information extracted from the email signature and domain, ready for you to qualify.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Gmail to GAIA",
        description:
          "Authorize GAIA with your HubSpot account and Gmail. GAIA will match Gmail contacts against HubSpot records automatically.",
      },
      {
        step: "Configure logging and deal rules",
        description:
          "Set which emails should be logged to HubSpot, which email signals should trigger deal stage changes, and how you want outreach drafts structured.",
      },
      {
        step: "Sell with full CRM context",
        description:
          "GAIA keeps HubSpot current from your Gmail activity and brings CRM context into your email drafting, making your inbox a CRM-aware sales tool.",
      },
    ],
    faqs: [
      {
        question:
          "Will GAIA log every Gmail email to HubSpot or only emails to known contacts?",
        answer:
          "By default GAIA only logs emails to and from existing HubSpot contacts. You can configure it to also log emails from unrecognized contacts to a review queue for manual qualification.",
      },
      {
        question:
          "Can GAIA handle HubSpot sequences alongside manual Gmail outreach?",
        answer:
          "Yes. GAIA is aware of active HubSpot sequences and won't duplicate outreach. It can also suspend sequences when a contact replies, ensuring you don't send automated follow-ups after a personal conversation.",
      },
      {
        question: "Does GAIA work with HubSpot's native Gmail extension?",
        answer:
          "GAIA provides more automated intelligence than the native HubSpot Gmail extension. They can coexist, but GAIA handles the automated logging and drafting so you may find the native extension redundant.",
      },
    ],
  },

  "hubspot-slack": {
    slug: "hubspot-slack",
    toolA: "HubSpot",
    toolASlug: "hubspot",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline: "Get HubSpot deal alerts in Slack and update CRM from chat",
    metaTitle: "HubSpot + Slack Automation - CRM Alerts in Slack | GAIA",
    metaDescription:
      "Automate HubSpot and Slack with GAIA. Get deal stage alerts in Slack, notify sales teams of new leads, and update HubSpot from Slack without switching apps.",
    keywords: [
      "HubSpot Slack integration",
      "HubSpot Slack automation",
      "deal alerts Slack",
      "CRM Slack notifications",
      "sales team Slack alerts",
    ],
    intro:
      "Sales teams collaborate in Slack but their data lives in HubSpot. Important deal updates sit in HubSpot where the team doesn't see them, and Slack discussions about deals don't update the CRM. GAIA connects HubSpot and Slack so deal intelligence flows to where the team is working and CRM updates happen from conversations.",
    useCases: [
      {
        title: "New lead alerts in Slack",
        description:
          "When a new lead enters HubSpot, GAIA posts a structured notification to the sales Slack channel with company, contact name, source, and lead score so reps can prioritize quickly.",
      },
      {
        title: "Deal stage change notifications",
        description:
          "Every significant deal stage change in HubSpot triggers a Slack notification to the relevant sales channel or account owner, keeping the team informed on pipeline movement.",
      },
      {
        title: "Closed won celebrations",
        description:
          "When a deal is marked Closed Won in HubSpot, GAIA posts a celebration to the team Slack channel with deal value and the winning rep's name, recognizing the win publicly.",
      },
      {
        title: "Update HubSpot from Slack",
        description:
          "Sales reps can ask GAIA in Slack to log a call, update a deal stage, or add a note to a contact record without switching to HubSpot, reducing the CRM data entry friction.",
      },
      {
        title: "Daily sales pipeline digest",
        description:
          "GAIA posts a morning sales pipeline summary to the leadership Slack channel with deals closing this week, new leads this week, and pipeline by stage.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Slack to GAIA",
        description:
          "Authorize GAIA with your HubSpot portal and Slack workspace. Configure which Slack channels receive which HubSpot notifications.",
      },
      {
        step: "Configure deal and lead rules",
        description:
          "Set notification thresholds — which deal values trigger channel-wide alerts, which stage changes notify the rep only, and what the daily digest includes.",
      },
      {
        step: "Keep your team selling",
        description:
          "GAIA handles the information flow so your team spends less time checking HubSpot and more time on customer conversations.",
      },
    ],
    faqs: [
      {
        question:
          "Can individual sales reps configure their own HubSpot alerts in Slack?",
        answer:
          "Yes. Each rep can configure personal alert preferences for their own deals and contacts in addition to the team-wide notifications configured by the sales manager.",
      },
      {
        question:
          "How detailed are the HubSpot updates GAIA can make from Slack?",
        answer:
          "GAIA can update deal stage, deal value, close date, add notes, log calls and meetings, update contact properties, and add tasks from Slack. Most common CRM updates are supported without opening HubSpot.",
      },
      {
        question:
          "Can GAIA post to different Slack channels for different deal sizes or territories?",
        answer:
          "Yes. You can configure routing rules so enterprise deals notify the enterprise sales channel, SMB deals notify the SMB channel, and deal alerts route by geography or product line.",
      },
    ],
  },

  "gmail-google-calendar": {
    slug: "gmail-google-calendar",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Turn meeting emails into calendar events and prep tasks automatically",
    metaTitle: "Gmail + Google Calendar Automation - Email to Events | GAIA",
    metaDescription:
      "Automate Gmail and Google Calendar with GAIA. Create calendar events from emails, get meeting prep delivered to your inbox, and keep your schedule and email in sync effortlessly.",
    keywords: [
      "Gmail Google Calendar integration",
      "email to calendar event",
      "Gmail calendar automation",
      "schedule meeting from email",
      "Google Calendar Gmail workflow",
      "inbox to calendar sync",
    ],
    intro:
      "Meeting requests, event invitations, and scheduling threads arrive in Gmail every day, but converting them into calendar events requires manual copy-pasting that breaks your flow. Meanwhile, your calendar holds context that should be informing your email responses — yet Gmail has no idea what your schedule looks like.\n\nGAIA bridges Gmail and Google Calendar so information flows naturally between them. Scheduling emails automatically become draft calendar events. Meeting invitations trigger prep emails with agendas and attendee context. Confirmed events generate follow-up tasks in your inbox. The two tools work as a unified scheduling and communication system.\n\nThis integration is particularly powerful for anyone who manages a high volume of external meetings, coordinates schedules across time zones, or wants to spend less time manually transferring information between their inbox and calendar.",
    useCases: [
      {
        title: "Create calendar events from scheduling emails",
        description:
          "When a scheduling email arrives proposing a meeting time, GAIA creates a draft calendar event with the proposed details so you can confirm with one click rather than manually entering all the information.",
      },
      {
        title: "Meeting prep delivered to your inbox",
        description:
          "The morning of each calendar event, GAIA sends a Gmail summary with the agenda, attendee LinkedIn profiles, relevant email history with those attendees, and any prep notes, so you walk into every meeting informed.",
      },
      {
        title: "Auto-detect and create events from confirmation emails",
        description:
          "Flight confirmations, hotel reservations, restaurant bookings, and event ticket emails automatically create corresponding Google Calendar entries with all the relevant details extracted.",
      },
      {
        title: "Follow-up email drafts after meetings",
        description:
          "When a calendar event ends, GAIA drafts a follow-up email to the attendees summarizing key points and next steps, ready for your review in Gmail Draft so you can send while context is fresh.",
      },
      {
        title: "Availability responses from calendar",
        description:
          "When someone emails asking for your availability, GAIA checks Google Calendar and drafts a reply in Gmail with your open slots formatted cleanly so scheduling doesn't require back-and-forth.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Google Calendar to GAIA",
        description:
          "Authorize GAIA with your Gmail and Google Calendar using OAuth. Both use your existing Google account so setup takes under two minutes.",
      },
      {
        step: "Configure event and email rules",
        description:
          "Tell GAIA which types of emails should become calendar events, which event types should trigger prep emails, and how follow-up drafts should be structured.",
      },
      {
        step: "GAIA keeps email and calendar in sync",
        description:
          "From the moment you connect, GAIA monitors both Gmail and Calendar and keeps them informed about each other. You focus on the conversations and meetings, not the administrative transfer of information.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA distinguish scheduling emails from other emails automatically?",
        answer:
          "Yes. GAIA uses AI to detect scheduling intent in emails — phrases like 'let's meet', 'are you free', 'I'd like to schedule', and attached .ics files all trigger the calendar workflow. You can also manually invoke it for any email.",
      },
      {
        question: "Will GAIA create events without my confirmation?",
        answer:
          "By default GAIA creates draft events that you confirm before they appear on your calendar. You can configure it to auto-create events for specific trusted senders or email patterns where manual review isn't needed.",
      },
      {
        question: "Does this work with Google Workspace accounts?",
        answer:
          "Yes. GAIA works with personal Gmail and Google Workspace accounts. For Workspace accounts, the integration respects your organization's sharing and access settings.",
      },
    ],
  },

  "gmail-clickup": {
    slug: "gmail-clickup",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline: "Convert emails into ClickUp tasks without leaving your inbox",
    metaTitle: "Gmail + ClickUp Automation - Email to Tasks | GAIA",
    metaDescription:
      "Automate Gmail and ClickUp with GAIA. Create ClickUp tasks from emails, assign them to the right team members, set due dates from email context, and manage all your work in one place.",
    keywords: [
      "Gmail ClickUp integration",
      "email to ClickUp task",
      "Gmail ClickUp automation",
      "create ClickUp task from email",
      "inbox to project management",
      "ClickUp email workflow",
    ],
    intro:
      "Your inbox is a constant source of work requests, but Gmail and ClickUp operate in separate worlds. Action items buried in email threads never make it to ClickUp, and tasks created in ClickUp lack the email context that explains why they exist. The result is duplicated work, missed tasks, and a project board that doesn't reflect your actual workload.\n\nGAIA connects Gmail and ClickUp so emails flow directly into your project management system. Client requests become ClickUp tasks with proper context. Team emails generate subtasks with assignments. Deadlines mentioned in emails set ClickUp due dates automatically.\n\nThe integration is especially useful for agencies, consultancies, and client-facing teams who receive work through email but manage execution in ClickUp.",
    useCases: [
      {
        title: "Client request emails to ClickUp tasks",
        description:
          "When a client emails with a request or change, GAIA creates a ClickUp task in the relevant list with the client's request as the task description, the sender as a custom field, and any deadline mentioned as the due date.",
      },
      {
        title: "Email-triggered subtask creation",
        description:
          "When a complex project update arrives in email with multiple action items, GAIA creates a parent ClickUp task and individual subtasks for each action item, complete with suggested assignees.",
      },
      {
        title: "Auto-tag tasks from email labels",
        description:
          "Gmail labels on incoming emails map to ClickUp tags on created tasks, so your email organization system automatically categorizes ClickUp work without extra tagging effort.",
      },
      {
        title: "Task completion replies to email senders",
        description:
          "When a ClickUp task created from an email is marked complete, GAIA drafts a completion reply to the original email sender so they're notified without extra manual communication.",
      },
      {
        title: "Vendor and supplier request tracking",
        description:
          "Emails from vendors requesting approvals, information, or signatures create ClickUp tasks in a dedicated vendor list with deadlines so vendor management doesn't get buried in the inbox.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and ClickUp to GAIA",
        description:
          "Authorize GAIA with your Gmail account and ClickUp workspace. Select which ClickUp spaces and lists should receive email-generated tasks.",
      },
      {
        step: "Define task routing rules",
        description:
          "Configure which emails create ClickUp tasks — by sender, Gmail label, keywords, or AI classification. Set default list, assignee, and priority for each rule.",
      },
      {
        step: "GAIA manages the email-to-task pipeline",
        description:
          "Incoming emails matching your rules automatically generate ClickUp tasks. You review the task list in ClickUp and execute without needing to revisit the email thread for context.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA include the full email body in the ClickUp task description?",
        answer:
          "Yes. GAIA can include the full email body, a GAIA-generated summary, or key extracted details in the ClickUp task description. For long email threads, a summary is usually more actionable than the raw thread.",
      },
      {
        question:
          "Does GAIA support ClickUp custom fields when creating tasks from email?",
        answer:
          "Yes. You can map email metadata (sender name, domain, label) to ClickUp custom fields. This is useful for tracking client name, request type, or email source on each task.",
      },
      {
        question:
          "Can GAIA handle replies in an email thread and update the existing ClickUp task?",
        answer:
          "Yes. When a reply arrives on an email thread that already has a ClickUp task, GAIA can add the new information as a comment on the existing task rather than creating a duplicate.",
      },
    ],
  },

  "gmail-jira": {
    slug: "gmail-jira",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Jira",
    toolBSlug: "jira",
    tagline:
      "Create Jira issues from emails and close the customer-engineering loop",
    metaTitle: "Gmail + Jira Automation - Email to Jira Issues | GAIA",
    metaDescription:
      "Automate Gmail and Jira with GAIA. Convert customer emails into Jira issues, notify customers when issues resolve, and keep your support and engineering teams aligned automatically.",
    keywords: [
      "Gmail Jira integration",
      "email to Jira issue",
      "Gmail Jira automation",
      "customer email Jira ticket",
      "support email to Jira",
      "Jira Gmail workflow",
    ],
    intro:
      "Support teams receive bug reports and feature requests over email. Engineering teams track them in Jira. The handoff between the two is often manual, slow, and lossy — context gets dropped, duplicates get created, and customers wait longer than necessary.\n\nGAIA automates the Gmail-to-Jira pipeline. Customer emails become properly formatted Jira issues with the right project assignment, priority, and labels. When a Jira issue is resolved, GAIA drafts the customer reply in Gmail. The entire support-to-engineering loop runs automatically.\n\nThis integration serves support teams, customer success managers, and technical account managers who receive client issues by email but need them tracked in Jira for engineering visibility.",
    useCases: [
      {
        title: "Bug report emails to Jira issues",
        description:
          "GAIA reads customer bug report emails, extracts relevant technical details and reproduction steps, and creates a formatted Jira issue with appropriate priority, labels, and project assignment.",
      },
      {
        title: "Duplicate issue detection",
        description:
          "Before creating a new Jira issue, GAIA checks for semantically similar existing issues and links the email to the existing issue rather than creating a duplicate, reducing engineering noise.",
      },
      {
        title: "Customer notification on resolution",
        description:
          "When a Jira issue moves to 'Done', GAIA drafts a personalized resolution email in Gmail to the original reporter explaining what was fixed and when the fix will be available.",
      },
      {
        title: "SLA breach escalation",
        description:
          "Customer emails that have not received a Jira response within your SLA threshold trigger a Slack or email escalation alert so high-priority customer issues never slip through.",
      },
      {
        title: "Feature request backlog from email",
        description:
          "Feature requests in customer emails create Jira backlog items with the customer's verbatim language attached so product teams have authentic user voice on every feature request.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Jira to GAIA",
        description:
          "Authorize GAIA with your Gmail account and Jira project. Specify which Jira project and issue types should receive email-generated tickets.",
      },
      {
        step: "Set issue creation and routing rules",
        description:
          "Define which emails should create Jira issues — by sender domain, Gmail label, or AI detection of bug/feature language. Configure priority mapping from email urgency to Jira priority.",
      },
      {
        step: "Enable bidirectional status flow",
        description:
          "Configure GAIA to draft Gmail replies when Jira issues reach key statuses, closing the communication loop with customers automatically.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA link Jira issues back to the original Gmail thread?",
        answer:
          "Yes. GAIA includes the Gmail thread URL in the Jira issue description so engineers always have one-click access to the original customer communication for full context.",
      },
      {
        question:
          "Does GAIA work with Jira Service Management as well as Jira Software?",
        answer:
          "GAIA works with both. For Jira Service Management, it can create service requests rather than issues, respecting your support queue configuration and SLA rules.",
      },
      {
        question:
          "Can I use Gmail labels to route emails to different Jira projects?",
        answer:
          "Yes. You can map Gmail labels to Jira projects so emails labeled 'Mobile Bug' go to the mobile Jira project and emails labeled 'Web Bug' go to the web project automatically.",
      },
    ],
  },

  "slack-jira": {
    slug: "slack-jira",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Jira",
    toolBSlug: "jira",
    tagline: "Create and track Jira issues directly from Slack conversations",
    metaTitle: "Slack + Jira Automation - Manage Issues from Chat | GAIA",
    metaDescription:
      "Automate Slack and Jira with GAIA. Create Jira issues from Slack messages, get issue updates in Slack, and keep your engineering and support teams aligned without leaving chat.",
    keywords: [
      "Slack Jira integration",
      "create Jira issue from Slack",
      "Slack Jira automation",
      "Jira Slack notifications",
      "Slack Jira bot",
      "engineering Slack Jira workflow",
    ],
    intro:
      "Engineering teams report bugs and discuss incidents in Slack, but track them in Jira. The gap between these two tools means important issues get reported in Slack but never logged in Jira, and Jira updates don't reach the team where they're already collaborating.\n\nGAIA makes Slack a full-featured Jira interface. Team members create issues from messages with an emoji reaction. Status updates flow back into the right Slack channels. Engineers can query and update Jira without leaving the conversation. The result is a tighter feedback loop between what the team discovers and what gets tracked.",
    useCases: [
      {
        title: "Create Jira issues from Slack messages",
        description:
          "React to any Slack message with a designated emoji or GAIA command and the message becomes a Jira issue instantly. GAIA formats the content, assigns the right project, and posts the issue link back into Slack.",
      },
      {
        title: "Incident management from Slack",
        description:
          "When an incident is discussed in a Slack channel, GAIA creates a tracking Jira issue, sets priority based on severity language in the conversation, and links the issue to the Slack thread for shared context.",
      },
      {
        title: "Jira status updates to Slack",
        description:
          "Issue transitions in Jira post real-time updates to designated Slack channels so the team knows when bugs are assigned, in progress, or resolved without checking Jira manually.",
      },
      {
        title: "Query Jira from Slack",
        description:
          "Ask GAIA in Slack for the status of specific issues, sprint progress, or open bugs in a project. GAIA queries Jira and returns a formatted summary so the team gets answers without switching apps.",
      },
      {
        title: "On-call alert to Jira issue",
        description:
          "When an on-call alert fires in Slack, GAIA creates a Jira incident issue automatically with the alert details, assigns it to the on-call engineer, and starts tracking time to resolution.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Jira to GAIA",
        description:
          "Add GAIA to your Slack workspace and authorize your Jira account. Configure which Slack channels correspond to which Jira projects.",
      },
      {
        step: "Configure issue creation and notification rules",
        description:
          "Choose your issue creation triggers (emoji, command, or keyword detection) and specify which Jira status transitions should notify which Slack channels.",
      },
      {
        step: "Work in Slack, track in Jira automatically",
        description:
          "Team members interact with Jira from Slack while GAIA keeps both systems synchronized. Engineering context stays in Jira while team communication stays in Slack.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA update Jira issue fields from Slack without opening Jira?",
        answer:
          "Yes. You can ask GAIA in Slack to change assignee, update priority, add a comment, change status, or set a due date on any Jira issue. GAIA confirms each update in the Slack thread.",
      },
      {
        question: "Does GAIA work with Jira's sprint and board structure?",
        answer:
          "Yes. GAIA can create issues in specific sprints, move issues between sprints, and report on sprint progress from Slack. You can also ask GAIA to show what's in the current sprint for any project.",
      },
      {
        question:
          "Can GAIA handle Jira notifications without creating too much Slack noise?",
        answer:
          "GAIA applies intelligent filtering. You configure exactly which Jira events notify which channels. Most teams start with just high-priority status changes and add more events as needed.",
      },
    ],
  },

  "slack-clickup": {
    slug: "slack-clickup",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline: "Manage ClickUp tasks and get updates directly inside Slack",
    metaTitle: "Slack + ClickUp Automation - Task Management from Slack | GAIA",
    metaDescription:
      "Automate Slack and ClickUp with GAIA. Create ClickUp tasks from Slack messages, receive task updates in Slack, and manage your project work without switching between apps.",
    keywords: [
      "Slack ClickUp integration",
      "create ClickUp task from Slack",
      "Slack ClickUp automation",
      "ClickUp Slack notifications",
      "project management Slack bot",
      "ClickUp Slack workflow",
    ],
    intro:
      "Teams coordinate in Slack but their work lives in ClickUp. Decisions made in Slack channels don't always make it to ClickUp tasks, and ClickUp progress updates don't reach the team in Slack. GAIA creates a seamless bridge so your team's communication and task management work together.\n\nWith GAIA, any Slack message can become a ClickUp task in seconds. ClickUp task completions celebrate in Slack. Overdue tasks alert the right people in chat. Your team spends less time switching between tools and more time doing actual work.",
    useCases: [
      {
        title: "Create tasks from Slack with emoji reactions",
        description:
          "React to any Slack message with a task emoji and GAIA instantly creates a ClickUp task from the message content, posted in the configured list with the message context preserved.",
      },
      {
        title: "ClickUp task update notifications in Slack",
        description:
          "When ClickUp tasks change status, are completed, or become overdue, GAIA posts intelligent updates to the relevant Slack channel so the team stays informed without checking ClickUp.",
      },
      {
        title: "Daily ClickUp digest in Slack",
        description:
          "GAIA posts a morning digest to each team member's Slack DM summarizing their ClickUp tasks due today and any overdue items, making prioritization effortless.",
      },
      {
        title: "Sprint summary posts",
        description:
          "At the end of each ClickUp sprint, GAIA posts a summary to the team Slack channel showing completed tasks, incomplete items carried over, and velocity metrics.",
      },
      {
        title: "Blocker escalations",
        description:
          "When a ClickUp task is marked as blocked, GAIA sends a Slack alert to the task owner and project manager so blockers get addressed immediately rather than sitting unnoticed in the task board.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and ClickUp to GAIA",
        description:
          "Add GAIA to your Slack workspace and authorize your ClickUp account. Map Slack channels to ClickUp lists and spaces.",
      },
      {
        step: "Set up task creation and notification preferences",
        description:
          "Configure your preferred task creation method and which ClickUp events should generate Slack notifications. Start with task completion and blocker alerts.",
      },
      {
        step: "GAIA bridges chat and task management",
        description:
          "From the moment you connect, GAIA routes Slack action items to ClickUp and ClickUp updates back to Slack, keeping both in sync automatically.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA create ClickUp tasks with subtasks from Slack?",
        answer:
          "Yes. If you describe a task with multiple components in Slack, GAIA can create a parent task with subtasks. You can also ask GAIA to add subtasks to an existing ClickUp task from Slack.",
      },
      {
        question:
          "Does GAIA support ClickUp's custom statuses when posting Slack updates?",
        answer:
          "Yes. GAIA reads your ClickUp custom statuses and uses them in Slack notifications so updates reflect your actual workflow stages rather than generic status names.",
      },
      {
        question:
          "Can I control which ClickUp lists generate Slack notifications?",
        answer:
          "Yes. You can enable notifications for specific lists, folders, or spaces and mute others. This prevents notifications from low-priority lists cluttering your team Slack channels.",
      },
    ],
  },

  "notion-google-calendar": {
    slug: "notion-google-calendar",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Sync Notion project dates and deadlines with Google Calendar automatically",
    metaTitle:
      "Notion + Google Calendar Automation - Deadlines to Calendar | GAIA",
    metaDescription:
      "Automate Notion and Google Calendar with GAIA. Sync Notion database dates to Google Calendar events, create calendar blocks for Notion tasks, and keep your schedule and projects aligned.",
    keywords: [
      "Notion Google Calendar integration",
      "Notion calendar sync",
      "sync Notion to Google Calendar",
      "Notion deadlines calendar",
      "project planning calendar automation",
      "Notion calendar workflow",
    ],
    intro:
      "Notion is where projects, tasks, and content plans live — complete with due dates and scheduling properties. But those dates stay inside Notion, invisible to your Google Calendar and disconnected from how you actually manage your time. GAIA bridges this gap so the timelines you set in Notion automatically appear on your calendar.\n\nProject milestones in your Notion database become Google Calendar events. Content publication dates become deadline reminders. Meeting notes in Notion connect to the calendar events that generated them. Planning in Notion and scheduling in Google Calendar become one unified workflow.\n\nThis integration is especially valuable for content creators, project managers, and product teams who plan extensively in Notion but need their schedules visible in calendar form.",
    useCases: [
      {
        title: "Sync Notion project dates to Google Calendar",
        description:
          "Dates in your Notion project database automatically create Google Calendar events so project milestones, launch dates, and deadlines appear on your calendar without manual entry.",
      },
      {
        title: "Content calendar integration",
        description:
          "Notion content calendar entries with publication dates sync to Google Calendar, giving your team a unified view of the content schedule alongside other meetings and commitments.",
      },
      {
        title: "Calendar time blocks for Notion tasks",
        description:
          "GAIA creates Google Calendar focus blocks for Notion tasks with due dates, ensuring you have dedicated calendar time to complete what your Notion task list requires.",
      },
      {
        title: "Notion meeting notes linked to calendar events",
        description:
          "GAIA connects Notion meeting notes pages to their corresponding Google Calendar events bidirectionally, so clicking a calendar event links directly to the Notion notes page.",
      },
      {
        title: "Deadline reminders from Notion databases",
        description:
          "As deadlines approach for items in your Notion database, GAIA creates Google Calendar reminders so critical dates surface in the tool you check for your schedule.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Google Calendar to GAIA",
        description:
          "Authorize GAIA with your Notion workspace (selecting specific databases) and Google Calendar account. Configure which Notion date properties should sync to Calendar.",
      },
      {
        step: "Map Notion databases to calendar rules",
        description:
          "Tell GAIA which Notion databases contain schedulable dates, what event titles to use, and which Google Calendar to add events to. Different databases can map to different calendars.",
      },
      {
        step: "Plan in Notion, see everything in Calendar",
        description:
          "GAIA monitors Notion database changes and keeps Google Calendar updated. Add or change dates in Notion and calendar events update automatically within minutes.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync bidirectionally — calendar events back into Notion?",
        answer:
          "Yes. GAIA can create Notion database entries from Google Calendar events you add, so new meetings appear in your Notion project database automatically with calendar event details as properties.",
      },
      {
        question:
          "Does GAIA handle Notion date ranges (start and end dates) in calendar events?",
        answer:
          "Yes. Notion date properties with start and end dates create multi-day Google Calendar events with the correct duration. Single date properties create all-day events or events with a default duration you configure.",
      },
      {
        question:
          "Can multiple Notion databases sync to the same Google Calendar?",
        answer:
          "Yes. You can sync multiple Notion databases to a single calendar, or map each database to a separate calendar. Having separate calendars per project type is useful for toggling visibility.",
      },
    ],
  },

  "notion-asana": {
    slug: "notion-asana",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline: "Turn Notion project plans into Asana tasks and keep both in sync",
    metaTitle:
      "Notion + Asana Automation - Planning to Project Execution | GAIA",
    metaDescription:
      "Automate Notion and Asana with GAIA. Convert Notion project plans into Asana tasks, sync status updates back to Notion, and bridge your documentation and project management tools.",
    keywords: [
      "Notion Asana integration",
      "Notion to Asana tasks",
      "Notion Asana automation",
      "sync Notion Asana",
      "project planning to Asana",
      "Notion Asana workflow",
    ],
    intro:
      "Notion is where teams document strategies, write project briefs, and maintain knowledge. Asana is where execution happens. The problem is these two tools rarely talk to each other — plans live in Notion while tasks live in Asana, and neither reflects the full picture.\n\nGAIA connects Notion planning with Asana execution. Project briefs written in Notion generate Asana projects with tasks. Asana task completion rates flow back to Notion project pages. Decisions made in Notion documents create Asana action items automatically. The gap between planning and doing closes.\n\nTeams using both Notion and Asana — particularly agencies, product teams, and marketing departments — get the strategic depth of Notion and the execution discipline of Asana without manual synchronization.",
    useCases: [
      {
        title: "Project brief to Asana tasks",
        description:
          "When a project brief in Notion is finalized, GAIA reads the requirements and deliverables sections and creates a corresponding Asana project with tasks, due dates, and suggested assignees.",
      },
      {
        title: "Notion action items to Asana",
        description:
          "Meeting notes and decision documents in Notion that contain action items automatically generate Asana tasks assigned to the right team members with due dates from the Notion content.",
      },
      {
        title: "Asana progress reflected in Notion",
        description:
          "GAIA updates Notion project pages with live Asana completion percentages and task status so stakeholders reading the Notion brief see current execution status without switching tools.",
      },
      {
        title: "Content calendar to Asana production tasks",
        description:
          "Notion content calendar entries generate Asana production tasks for each piece of content — writing, editing, design, and publishing — with deadlines working backward from the publish date.",
      },
      {
        title: "Retrospective data from Asana to Notion",
        description:
          "After project completion, GAIA pulls Asana task history and populates a Notion retrospective template with completion rates, timeline accuracy, and team velocity data.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Asana to GAIA",
        description:
          "Authorize GAIA with your Notion workspace and Asana account. Select which Notion databases and pages GAIA should monitor and which Asana workspace to create tasks in.",
      },
      {
        step: "Define the plan-to-task mapping",
        description:
          "Tell GAIA how your Notion documents are structured so it knows which sections represent tasks, which dates become due dates, and which people mentioned become Asana assignees.",
      },
      {
        step: "Bridge planning and execution automatically",
        description:
          "GAIA creates Asana tasks from Notion content and keeps Notion updated with Asana progress. Your planning documents become living status reports.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create an entire Asana project from a single Notion page?",
        answer:
          "Yes. GAIA can read a Notion project brief and generate an Asana project complete with sections, tasks, subtasks, and dependencies based on the structure of the Notion document.",
      },
      {
        question:
          "What happens when Notion content changes after Asana tasks are created?",
        answer:
          "GAIA can detect Notion page updates and either update existing Asana tasks to reflect changes or create a comment on affected tasks flagging that the source document changed.",
      },
      {
        question:
          "Does this work with Notion's database view as well as page documents?",
        answer:
          "Yes. GAIA can sync both Notion database rows (where each row becomes an Asana task) and page-based documents (where GAIA extracts tasks from the page content).",
      },
    ],
  },

  "notion-github": {
    slug: "notion-github",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "GitHub",
    toolBSlug: "github",
    tagline: "Keep your Notion engineering wiki in sync with GitHub activity",
    metaTitle:
      "Notion + GitHub Automation - Engineering Wiki from GitHub | GAIA",
    metaDescription:
      "Automate Notion and GitHub with GAIA. Generate Notion documentation from GitHub, sync repository updates to your wiki, and keep your engineering knowledge base current automatically.",
    keywords: [
      "Notion GitHub integration",
      "Notion GitHub automation",
      "GitHub to Notion documentation",
      "engineering wiki GitHub",
      "code documentation Notion",
      "Notion GitHub workflow",
    ],
    intro:
      "Engineering documentation in Notion goes stale the moment a codebase changes. GitHub repositories evolve daily — new features ship, APIs change, architectural decisions are made — but the Notion wiki doesn't know it. GAIA monitors GitHub activity and automatically keeps your Notion engineering documentation current.\n\nRelease notes appear in Notion as PRs merge. Architecture decisions recorded in GitHub PR discussions become Notion ADR entries. Repository READMEs propagate to the wiki. Your engineering team's Notion workspace becomes a living reflection of what's actually in the codebase, not a document that was accurate six months ago.",
    useCases: [
      {
        title: "Automatic release notes in Notion",
        description:
          "Each GitHub release triggers GAIA to create a Notion release notes page populated with merged PRs, closed issues, and contributor credits organized by feature area.",
      },
      {
        title: "Architecture Decision Records from PR discussions",
        description:
          "Significant technical decisions made in GitHub PR review threads get extracted by GAIA and saved as structured ADR entries in your Notion engineering wiki for permanent reference.",
      },
      {
        title: "Repository README sync",
        description:
          "When a GitHub README is updated, GAIA propagates the changes to the corresponding Notion project page so documentation stays consistent across both platforms.",
      },
      {
        title: "Open issue dashboard in Notion",
        description:
          "GAIA maintains a real-time Notion database of open GitHub issues across all repositories, organized by label, priority, and repository for engineering leadership visibility.",
      },
      {
        title: "Sprint retrospective data",
        description:
          "GAIA compiles GitHub PR metrics — merge time, review cycles, contributor activity — into a Notion retrospective page before each sprint review so the data is ready without manual collection.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and GitHub to GAIA",
        description:
          "Authorize GAIA with your Notion workspace and GitHub organization. Select which repositories to monitor and which Notion sections should receive generated documentation.",
      },
      {
        step: "Configure documentation workflows",
        description:
          "Choose which GitHub events create or update Notion content. Start with release notes and grow to include ADRs, issue tracking, and retrospective data as your workflow matures.",
      },
      {
        step: "Engineering wiki stays current automatically",
        description:
          "As GitHub activity occurs, GAIA updates Notion documentation in real time. Your wiki becomes a trusted source of truth rather than a maintenance burden.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA read existing Notion pages before creating new ones to avoid duplication?",
        answer:
          "Yes. GAIA checks whether a page for a given repository, release, or topic already exists in Notion and appends to it rather than creating a duplicate entry.",
      },
      {
        question: "Does GAIA work with private GitHub repositories?",
        answer:
          "Yes. GAIA uses your authorized GitHub credentials and can access private repositories you have permission to access within your organization.",
      },
      {
        question:
          "Can non-engineers use the Notion documentation GAIA creates from GitHub?",
        answer:
          "Absolutely. Product managers, designers, and leadership get GitHub intelligence in Notion without needing GitHub access. This is one of the primary use cases — making engineering activity visible to the whole team.",
      },
    ],
  },

  "google-calendar-asana": {
    slug: "google-calendar-asana",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline:
      "Create Asana tasks from calendar events and block time for project work",
    metaTitle:
      "Google Calendar + Asana Automation - Schedule and Tasks Aligned | GAIA",
    metaDescription:
      "Automate Google Calendar and Asana with GAIA. Create Asana tasks from calendar events, block calendar time for project work, and keep your schedule and project management synchronized.",
    keywords: [
      "Google Calendar Asana integration",
      "calendar Asana automation",
      "meeting to Asana task",
      "time block Asana",
      "schedule project management sync",
      "Google Calendar Asana workflow",
    ],
    intro:
      "Your Google Calendar tells you how time is allocated. Asana tells you what work needs doing. But most teams manage these separately — meetings get scheduled without corresponding Asana prep tasks, Asana deadlines exist without calendar time blocked to meet them, and project work suffers because schedule and task management don't inform each other.\n\nGAIA makes Google Calendar and Asana work as a unified system. Meeting events generate Asana prep and follow-up tasks. Asana task due dates create calendar reminders. Project milestones block calendar time for focused work. Your schedule and your task list finally tell the same story.",
    useCases: [
      {
        title: "Meeting prep tasks from calendar events",
        description:
          "For every calendar event with external attendees, GAIA creates an Asana task to prepare for the meeting — review agenda, prepare talking points — assigned to the meeting host and due the day before.",
      },
      {
        title: "Post-meeting action items in Asana",
        description:
          "After calendar events end, GAIA creates a follow-up Asana task to capture and distribute meeting notes and action items, ensuring meetings produce tracked outcomes.",
      },
      {
        title: "Calendar blocks for Asana project milestones",
        description:
          "When an Asana project milestone has a due date, GAIA creates a Google Calendar reminder event so the deadline surfaces in your schedule with appropriate advance notice.",
      },
      {
        title: "Deadline proximity alerts",
        description:
          "GAIA monitors Asana tasks and detects when deadlines are approaching on days that are heavily scheduled in Google Calendar. It alerts you to reschedule meetings or extend deadlines proactively.",
      },
      {
        title: "Recurring meeting to recurring Asana task",
        description:
          "Recurring calendar events like weekly standups or client check-ins generate recurring Asana tasks for prep and follow-up so standard meeting hygiene is always tracked.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Asana to GAIA",
        description:
          "Authorize GAIA with your Google Calendar and Asana account. Configure which Asana projects receive tasks from which calendar event types.",
      },
      {
        step: "Define task creation and time-blocking rules",
        description:
          "Specify which meeting types generate prep tasks, how far in advance to create them, and which Asana task due dates should create calendar reminders or time blocks.",
      },
      {
        step: "GAIA aligns your schedule and task list",
        description:
          "Calendar events and Asana tasks stay in sync automatically. You plan and schedule in either tool and GAIA keeps both informed.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create Asana tasks for all calendar events or only specific types?",
        answer:
          "You control which event types generate Asana tasks. Common configurations include only events with external attendees, events tagged with specific calendars, or events lasting over 30 minutes.",
      },
      {
        question:
          "Does GAIA update Asana tasks if a calendar event is rescheduled?",
        answer:
          "Yes. When a calendar event changes date or time, GAIA updates the due date on the corresponding Asana prep task to match the new schedule.",
      },
      {
        question:
          "Can GAIA help identify when Asana deadlines conflict with a busy calendar?",
        answer:
          "Yes. GAIA can audit your upcoming Asana deadlines against your Google Calendar and flag days where task deadlines and heavy meeting schedules conflict so you can plan accordingly.",
      },
    ],
  },

  "google-calendar-linear": {
    slug: "google-calendar-linear",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline:
      "Connect your engineering sprint schedule with Google Calendar automatically",
    metaTitle:
      "Google Calendar + Linear Automation - Sprint Schedule Sync | GAIA",
    metaDescription:
      "Automate Google Calendar and Linear with GAIA. Sync Linear sprint dates to Google Calendar, get meeting context from Linear issues, and keep your engineering schedule and project board aligned.",
    keywords: [
      "Google Calendar Linear integration",
      "Linear sprint calendar sync",
      "calendar Linear automation",
      "engineering schedule Linear",
      "Linear deadline Google Calendar",
      "sprint planning calendar",
    ],
    intro:
      "Engineering teams plan in Linear but schedule in Google Calendar. Sprint start and end dates live in Linear but don't appear on the calendar. Important Linear deadlines and cycle reviews aren't visible in the tool engineers check for their daily schedule. GAIA connects the two so your engineering timeline is visible wherever you look.\n\nLinear cycle dates appear on Google Calendar. Calendar events for sprint planning and retrospectives generate Linear cycle items. The engineering schedule and the project board tell the same story without manual synchronization between them.",
    useCases: [
      {
        title: "Linear cycle dates synced to Google Calendar",
        description:
          "Linear sprint cycles appear as Google Calendar events with start and end dates, giving engineers and engineering managers visibility into the sprint timeline alongside their other commitments.",
      },
      {
        title: "Linear issue due dates as calendar reminders",
        description:
          "High-priority Linear issues with due dates create Google Calendar reminders so engineers see approaching deadlines in their calendar rather than only in Linear.",
      },
      {
        title: "Sprint planning meeting prep from Linear",
        description:
          "Before sprint planning calendar events, GAIA compiles the Linear backlog items proposed for the sprint and sends a prep summary so the team arrives with full context.",
      },
      {
        title: "Retrospective data before review meetings",
        description:
          "Before retrospective calendar events, GAIA pulls Linear cycle metrics (completed issues, velocity, cycle time) and creates a meeting prep document so retrospectives are data-informed.",
      },
      {
        title: "Engineering milestone calendar events",
        description:
          "Linear project milestones generate Google Calendar events so product launches, feature freezes, and major deliverables are visible on the shared team calendar.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Linear to GAIA",
        description:
          "Authorize GAIA with your Google Calendar and Linear workspace. Specify which Linear teams and cycles should sync to which calendars.",
      },
      {
        step: "Configure sync and notification rules",
        description:
          "Choose which Linear events create Calendar events, which issue due dates generate reminders, and which calendar events should pull Linear context for prep summaries.",
      },
      {
        step: "Engineering schedule and board stay aligned",
        description:
          "Linear timelines appear on the calendar automatically. Calendar events have Linear context attached. Both tools reflect the same engineering schedule.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create Linear cycles from calendar date ranges I define?",
        answer:
          "Yes. You can ask GAIA to create a new Linear cycle based on dates you've set in Google Calendar for a sprint, and it will configure the cycle with the correct start and end dates in Linear.",
      },
      {
        question:
          "Does GAIA sync Linear cycles for all teams or specific ones?",
        answer:
          "You configure which Linear teams sync to which calendars. This is useful for separating engineering team calendars from product or design team cycles.",
      },
      {
        question:
          "Can GAIA send calendar invites to the team for sprint events?",
        answer:
          "Yes. When GAIA creates Google Calendar events from Linear cycles, you can configure it to add your team members as guests so the sprint events appear on everyone's calendar.",
      },
    ],
  },

  "google-calendar-zoom": {
    slug: "google-calendar-zoom",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline: "Seamlessly link your Google Calendar meetings with Zoom calls",
    metaTitle:
      "Google Calendar + Zoom Automation - Meeting Links and Prep | GAIA",
    metaDescription:
      "Automate Google Calendar and Zoom with GAIA. Add Zoom links to calendar events, get meeting prep before calls, and manage your video meeting schedule without manual coordination.",
    keywords: [
      "Google Calendar Zoom integration",
      "calendar Zoom automation",
      "add Zoom link to calendar",
      "Zoom Google Calendar sync",
      "meeting scheduling Zoom calendar",
      "video meeting automation",
    ],
    intro:
      "Creating Zoom meetings and adding them to Google Calendar events is a small but persistent friction point. You create a calendar event, generate a Zoom link, paste it in, and hope everyone finds it. When meetings get rescheduled, the Zoom link sometimes changes. When new attendees are added, they may miss the link.\n\nGAIA automates the Google Calendar-Zoom connection. New calendar events get Zoom links added automatically. Meeting prep arrives in your preferred channel before each call. Post-meeting notes capture what happened. The administrative overhead of video meeting management disappears.",
    useCases: [
      {
        title: "Auto-add Zoom links to calendar events",
        description:
          "When you create a Google Calendar event with external attendees, GAIA automatically generates a Zoom meeting and adds the join link to the calendar event so attendees always have the video call details.",
      },
      {
        title: "Pre-meeting prep reminders",
        description:
          "Five minutes before each calendar event with a Zoom link, GAIA sends the join link, agenda, and attendee list to your preferred channel so you're never scrambling to find the meeting details.",
      },
      {
        title: "Post-call follow-up prompts",
        description:
          "After a Zoom call ends, GAIA sends a prompt to capture meeting notes and action items while context is fresh, with a structured template ready to fill in.",
      },
      {
        title: "Rescheduled meeting Zoom link management",
        description:
          "When a calendar event is rescheduled, GAIA checks whether the Zoom meeting needs updating and keeps the calendar event's video link current so attendees always have working join details.",
      },
      {
        title: "Meeting recording notifications",
        description:
          "When a Zoom recording is available for a calendar event, GAIA notifies attendees with the recording link so they can review it without searching through Zoom's recording library.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Zoom to GAIA",
        description:
          "Authorize GAIA with your Google Calendar and Zoom account. Configure which event types should get Zoom links added automatically.",
      },
      {
        step: "Set your meeting preferences",
        description:
          "Choose which calendar events generate Zoom meetings — by attendee count, calendar, or event name keywords. Configure your preferred prep notification channel.",
      },
      {
        step: "Meetings run smoothly from start to finish",
        description:
          "GAIA handles the Zoom link creation, calendar event updates, pre-meeting prep, and post-meeting follow-up so you focus entirely on the conversation.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA use my existing Zoom settings (waiting room, passcode) when creating meetings?",
        answer:
          "Yes. GAIA creates Zoom meetings with your account's default settings. You can also configure specific settings per event type — like enabling waiting rooms for external client calls but not internal team meetings.",
      },
      {
        question: "Does GAIA work with Google Meet as well as Zoom?",
        answer:
          "GAIA can work with both. You can configure GAIA to use Zoom for external meetings and Google Meet for internal ones based on attendee domains or calendar tags.",
      },
      {
        question:
          "Will GAIA notify all attendees when a Zoom meeting is created or updated?",
        answer:
          "Google Calendar handles attendee notifications for event updates. GAIA updates the calendar event with Zoom details, and Google Calendar's standard invitation flow notifies attendees automatically.",
      },
    ],
  },

  "todoist-asana": {
    slug: "todoist-asana",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline:
      "Bridge personal Todoist tasks with team Asana projects seamlessly",
    metaTitle:
      "Todoist + Asana Automation - Personal and Team Task Sync | GAIA",
    metaDescription:
      "Automate Todoist and Asana with GAIA. Sync personal Todoist tasks with team Asana projects, capture Asana assignments in Todoist, and manage individual and team work in one view.",
    keywords: [
      "Todoist Asana integration",
      "Todoist Asana sync",
      "personal team task sync",
      "Todoist Asana automation",
      "individual team task management",
      "Asana Todoist workflow",
    ],
    intro:
      "Many professionals use Todoist for personal task management and Asana for team project work. The problem is these systems don't talk to each other. Asana task assignments don't appear in your Todoist inbox. Personal tasks in Todoist don't reflect project commitments in Asana. You end up with two separate systems to maintain.\n\nGAIA bridges personal and team task management. When you're assigned an Asana task, it appears in Todoist. When you complete a task in Todoist that maps to Asana, both update. Your personal productivity system and your team's project management stay synchronized without double entry.",
    useCases: [
      {
        title: "Asana assignments synced to Todoist",
        description:
          "When you're assigned a task in Asana, GAIA automatically adds it to your Todoist inbox so all your work — individual and team — appears in one task manager.",
      },
      {
        title: "Todoist completion updates Asana",
        description:
          "When you complete an Asana-sourced task in Todoist, GAIA marks it complete in Asana automatically so your team's project board stays accurate without extra effort.",
      },
      {
        title: "Personal task context in Asana",
        description:
          "Todoist personal tasks related to Asana projects can be linked so project managers see the full picture of work being done — both the tracked Asana tasks and the personal prep work in Todoist.",
      },
      {
        title: "Due date synchronization",
        description:
          "When an Asana task due date changes, GAIA updates the corresponding Todoist task due date automatically so your personal priority list always reflects the latest project schedule.",
      },
      {
        title: "Daily personal briefing from Asana",
        description:
          "Each morning GAIA creates a Todoist daily overview that includes your Asana tasks due today alongside your personal Todoist tasks, giving you a complete view of the day's commitments.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Asana to GAIA",
        description:
          "Authorize GAIA with your Todoist account and Asana workspace. Configure which Asana projects should sync tasks to Todoist.",
      },
      {
        step: "Set sync preferences",
        description:
          "Choose whether all Asana assignments sync to Todoist or only assignments from specific projects. Configure which Todoist project receives Asana tasks.",
      },
      {
        step: "One task list for all your work",
        description:
          "GAIA maintains synchronization between both systems. You manage your work from Todoist while Asana stays updated for your team automatically.",
      },
    ],
    faqs: [
      {
        question:
          "Will GAIA create duplicates if a task is in both Todoist and Asana?",
        answer:
          "GAIA tracks which Todoist tasks originated from Asana and avoids creating duplicates. Updates flow between the linked tasks rather than creating new entries each time.",
      },
      {
        question:
          "Can I use Todoist labels to organize Asana tasks alongside personal tasks?",
        answer:
          "Yes. GAIA can apply Todoist labels based on the Asana project the task came from, making it easy to filter your Todoist view to show only Asana work or only personal tasks.",
      },
      {
        question:
          "Does this work with shared Todoist projects as well as personal ones?",
        answer:
          "Yes. GAIA can sync Asana team tasks to shared Todoist projects so your whole team can manage Asana work from Todoist if preferred.",
      },
    ],
  },

  "asana-jira": {
    slug: "asana-jira",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "Jira",
    toolBSlug: "jira",
    tagline:
      "Sync Asana project tasks with Jira engineering tickets automatically",
    metaTitle: "Asana + Jira Automation - Product and Engineering Sync | GAIA",
    metaDescription:
      "Automate Asana and Jira with GAIA. Sync Asana tasks with Jira tickets, keep product and engineering aligned, and eliminate manual status updates between project management tools.",
    keywords: [
      "Asana Jira integration",
      "Asana Jira sync",
      "Asana Jira automation",
      "product engineering sync",
      "Asana to Jira tickets",
      "project management integration",
    ],
    intro:
      "Product teams track work in Asana while engineering teams work in Jira. The gap between them is where projects slow down — product managers create Asana tasks that need corresponding Jira tickets, status updates must be manually mirrored across both tools, and neither side has full visibility into the other.\n\nGAIA synchronizes Asana and Jira so the right information is in both places without double entry. Asana tasks create Jira tickets. Jira status changes update Asana. Product managers see engineering progress in Asana. Engineers see product context in Jira. Both teams work in their preferred tool while GAIA keeps them aligned.",
    useCases: [
      {
        title: "Asana task to Jira ticket creation",
        description:
          "When an Asana task requires engineering work, GAIA creates a corresponding Jira ticket with the product context, acceptance criteria, and due date from the Asana task.",
      },
      {
        title: "Jira status mirrored to Asana",
        description:
          "As Jira tickets progress through engineering workflow stages, GAIA updates the linked Asana task status so product managers see real-time engineering progress without checking Jira.",
      },
      {
        title: "Asana deadline alerts in Jira",
        description:
          "When an Asana task has a product deadline, GAIA adds that deadline context to the linked Jira ticket so engineers understand the business urgency behind their technical work.",
      },
      {
        title: "Bug escalation from Jira to Asana",
        description:
          "High-severity Jira bugs automatically create Asana tasks in the product team's project so product managers can track customer-facing impact and coordinate response communications.",
      },
      {
        title: "Release planning coordination",
        description:
          "Asana release milestones link to Jira fix versions so GAIA can report on what percentage of planned release work is complete in Jira, giving product teams accurate launch confidence.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Asana and Jira to GAIA",
        description:
          "Authorize GAIA with your Asana workspace and Jira project. Define the mapping between Asana projects and Jira projects.",
      },
      {
        step: "Configure bidirectional sync rules",
        description:
          "Set which Asana task events create Jira tickets, which Jira status changes update Asana, and how fields map between the two systems.",
      },
      {
        step: "Product and engineering work in their preferred tools",
        description:
          "GAIA handles all status synchronization automatically. Both teams get the visibility they need without using each other's tools.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA map Asana custom fields to Jira custom fields?",
        answer:
          "Yes. Custom fields in Asana can map to custom fields in Jira so specialized metadata like client name, budget code, or component area is preserved when tasks sync between tools.",
      },
      {
        question:
          "What happens if someone updates the Asana task and the Jira ticket at the same time?",
        answer:
          "GAIA uses timestamp-based conflict resolution, applying the most recent update as the source of truth. For critical fields, you can configure which system takes priority in conflict scenarios.",
      },
      {
        question:
          "Does GAIA support syncing between Asana portfolios and Jira epics?",
        answer:
          "Yes. Asana portfolios can map to Jira epics, giving product leadership a cross-tool view where Asana's portfolio progress reflects the actual Jira issue completion underneath.",
      },
    ],
  },

  "jira-linear": {
    slug: "jira-linear",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline: "Sync Jira and Linear so teams using both stay perfectly aligned",
    metaTitle: "Jira + Linear Automation - Cross-Team Issue Sync | GAIA",
    metaDescription:
      "Automate Jira and Linear with GAIA. Sync issues between Jira and Linear, keep cross-team projects aligned, and eliminate the friction of managing work across two engineering tools.",
    keywords: [
      "Jira Linear integration",
      "Jira Linear sync",
      "Jira Linear automation",
      "cross-team issue sync",
      "engineering tool integration",
      "Jira to Linear migration",
    ],
    intro:
      "Many organizations have teams that use Jira and teams that use Linear. Enterprise departments use Jira for compliance and audit trails while product engineering teams prefer Linear for speed. When these teams collaborate, work coordination requires manual translation between the two systems — a constant overhead that slows cross-team projects.\n\nGAIA synchronizes Jira and Linear so cross-team work is visible in both places. Issues created in Linear for a cross-functional feature appear in Jira for the enterprise team. Jira ticket status changes flow back to Linear. Teams use their preferred tool while GAIA keeps the shared work in sync.",
    useCases: [
      {
        title: "Cross-team issue visibility",
        description:
          "When a Linear team creates an issue that requires input from a Jira team (like infrastructure or security), GAIA creates a linked Jira ticket so the work is tracked in both systems.",
      },
      {
        title: "Bidirectional status sync",
        description:
          "Issue status changes in either Jira or Linear propagate to the linked issue in the other system, so both teams always see current status without checking the other tool.",
      },
      {
        title: "Migration assistance",
        description:
          "Teams migrating from Jira to Linear use GAIA to run both tools in parallel during transition, keeping historical Jira issues linked to new Linear counterparts without losing audit history.",
      },
      {
        title: "Dependency tracking across tools",
        description:
          "When a Linear issue is blocked by a Jira ticket, GAIA links the dependency and notifies both teams so blockers are visible regardless of which tool each team checks.",
      },
      {
        title: "Executive reporting across both platforms",
        description:
          "GAIA compiles status from both Jira and Linear into a unified report for leadership, showing project health across teams without requiring executives to access either platform directly.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Linear to GAIA",
        description:
          "Authorize GAIA with your Jira instance and Linear workspace. Map which Jira projects correspond to which Linear teams for routing.",
      },
      {
        step: "Configure sync rules and field mappings",
        description:
          "Define which issue types sync between systems, how priority and status fields map across the two tools, and which events trigger cross-system updates.",
      },
      {
        step: "Teams work independently, GAIA keeps them aligned",
        description:
          "Each team works in their preferred tool. GAIA handles all cross-tool synchronization automatically so collaboration happens without tool-switching overhead.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA handle the different priority scales between Jira and Linear?",
        answer:
          "Yes. GAIA maps Jira's priority levels (Highest, High, Medium, Low, Lowest) to Linear's priority scale (Urgent, High, Medium, Low, No priority) intelligently, and you can customize the mapping.",
      },
      {
        question: "Does GAIA sync comments between Jira and Linear?",
        answer:
          "Yes. Comments added to issues in either tool sync to the linked issue in the other system, so conversation context is preserved regardless of where team members prefer to comment.",
      },
      {
        question: "Is this suitable for compliance-heavy Jira workflows?",
        answer:
          "GAIA respects Jira's audit and compliance requirements. It creates issues and adds comments through the standard Jira API so all changes are properly attributed and logged in Jira's audit trail.",
      },
    ],
  },

  "jira-github": {
    slug: "jira-github",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "GitHub",
    toolBSlug: "github",
    tagline:
      "Link Jira issues to GitHub PRs and keep them synchronized automatically",
    metaTitle: "Jira + GitHub Automation - Issue and Code Sync | GAIA",
    metaDescription:
      "Automate Jira and GitHub with GAIA. Sync Jira issues with GitHub pull requests, auto-update issue status when PRs merge, and give your team real-time development visibility in Jira.",
    keywords: [
      "Jira GitHub integration",
      "Jira GitHub sync",
      "Jira GitHub automation",
      "PR to Jira issue",
      "GitHub Jira workflow",
      "engineering project management sync",
    ],
    intro:
      "Jira tracks what needs to be built. GitHub is where it gets built. But the two rarely reflect the same state — PRs merge without the Jira issue updating, branches stay open after issues close, and development progress is invisible to product stakeholders who track everything in Jira.\n\nGAIA automates the Jira-GitHub connection so both systems reflect engineering reality. PR events update Jira issues. Merged PRs transition issues to Done. New Jira issues can trigger branch creation. Your project board accurately reflects your codebase state without anyone manually updating it.",
    useCases: [
      {
        title: "Automatic Jira issue transitions from PR events",
        description:
          "When a GitHub PR referencing a Jira issue is opened, GAIA moves the issue to 'In Progress'. When the PR is merged, GAIA moves it to 'Done'. Jira always reflects the current development state.",
      },
      {
        title: "GitHub branch creation from Jira issues",
        description:
          "When a Jira issue moves to 'In Progress', GAIA creates the corresponding GitHub branch with the correct naming convention, saving engineers the manual branch setup step.",
      },
      {
        title: "PR status in Jira comments",
        description:
          "GAIA posts GitHub PR details (title, author, review status, CI status) as Jira issue comments so product managers and QA can see development progress directly in Jira.",
      },
      {
        title: "Release notes from Jira to GitHub",
        description:
          "GAIA compiles all Jira issues resolved in a sprint into formatted GitHub release notes, linking each changelog item back to the Jira issue for full traceability.",
      },
      {
        title: "CI failure alerts on Jira issues",
        description:
          "When GitHub Actions CI fails on a branch linked to a Jira issue, GAIA comments on the Jira issue with the failure details so the assigned engineer sees it in their issue tracker.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and GitHub to GAIA",
        description:
          "Authorize GAIA with your Jira project and GitHub organization. Configure which repositories link to which Jira projects.",
      },
      {
        step: "Set up the issue-PR linking convention",
        description:
          "Define how PRs reference Jira issues — by issue key in the PR title, branch name, or description. Configure the Jira status transitions that correspond to each GitHub event.",
      },
      {
        step: "Code and project management stay in sync",
        description:
          "GAIA monitors both systems and keeps them synchronized. Engineers work in GitHub, stakeholders track in Jira, and both see the same reality.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA identify which Jira issue a GitHub PR relates to?",
        answer:
          "GAIA looks for Jira issue keys (like PROJECT-123) in PR titles, branch names, and PR descriptions. This convention is standard practice at most engineering teams and requires no extra tooling.",
      },
      {
        question: "Can GAIA handle GitHub PRs that close multiple Jira issues?",
        answer:
          "Yes. If a PR references multiple Jira issue keys, GAIA updates all linked issues when the PR status changes. Each issue is updated individually with the appropriate transition.",
      },
      {
        question:
          "Does GAIA's integration complement or replace Jira's native GitHub app?",
        answer:
          "GAIA provides more intelligent automation than Jira's native GitHub integration. It handles smart status transitions, CI notifications, and branch creation that the native integration doesn't support.",
      },
    ],
  },

  "zoom-google-calendar": {
    slug: "zoom-google-calendar",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Automatically add Zoom links to Google Calendar events and manage meetings effortlessly",
    metaTitle:
      "Zoom + Google Calendar Automation - Video Meeting Management | GAIA",
    metaDescription:
      "Automate Zoom and Google Calendar with GAIA. Generate Zoom links for calendar events automatically, receive pre-meeting reminders, and manage your video meeting schedule without manual effort.",
    keywords: [
      "Zoom Google Calendar integration",
      "Zoom calendar automation",
      "add Zoom to calendar event",
      "Google Calendar Zoom link",
      "video meeting scheduling automation",
      "Zoom calendar sync",
    ],
    intro:
      "Every external meeting involves the same repetitive steps: create a Zoom meeting, copy the link, edit the calendar event, paste the link, and hope nothing changes. When meetings get rescheduled or new attendees are added, the process repeats. This low-value administrative work takes time away from actual meeting preparation.\n\nGAIA automates the Zoom and Google Calendar connection. Calendar events automatically get Zoom meetings created and linked. Reschedules update Zoom meetings without manual intervention. Pre-meeting reminders arrive with working join links and context. The administrative overhead of video meeting management disappears.",
    useCases: [
      {
        title: "Automatic Zoom links for calendar events",
        description:
          "When you create a Google Calendar event with external attendees, GAIA generates a Zoom meeting and adds the join URL, meeting ID, and passcode to the event description automatically.",
      },
      {
        title: "Meeting reminders with context",
        description:
          "Ten minutes before each Zoom-linked calendar event, GAIA sends a reminder with the join link, attendee list, any shared agenda, and a summary of recent interactions with the attendees.",
      },
      {
        title: "Reschedule Zoom meetings with calendar",
        description:
          "When a Google Calendar event is rescheduled, GAIA updates the corresponding Zoom meeting time automatically so attendees always have a working join link with current timing.",
      },
      {
        title: "Post-meeting recording distribution",
        description:
          "After a Zoom call ends and the cloud recording processes, GAIA adds the recording link to the Google Calendar event so attendees can find the recording by checking the original calendar entry.",
      },
      {
        title: "Zoom meeting analytics by calendar event type",
        description:
          "GAIA tracks Zoom meeting duration and attendance against calendar event categories, providing insights into how much time different meeting types actually consume versus what was scheduled.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Google Calendar to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Google Calendar. Configure which calendar event types should automatically get Zoom meetings created.",
      },
      {
        step: "Set your meeting creation preferences",
        description:
          "Choose default Zoom settings per event type — waiting rooms for client calls, auto-recording for important meetings, and host video preferences by meeting category.",
      },
      {
        step: "Meetings are managed end to end automatically",
        description:
          "From calendar event creation through post-meeting recording distribution, GAIA handles all the administrative work of running Zoom meetings via your calendar.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA create a new Zoom meeting for every calendar event or reuse links?",
        answer:
          "By default GAIA creates a unique Zoom meeting per calendar event for security and tracking. For recurring events, you can configure GAIA to use a persistent Zoom room instead.",
      },
      {
        question:
          "Can GAIA manage Zoom webinars in addition to regular meetings?",
        answer:
          "Yes. GAIA can create Zoom webinars from calendar events for large external events and manage registration, reminders, and post-webinar recording distribution.",
      },
      {
        question:
          "What happens to the Zoom meeting if a calendar event is cancelled?",
        answer:
          "GAIA automatically cancels the corresponding Zoom meeting when a Google Calendar event is deleted, preventing orphaned Zoom meetings and keeping your Zoom account tidy.",
      },
    ],
  },

  "zoom-slack": {
    slug: "zoom-slack",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline:
      "Start Zoom calls from Slack and share meeting summaries automatically",
    metaTitle: "Zoom + Slack Automation - Video Meetings from Chat | GAIA",
    metaDescription:
      "Automate Zoom and Slack with GAIA. Start Zoom meetings from Slack, share meeting summaries to channels, get pre-meeting reminders in chat, and keep your team coordinated across both tools.",
    keywords: [
      "Zoom Slack integration",
      "start Zoom from Slack",
      "Zoom Slack automation",
      "meeting summary Slack",
      "Zoom Slack bot",
      "video meeting Slack notification",
    ],
    intro:
      "Teams coordinate on Slack but meet on Zoom. The switch between the two creates friction — finding the Zoom link, notifying the team a meeting is starting, sharing what was decided after the call. GAIA connects Zoom and Slack so video meetings flow naturally from chat and back again.\n\nWith GAIA, starting a Zoom call from Slack takes one message. Meeting summaries post to the right channels automatically after calls end. Pre-meeting reminders arrive in Slack with all the context you need. The transition between Slack conversation and Zoom meeting becomes invisible.",
    useCases: [
      {
        title: "Start Zoom meetings from Slack",
        description:
          "Ask GAIA in any Slack channel to start a Zoom meeting for the conversation. GAIA creates the Zoom room and posts the join link to the channel so participants can join instantly.",
      },
      {
        title: "Post meeting summaries to Slack",
        description:
          "After a Zoom call, GAIA posts a structured summary to the relevant Slack channel including key decisions, action items, and participants so the team is aligned even if they missed the call.",
      },
      {
        title: "Zoom meeting reminders in Slack",
        description:
          "Before scheduled Zoom meetings linked to your calendar, GAIA sends a Slack DM with the join link, agenda, and attendee list so you're prepared and on time.",
      },
      {
        title: "Recording notifications to Slack",
        description:
          "When a Zoom cloud recording is ready, GAIA posts the recording link to the designated Slack channel so team members who missed the live call can catch up immediately.",
      },
      {
        title: "On-call meeting triggers",
        description:
          "When an incident alert fires in Slack, GAIA automatically creates an incident Zoom room and posts the join link to the on-call channel so the team can join a war room instantly.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Slack to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Slack workspace. Configure which Slack channels should receive meeting summaries and recording notifications.",
      },
      {
        step: "Configure meeting triggers and summary preferences",
        description:
          "Choose what meeting summaries include, which channels get notified for different meeting types, and how pre-meeting reminders should be formatted.",
      },
      {
        step: "Chat and video meetings work as one system",
        description:
          "Zoom meetings start from Slack effortlessly. Post-meeting content flows back into Slack automatically. Your team's communication stays unified across both tools.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA identify which Slack channel to post a meeting summary to?",
        answer:
          "Yes. GAIA uses the channel where the meeting was initiated, the calendar event description, or rules you configure (like 'engineering Zoom calls post to #engineering-updates') to route summaries intelligently.",
      },
      {
        question:
          "Does GAIA require Zoom cloud recording to generate meeting summaries?",
        answer:
          "Zoom cloud recording with transcription provides the richest summaries. Without it, GAIA generates summaries from calendar event context and any pre/post meeting Slack messages. Results improve significantly with transcription access.",
      },
      {
        question:
          "Can GAIA handle recurring Zoom meetings with the same Slack channel?",
        answer:
          "Yes. Recurring meetings can be configured to always post summaries and recordings to the same Slack channel, building a running archive of meeting outcomes in one place.",
      },
    ],
  },
  ...combosBatchB,
  ...combosBatchC,
  ...combosBatchD,
  ...combosBatchE,
  ...combosBatchF,
  ...combosBatchG,
  ...combosBatchH,
};

export function getCombo(slug: string): IntegrationCombo | undefined {
  return combos[slug];
}

export function getAllComboSlugs(): string[] {
  return Object.keys(combos);
}

export function getAllCombos(): IntegrationCombo[] {
  return Object.values(combos);
}
