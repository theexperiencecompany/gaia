import type { IntegrationCombo } from "./combosData";

export const combosBatchE: Record<string, IntegrationCombo> = {
  "linear-asana": {
    slug: "linear-asana",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline:
      "Bridge engineering issues with cross-team project management automatically",
    metaTitle:
      "Linear + Asana Automation - Sync Engineering and Projects | GAIA",
    metaDescription:
      "Connect Linear and Asana with GAIA. Automatically mirror Linear issues to Asana tasks, sync status updates across both tools, and give every team a unified view of engineering work without manual duplication.",
    keywords: [
      "Linear Asana integration",
      "Linear Asana sync",
      "sync Linear to Asana",
      "engineering project management automation",
      "Linear Asana workflow",
      "connect Linear and Asana",
      "issue tracking project management sync",
    ],
    intro:
      "Engineering teams live in Linear while product managers, designers, and cross-functional partners live in Asana. Both tools serve their users well, but when the two teams need to collaborate on the same deliverable, the gap between them creates friction. Engineers mark an issue complete in Linear while the Asana task still shows in-progress. Product managers ask for status updates that engineers already posted in Linear. The result is duplicate work and a constant back-and-forth to keep everyone aligned.\n\nGAIA connects Linear and Asana so that work done in one tool is reflected automatically in the other. When an engineer picks up a Linear issue, the linked Asana task updates. When a product manager changes a priority in Asana, GAIA flags the relevant Linear issue so engineers can reorder their queue. The two tools stay synchronized without anyone manually copying updates between them.\n\nThis integration is especially valuable for product engineering teams running agile sprints in Linear who need to surface progress to stakeholders managing roadmaps in Asana, and for companies that standardized on Asana org-wide but gave engineering autonomy to use Linear for day-to-day issue tracking.",
    useCases: [
      {
        title: "Mirror Linear issue status to Asana tasks",
        description:
          "When a Linear issue moves from In Progress to Done, GAIA automatically marks the corresponding Asana task complete, so cross-functional stakeholders always see current engineering status without asking for updates.",
      },
      {
        title: "Create Linear issues from Asana feature tasks",
        description:
          "When a product manager marks an Asana feature task as Ready for Engineering, GAIA creates the corresponding Linear issue with title, description, and priority already populated so engineers can pick it up immediately.",
      },
      {
        title: "Sync sprint milestones to Asana project timelines",
        description:
          "GAIA maps Linear cycle start and end dates to Asana project milestones, keeping the product roadmap in Asana aligned with what engineering is actually building each sprint.",
      },
      {
        title: "Escalate blocked Linear issues to Asana",
        description:
          "When a Linear issue sits in Blocked status for more than a configurable threshold, GAIA creates an Asana task assigned to the relevant dependency owner so cross-team blockers get resolved without falling through the cracks.",
      },
      {
        title: "Weekly engineering summary to Asana project updates",
        description:
          "Each Friday, GAIA compiles a summary of Linear issues completed, in progress, and blocked during the week and posts it as an Asana project status update so stakeholders have a clean record without engineers writing status reports manually.",
      },
    ],
    howItWorks: [
      {
        step: "Connect both workspaces",
        description:
          "Authorize GAIA to access your Linear workspace and your Asana organization. GAIA maps Linear teams to Asana projects based on naming conventions or explicit configuration so syncing targets the right destinations.",
      },
      {
        step: "Define sync rules",
        description:
          "Tell GAIA which Linear issue states map to which Asana task statuses, which fields should flow in which direction, and how often bidirectional reconciliation should run. GAIA handles deduplication automatically.",
      },
      {
        step: "Let GAIA keep both tools current",
        description:
          "GAIA monitors both platforms for changes and propagates updates in real time. Engineers keep working in Linear and stakeholders keep working in Asana — GAIA ensures both sides always reflect the same ground truth.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA sync all Linear issues to Asana or only specific ones?",
        answer:
          "You control the scope. You can configure GAIA to sync an entire Linear team, a specific project, issues with a certain label, or only issues above a given priority threshold. Only the issues matching your rules are mirrored to Asana.",
      },
      {
        question:
          "What happens if someone edits the same issue in both tools simultaneously?",
        answer:
          "GAIA uses a last-write-wins policy by default and flags conflicts in a dedicated GAIA log channel so you can review and resolve them. You can also designate one tool as the source of truth for specific fields to prevent conflicts entirely.",
      },
      {
        question: "Can GAIA sync custom fields between Linear and Asana?",
        answer:
          "Yes. GAIA supports mapping Linear custom fields to Asana custom fields during setup. If no direct mapping exists, GAIA appends the unmapped fields as structured notes in the destination task description.",
      },
    ],
  },

  "linear-notion": {
    slug: "linear-notion",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline:
      "Sync sprint notes to Notion and link Linear issues to living docs",
    metaTitle:
      "Linear + Notion Integration - Issues Meets Documentation | GAIA",
    metaDescription:
      "Connect Linear and Notion with GAIA. Automatically sync Linear issues to Notion databases, embed issue status in sprint docs, and keep engineering documentation aligned with actual work.",
    keywords: [
      "Linear Notion integration",
      "Linear Notion sync",
      "sync Linear issues to Notion",
      "engineering documentation automation",
      "Linear Notion workflow",
      "connect Linear and Notion",
      "sprint notes automation",
    ],
    canonicalSlug: "notion-linear",
    intro:
      "Linear tracks the what and when of engineering work. Notion holds the why — the specs, retros, architecture decisions, and sprint notes that give issues their context. But when the two live completely separately, engineers waste time hunting for the spec behind an issue, and PMs lose visibility into whether the work described in a Notion doc is actually reflected in Linear.\n\nGAIA connects Linear and Notion so documentation and issue tracking reinforce each other. When a new Linear issue is created from a Notion spec, the link goes both ways. When a sprint completes, GAIA populates the Notion retrospective template with data pulled directly from Linear. Engineers get context without leaving Linear; stakeholders get traceability without leaving Notion.\n\nThis integration is particularly valuable for product teams who write detailed specs in Notion before creating Linear issues, and for engineering teams that want their sprint ceremonies — planning, review, retro — to be automatically populated with data rather than filled in manually.",
    useCases: [
      {
        title: "Create Linear issues from Notion spec pages",
        description:
          "When a Notion spec page is marked Ready for Engineering, GAIA reads the acceptance criteria, extracts discrete tasks, and creates corresponding Linear issues with links back to the source spec so engineers always have context.",
      },
      {
        title: "Auto-populate sprint retrospective templates",
        description:
          "At the end of each Linear cycle, GAIA fills the team's Notion retrospective template with cycle metrics — issues completed, carry-over, cycle time, and blockers — so the retro meeting focuses on discussion rather than data entry.",
      },
      {
        title: "Embed live issue status in Notion docs",
        description:
          "GAIA maintains a Notion database that mirrors the current state of active Linear issues. Any Notion page that references a Linear issue gets an inline status indicator so readers see whether work is in progress, blocked, or shipped.",
      },
      {
        title: "Sync Linear project updates to Notion changelog",
        description:
          "When Linear issues in a project are completed, GAIA appends a structured entry to the project's Notion changelog page, giving stakeholders a running record of what shipped and when.",
      },
      {
        title: "Link architecture decision records to Linear issues",
        description:
          "When an engineer creates an Architecture Decision Record in Notion, GAIA attaches the Notion page link to related Linear issues so future engineers can trace why implementation decisions were made.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Linear and Notion",
        description:
          "Authorize GAIA to access your Linear workspace and Notion workspace. Map Linear teams to Notion databases or page hierarchies during initial setup.",
      },
      {
        step: "Configure documentation workflows",
        description:
          "Choose which Notion page properties trigger Linear issue creation, which Linear events update Notion pages, and which Notion templates GAIA should populate at sprint boundaries.",
      },
      {
        step: "Work normally in both tools",
        description:
          "GAIA monitors Linear and Notion for the events you configured and handles all cross-tool updates automatically. Your Notion docs stay current and your Linear issues stay linked to their context.",
      },
    ],
    faqs: [
      {
        question:
          "Will GAIA overwrite content I've manually added to Notion pages?",
        answer:
          "No. GAIA writes only to dedicated sections or properties it manages. Freeform content you add to a Notion page is never modified. GAIA uses structured blocks and database properties to keep its updates isolated.",
      },
      {
        question: "Can GAIA sync Linear issue descriptions back to Notion?",
        answer:
          "Yes. You can configure bidirectional sync so that updates to a Linear issue description are reflected in the linked Notion page and vice versa. You can also set one direction as read-only to prevent accidental overwrites.",
      },
      {
        question:
          "Does this integration work with Notion databases or only pages?",
        answer:
          "Both. GAIA can sync Linear issues as rows in a Notion database for structured tracking, and it can also update or create standalone Notion pages for richer documentation like sprint retros and project specs.",
      },
    ],
  },

  "linear-clickup": {
    slug: "linear-clickup",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline:
      "Sync issues between Linear engineering and ClickUp project management",
    metaTitle:
      "Linear + ClickUp Integration - Engineering Meets Project Management | GAIA",
    metaDescription:
      "Connect Linear and ClickUp with GAIA. Automatically sync Linear engineering issues to ClickUp tasks, keep status current across both tools, and eliminate manual handoffs between engineering and project teams.",
    keywords: [
      "Linear ClickUp integration",
      "Linear ClickUp sync",
      "sync Linear to ClickUp",
      "engineering project management sync",
      "Linear ClickUp automation",
      "connect Linear and ClickUp",
      "issue tracking task management",
    ],
    intro:
      "Engineering teams that use Linear for issue tracking often work alongside operations and project management teams running their work in ClickUp. Each tool is well-suited to its audience, but the boundary between them creates a handoff problem. Project managers in ClickUp cannot see when engineering tasks progress. Engineers in Linear cannot see when upstream dependencies managed in ClickUp change.\n\nGAIA bridges the two platforms so engineering velocity is visible in ClickUp and project context is visible in Linear. Status changes in Linear propagate to ClickUp automatically. When a ClickUp task representing a product requirement is updated, GAIA flags the relevant Linear issues so engineers know what changed without switching tools.\n\nTeams that have tried to consolidate on a single tool and failed because different functions have strong preferences will find this integration especially valuable. GAIA lets each team work in their preferred tool while maintaining a shared source of truth that neither has to maintain manually.",
    useCases: [
      {
        title: "Propagate Linear issue status to ClickUp tasks",
        description:
          "When a Linear issue moves to In Review or Done, GAIA updates the linked ClickUp task status so project managers always have a real-time view of engineering progress without pinging engineers for updates.",
      },
      {
        title: "Create Linear issues from ClickUp requirements tasks",
        description:
          "When a product requirement task in ClickUp is approved and ready for development, GAIA creates corresponding Linear issues with priority, description, and due date pre-populated from the ClickUp task.",
      },
      {
        title: "Sync ClickUp sprint timelines to Linear cycles",
        description:
          "GAIA reads ClickUp sprint dates and creates matching Linear cycles, ensuring engineering sprints are aligned with the delivery schedule tracked in ClickUp without manual date entry in both tools.",
      },
      {
        title: "Alert engineers to ClickUp scope changes",
        description:
          "When a ClickUp task that has linked Linear issues is edited — priority changed, deadline shifted, requirements updated — GAIA posts a comment on the Linear issue summarizing what changed so engineers are never surprised.",
      },
      {
        title: "Roll up engineering metrics into ClickUp dashboards",
        description:
          "GAIA periodically syncs Linear cycle metrics — velocity, completion rate, lead time — into custom fields on the corresponding ClickUp project so leadership can track engineering health alongside other project KPIs.",
      },
    ],
    howItWorks: [
      {
        step: "Authorize both platforms",
        description:
          "Connect your Linear workspace and ClickUp workspace to GAIA. During setup, map Linear teams and projects to the corresponding ClickUp Spaces and Lists.",
      },
      {
        step: "Set sync direction and field mappings",
        description:
          "Define which fields are authoritative in which tool, which status values map between platforms, and which events should trigger cross-platform actions.",
      },
      {
        step: "GAIA handles ongoing synchronization",
        description:
          "From that point on, GAIA monitors both tools and applies updates automatically. Engineers and project managers each work in their preferred tool with confidence that the other side stays current.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA handle the different status models between Linear and ClickUp?",
        answer:
          "Yes. During setup you provide a status mapping table — for example, Linear's In Progress maps to ClickUp's In Development, and Linear's Done maps to ClickUp's Completed. GAIA applies this mapping consistently so statuses are always semantically equivalent.",
      },
      {
        question:
          "What happens to ClickUp tasks that have no Linear counterpart?",
        answer:
          "GAIA only acts on tasks and issues that are explicitly linked or match your configured sync rules. Unlinked ClickUp tasks are untouched. You can trigger issue creation in Linear from ClickUp manually by assigning a specific label or status.",
      },
      {
        question: "Is there a limit to how many issues GAIA can sync?",
        answer:
          "GAIA's sync capacity scales with your plan. Most engineering teams sync hundreds to thousands of issues per month without hitting limits. For very large ClickUp workspaces, you can scope sync to specific Lists or Tags to keep volume manageable.",
      },
    ],
  },

  "linear-todoist": {
    slug: "linear-todoist",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Todoist",
    toolBSlug: "todoist",
    tagline:
      "Turn Linear issues assigned to you into personal Todoist tasks automatically",
    metaTitle:
      "Linear + Todoist Integration - Engineering Issues in Your Personal Tasks | GAIA",
    metaDescription:
      "Connect Linear and Todoist with GAIA. Automatically create Todoist tasks when Linear issues are assigned to you, sync completions back, and manage your engineering workload alongside personal tasks in one place.",
    keywords: [
      "Linear Todoist integration",
      "Linear Todoist sync",
      "Linear issues to Todoist",
      "personal task management engineering",
      "Linear Todoist automation",
      "connect Linear and Todoist",
      "engineer personal productivity",
    ],
    intro:
      "Most engineers manage their work in at least two places: the team issue tracker and their personal task manager. Linear drives the sprint; Todoist (or a notebook, or a whiteboard) drives the individual. Keeping both aligned manually is friction that adds up — copying issue titles, tracking due dates in two places, remembering to mark things done in both systems.\n\nGAIA eliminates that duplication by watching Linear for assignments and automatically creating corresponding tasks in your Todoist. When an issue is assigned to you in Linear, it appears in Todoist with the right project, priority, and due date. When you complete it in either tool, GAIA marks it done in the other. Your personal task list reflects your real engineering workload without any manual copying.\n\nThis integration is ideal for engineers who use Todoist as their single place for all tasks — personal errands, recurring work, and engineering tickets — and want Linear to feed into that system automatically rather than competing with it.",
    useCases: [
      {
        title: "Auto-create Todoist tasks from Linear assignments",
        description:
          "Every time a Linear issue is assigned to you, GAIA creates a matching Todoist task with the issue title, Linear URL, priority, and target date so your personal task list is always current without any manual entry.",
      },
      {
        title: "Sync task completion back to Linear",
        description:
          "When you check off a task in Todoist, GAIA marks the linked Linear issue as completed so your team's board stays accurate even if you prefer to track your own work in Todoist.",
      },
      {
        title: "Organize Linear issues by project in Todoist",
        description:
          "GAIA maps Linear teams and projects to Todoist projects so engineering work lands in the right section of your task list and doesn't get mixed up with unrelated personal tasks.",
      },
      {
        title: "Morning digest of today's Linear priorities",
        description:
          "Each morning GAIA checks your Linear queue for high-priority issues due today or overdue and adds a Todoist task reminding you to review and action them before daily standup.",
      },
      {
        title: "Flag overdue Linear issues in Todoist",
        description:
          "When a Linear issue's due date passes without resolution, GAIA creates an urgent Todoist task flagging the overdue issue so it surfaces in your personal productivity system and doesn't get buried on the team board.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Linear and Todoist to GAIA",
        description:
          "Authorize GAIA with your Linear account and your Todoist account. GAIA identifies which Linear user you are and maps your assignments to your Todoist inbox.",
      },
      {
        step: "Configure project mapping and sync preferences",
        description:
          "Choose which Linear teams or projects should feed into Todoist, which Todoist project each should map to, and whether completions should sync bidirectionally.",
      },
      {
        step: "Work across both tools seamlessly",
        description:
          "GAIA monitors your Linear assignments and keeps your Todoist updated automatically. You can triage your day in Todoist while teammates see accurate status in Linear.",
      },
    ],
    faqs: [
      {
        question:
          "Will GAIA create a Todoist task for every Linear issue in the workspace or only my assignments?",
        answer:
          "By default GAIA only creates Todoist tasks for issues assigned to your Linear user. You can optionally configure it to also watch issues you've subscribed to or issues in a specific team regardless of assignment.",
      },
      {
        question:
          "What happens when a Linear issue is reassigned away from me?",
        answer:
          "GAIA detects the reassignment and marks the corresponding Todoist task as cancelled or deletes it, depending on your preference. This prevents stale tasks from cluttering your personal list.",
      },
      {
        question: "Can I edit the Todoist task without affecting Linear?",
        answer:
          "Yes. You can freely edit the Todoist task title, add subtasks, set reminders, or move it to a different project without those changes touching Linear. Only task completion is synced back; everything else is yours to manage locally.",
      },
    ],
  },

  "linear-trello": {
    slug: "linear-trello",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline:
      "Link Trello product roadmap cards to Linear engineering issues seamlessly",
    metaTitle:
      "Linear + Trello Integration - Roadmap Cards Meet Engineering Issues | GAIA",
    metaDescription:
      "Connect Linear and Trello with GAIA. Automatically link Trello roadmap cards to Linear engineering issues, propagate status updates, and keep product and engineering aligned without manual syncing.",
    keywords: [
      "Linear Trello integration",
      "Linear Trello sync",
      "Trello Linear automation",
      "roadmap to engineering sync",
      "connect Linear and Trello",
      "product engineering workflow automation",
      "Trello card Linear issue link",
    ],
    intro:
      "Product teams that plan roadmaps in Trello and engineering teams that execute in Linear often struggle to keep both views in sync. A Trello card representing a roadmap feature may spawn ten Linear issues, but the Trello card has no idea when those issues are completed. Product managers watch the Trello board and have no signal that engineering has shipped the underlying work.\n\nGAIA creates and maintains the link between Trello cards and Linear issues so product and engineering always share the same reality. When a Trello card moves to In Development, GAIA creates the corresponding Linear issues. As those issues progress and complete, GAIA updates the Trello card automatically. When the last issue ships, the Trello card moves to Done.\n\nThis integration suits companies that want to keep using Trello for high-level roadmap planning — its visual simplicity and broad accessibility make it popular with non-technical stakeholders — while giving engineering the power of Linear for day-to-day sprint work.",
    useCases: [
      {
        title: "Create Linear issues from Trello cards",
        description:
          "When a Trello card is moved to the Ready for Development list, GAIA breaks it into Linear issues based on the card checklist items, assigns them to the relevant Linear team, and attaches the Trello card URL for reference.",
      },
      {
        title: "Update Trello card status from Linear progress",
        description:
          "As Linear issues linked to a Trello card progress, GAIA updates the card's checklist items and custom fields so product managers see a live progress indicator on the roadmap card without checking Linear.",
      },
      {
        title: "Auto-move Trello cards when all issues ship",
        description:
          "When all Linear issues linked to a Trello card are marked Done, GAIA automatically moves the card to the Shipped list on the Trello board, giving the roadmap an accurate picture of what has been delivered.",
      },
      {
        title: "Attach Linear cycle info to Trello cards",
        description:
          "GAIA writes the target Linear cycle to a Trello card's label or custom field so product managers can see at a glance which sprint a feature is scheduled for without asking engineering.",
      },
      {
        title: "Notify Trello card members of Linear blockers",
        description:
          "When a Linear issue linked to a Trello card moves to Blocked, GAIA adds a comment to the Trello card summarizing the blocker so product owners can take cross-team action without waiting for standup.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Trello and Linear to GAIA",
        description:
          "Authorize GAIA with your Trello account and Linear workspace. Map Trello boards to Linear teams and define which Trello lists correspond to which development stages.",
      },
      {
        step: "Define creation and sync triggers",
        description:
          "Specify which Trello list moves trigger Linear issue creation, how Trello checklist items map to Linear issue titles, and which Linear state changes should update the Trello card.",
      },
      {
        step: "Keep roadmap and sprint board aligned automatically",
        description:
          "GAIA handles all cross-tool updates from that point. Product managers work in Trello, engineers work in Linear, and both boards stay synchronized without anyone manually managing the connection.",
      },
    ],
    faqs: [
      {
        question: "Can one Trello card be linked to multiple Linear issues?",
        answer:
          "Yes, this is the typical use case. A single Trello roadmap card often represents a feature that requires multiple engineering tasks. GAIA tracks all linked Linear issues and rolls up their status to the Trello card automatically.",
      },
      {
        question: "Does GAIA work with Trello Power-Ups?",
        answer:
          "GAIA operates through the Trello API and works alongside existing Power-Ups without conflict. It uses standard Trello card fields, custom fields, and comments, so it is compatible with most popular Trello Power-Up configurations.",
      },
      {
        question: "What if we move a Trello card back to a previous list?",
        answer:
          "GAIA detects backward movement and can optionally reopen the corresponding Linear issues or add a comment to notify the engineering team. You configure whether regressions should trigger automatic actions or just log a notification.",
      },
    ],
  },

  "linear-figma": {
    slug: "linear-figma",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline:
      "Link Figma designs to Linear issues and notify designers of engineering updates",
    metaTitle:
      "Linear + Figma Integration - Design and Engineering in Sync | GAIA",
    metaDescription:
      "Connect Linear and Figma with GAIA. Automatically attach Figma frame links to Linear issues, notify designers when implementation starts, and surface design feedback directly in your issue tracker.",
    keywords: [
      "Linear Figma integration",
      "Linear Figma sync",
      "attach Figma to Linear",
      "design engineering workflow",
      "Linear Figma automation",
      "connect Linear and Figma",
      "design handoff automation",
    ],
    intro:
      "Design handoffs between Figma and Linear are a perennial source of friction. Engineers hunt through Figma for the right frame version. Designers have no visibility into whether their specifications are being implemented correctly or when implementation is underway. Comments about design discrepancies live in two separate tools and never reach the right person.\n\nGAIA creates a live connection between Figma and Linear so that designs and implementation tasks are always paired. When an engineer creates a Linear issue for a feature, GAIA can link the relevant Figma frame automatically. When a designer publishes a new version, GAIA notifies the engineering team. When an engineer marks a design issue in Linear, GAIA can route the feedback directly to the Figma comment thread.\n\nThis integration is most valuable for product teams running fast design-development cycles where misaligned expectations between design and engineering add unnecessary rework.",
    useCases: [
      {
        title: "Auto-attach Figma frames to Linear issues",
        description:
          "When a new Linear issue is tagged with the design label, GAIA searches the connected Figma project for matching frames by name and attaches the direct link, so engineers always have the correct design reference without asking the design team.",
      },
      {
        title: "Notify engineers when Figma designs are updated",
        description:
          "When a designer publishes a new version of a Figma frame linked to an active Linear issue, GAIA adds a comment to the Linear issue flagging the update and summarizing what changed so engineers know to review the latest specs.",
      },
      {
        title: "Alert designers when implementation begins",
        description:
          "When a Linear issue moves from To Do to In Progress, GAIA notifies the designer listed in the Figma file that engineering has started implementation, giving them a window to catch any last-minute spec issues before code is written.",
      },
      {
        title: "Route Linear design feedback to Figma comments",
        description:
          "When an engineer adds a comment on a Linear issue that references a design discrepancy, GAIA posts the feedback as a comment in the linked Figma frame so designers receive it in their native tool without checking Linear.",
      },
      {
        title: "Track design review status in Linear",
        description:
          "GAIA monitors Figma for design approval annotations and updates the corresponding Linear issue status to Design Approved automatically, keeping the issue workflow accurate without requiring designers to update Linear manually.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Figma and Linear to GAIA",
        description:
          "Authorize GAIA with your Figma account and Linear workspace. Map Figma projects to Linear teams so GAIA knows which Figma files are associated with which engineering workflows.",
      },
      {
        step: "Define naming conventions and trigger rules",
        description:
          "Set the naming patterns GAIA should use to match Figma frames to Linear issues, which Linear labels or states should trigger designer notifications, and how design feedback comments should be forwarded.",
      },
      {
        step: "Design and build in parallel with full visibility",
        description:
          "GAIA maintains the link between design and implementation automatically. Designers see when their work enters development. Engineers always have the latest design specs. Feedback flows between tools without manual forwarding.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA match Figma frames to Linear issues automatically?",
        answer:
          "GAIA uses configurable matching rules — by default it looks for Figma frames whose names match the Linear issue title or ID. You can also link them explicitly by pasting a Figma URL into a Linear issue, which GAIA registers as the canonical design reference.",
      },
      {
        question: "Can GAIA embed Figma previews directly in Linear?",
        answer:
          "GAIA attaches Figma frame links to Linear issues. Linear natively renders Figma URLs as previews, so engineers see a design thumbnail inline in the issue without leaving their workflow.",
      },
      {
        question: "Does GAIA work with Figma branches for design versioning?",
        answer:
          "Yes. GAIA can be configured to track a specific Figma branch and notify engineers when that branch is merged, signaling that the final approved designs are ready for implementation.",
      },
    ],
  },

  "linear-discord": {
    slug: "linear-discord",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline: "Post Linear issue updates to dev Discord channels automatically",
    metaTitle:
      "Linear + Discord Integration - Engineering Updates in Your Dev Server | GAIA",
    metaDescription:
      "Connect Linear and Discord with GAIA. Automatically post Linear issue updates, sprint completions, and blocker alerts to your Discord engineering channels so the team stays informed without checking Linear.",
    keywords: [
      "Linear Discord integration",
      "Linear Discord notifications",
      "Linear Discord bot",
      "engineering Discord automation",
      "Linear Discord webhook",
      "connect Linear and Discord",
      "post Linear updates to Discord",
    ],
    intro:
      "Engineering teams that use Discord as their primary communication platform often miss Linear updates because important context stays siloed in the issue tracker. An issue moving to Blocked has no way to interrupt the Discord conversation. A sprint completing with a great velocity goes unannounced. New issues assigned to engineers sit unread while the team chats in Discord.\n\nGAIA brings Linear into Discord by routing the right events to the right channels automatically. High-priority issues get announced in the engineering channel. Blockers alert the relevant team leads. Sprint completions trigger automated summaries. Engineers can even create and update Linear issues directly from Discord commands without switching tools.\n\nThis integration is particularly valuable for remote-first engineering teams that treat Discord as their virtual office and want Linear activity to surface there naturally rather than requiring constant tab-switching.",
    useCases: [
      {
        title: "Post issue assignments to personal Discord DMs",
        description:
          "When a Linear issue is assigned to an engineer, GAIA sends them a Discord DM with the issue title, priority, description, and a direct link so they are notified immediately in the tool they are already using.",
      },
      {
        title: "Announce sprint completions to the engineering channel",
        description:
          "When a Linear cycle ends, GAIA posts a formatted sprint summary to the designated Discord channel showing issues completed, carry-over, team velocity, and top contributors to celebrate the team's work.",
      },
      {
        title: "Alert the team to new high-priority issues",
        description:
          "When a Linear issue is created or upgraded to Urgent priority, GAIA immediately posts an alert to the engineering Discord channel with full context so the team can react and assign it without delay.",
      },
      {
        title: "Post blocker alerts to the leads channel",
        description:
          "When a Linear issue transitions to Blocked, GAIA sends a structured alert to the team leads Discord channel including the blocking dependency, the affected engineer, and the issue's current due date so blockers are resolved quickly.",
      },
      {
        title: "Create Linear issues from Discord commands",
        description:
          "Engineers can type a GAIA command in Discord to create a new Linear issue without leaving the chat. GAIA prompts for title, priority, and assignee, creates the issue, and posts the confirmation link back to the channel.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Linear and Discord to GAIA",
        description:
          "Authorize GAIA with your Linear workspace and invite the GAIA bot to your Discord server. Map Linear teams to Discord channels during setup.",
      },
      {
        step: "Configure notification rules and channel routing",
        description:
          "Choose which Linear events generate Discord notifications, which channels should receive which event types, and the format of notification messages.",
      },
      {
        step: "Linear activity flows into Discord automatically",
        description:
          "GAIA monitors Linear for the configured events and posts formatted updates to the right Discord channels in real time. The team stays informed without leaving Discord.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA send Linear notifications to different Discord channels based on the team or project?",
        answer:
          "Yes. You can configure channel routing rules so that Linear Team A notifications go to #team-alpha and Team B notifications go to #team-beta. You can also route by event type, priority, or label.",
      },
      {
        question:
          "Can engineers interact with Linear issues directly from Discord?",
        answer:
          "Yes. GAIA supports Discord slash commands for common Linear actions including creating issues, updating status, adding comments, and querying the current sprint state. Responses are posted in-thread so the channel stays clean.",
      },
      {
        question: "How does GAIA handle Discord notification fatigue?",
        answer:
          "You control the event filters. Most teams configure GAIA to notify only on priority thresholds (e.g., Urgent and High only), specific labels, or specific issue state transitions rather than every Linear event. This keeps Discord signal-to-noise high.",
      },
    ],
  },

  "linear-drive": {
    slug: "linear-drive",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Attach design docs and specs from Google Drive to Linear issues automatically",
    metaTitle:
      "Linear + Google Drive Integration - Docs Attached to Engineering Issues | GAIA",
    metaDescription:
      "Connect Linear and Google Drive with GAIA. Automatically attach relevant Drive documents to Linear issues, create spec docs from issue descriptions, and keep engineering documentation linked to the work it supports.",
    keywords: [
      "Linear Google Drive integration",
      "Linear Drive automation",
      "attach docs to Linear issues",
      "engineering documentation workflow",
      "Linear Drive sync",
      "connect Linear and Google Drive",
      "spec doc Linear automation",
    ],
    intro:
      "Engineering issues rarely exist in isolation. Behind most Linear issues is a Google Drive folder full of context: the product spec, the design doc, the API contract, the meeting notes from the scoping session. But that context lives in Drive while the issue lives in Linear, and the link between them is usually an afterthought — a URL pasted into a comment that gets buried, or nothing at all.\n\nGAIA builds and maintains the connection between Drive documents and Linear issues automatically. When a new feature issue is created in Linear, GAIA searches the configured Drive folder for matching spec documents and attaches them. When a new spec doc is created in Drive and follows your team's naming convention, GAIA creates the corresponding Linear issue and links back to the doc.\n\nThis integration eliminates the document hunt that slows down engineers at the start of every task and ensures that the historical context behind an issue is always one click away.",
    useCases: [
      {
        title: "Auto-attach Drive spec docs to Linear issues",
        description:
          "When a new Linear issue is created with the feature label, GAIA searches the product specs folder in Drive for a document matching the issue title and attaches the link automatically so engineers have immediate access to the specification.",
      },
      {
        title: "Create Linear issues from new Drive spec docs",
        description:
          "When a new spec document is added to the designated Drive folder and marked Ready for Engineering, GAIA creates a corresponding Linear issue with the document title, a description pulled from the doc summary, and a link back to Drive.",
      },
      {
        title: "Attach meeting notes to related Linear issues",
        description:
          "When a Google Doc meeting note is created after an engineering planning session and contains Linear issue IDs in the title or body, GAIA attaches the note to each referenced issue so decision context is preserved.",
      },
      {
        title: "Generate post-mortem docs in Drive from Linear incidents",
        description:
          "When a Linear issue labeled incident is resolved, GAIA creates a post-mortem document in the designated Drive folder pre-populated with the issue title, timeline, and description so the team can fill in the analysis without starting from scratch.",
      },
      {
        title: "Organize Drive docs by Linear project",
        description:
          "GAIA maintains a Drive folder structure mirroring your Linear projects. When an issue is created in a Linear project, GAIA creates a corresponding subfolder in Drive so all related documents are organized consistently without manual folder management.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Drive and Linear to GAIA",
        description:
          "Authorize GAIA with your Google Workspace account and Linear workspace. Designate the Drive folders GAIA should watch and search, and map them to Linear teams or projects.",
      },
      {
        step: "Configure matching rules and triggers",
        description:
          "Define the naming conventions GAIA should use to match Drive documents to Linear issues, which Drive events should create Linear issues, and which Linear events should create Drive documents.",
      },
      {
        step: "Documentation attaches to issues automatically",
        description:
          "GAIA monitors both platforms and maintains the links between issues and documents in real time. Engineers find their specs in Linear; documents in Drive always reference their related issues.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA require a specific naming convention for Drive documents?",
        answer:
          "GAIA works best with consistent naming conventions but can also be configured with flexible matching patterns using regular expressions. You can also link Drive documents to Linear issues manually and GAIA will register and maintain those explicit links.",
      },
      {
        question:
          "Can GAIA attach shared Drive files or only files owned by me?",
        answer:
          "GAIA can attach any Drive file that the authorized Google account has access to, including shared drives and files shared with your domain. It respects existing Drive sharing permissions and does not change access settings.",
      },
      {
        question:
          "What file types does GAIA support when attaching Drive files to Linear?",
        answer:
          "GAIA can attach links to any Drive file type including Google Docs, Sheets, Slides, and uploaded PDFs, images, or other files. Linear renders the attached URLs with metadata previews for Google Workspace file types.",
      },
    ],
  },

  "linear-hubspot": {
    slug: "linear-hubspot",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "HubSpot",
    toolBSlug: "hubspot",
    tagline:
      "Link customer feature requests from HubSpot to Linear engineering issues",
    metaTitle:
      "Linear + HubSpot Integration - Customer Requests Drive Engineering | GAIA",
    metaDescription:
      "Connect Linear and HubSpot with GAIA. Automatically create Linear issues from HubSpot customer feature requests, link deals to issues, and notify sales when engineering ships customer-requested features.",
    keywords: [
      "Linear HubSpot integration",
      "Linear HubSpot sync",
      "customer requests to Linear",
      "HubSpot Linear automation",
      "connect Linear and HubSpot",
      "feature request workflow automation",
      "CRM engineering issue link",
    ],
    intro:
      "Customer-facing teams log feature requests and bug reports in HubSpot every day. Engineering tracks their work in Linear. But the path from a HubSpot contact's request to a Linear issue on the sprint board is almost always a manual one — someone reads CRM notes, decides it is worth building, creates a Linear issue, and then forgets to update HubSpot when the feature ships.\n\nGAIA closes the loop between customer feedback and engineering delivery. When a HubSpot deal or ticket contains a feature request that meets your threshold for engineering consideration, GAIA creates the Linear issue with full customer context attached. When engineering ships the feature in Linear, GAIA updates HubSpot and notifies the account owner so they can follow up with the customer.\n\nThis integration is most impactful for B2B SaaS teams where engineering prioritization is influenced by customer revenue potential and where sales and customer success teams need visibility into when requested features ship.",
    useCases: [
      {
        title: "Create Linear issues from HubSpot feature request tickets",
        description:
          "When a HubSpot support ticket is tagged as Feature Request and meets your minimum deal-value threshold, GAIA creates a Linear issue with the customer context, associated deal value, and HubSpot ticket link so engineering has all the information needed to evaluate and prioritize.",
      },
      {
        title: "Notify account owners when features ship",
        description:
          "When a Linear issue linked to a HubSpot deal is marked Done, GAIA creates a HubSpot activity on the deal notifying the account owner that the requested feature has shipped, giving them a timely reason to reach out to the customer.",
      },
      {
        title: "Aggregate customer demand to prioritize Linear backlog",
        description:
          "GAIA counts how many HubSpot contacts have requested a given feature and writes that demand count to the corresponding Linear issue's metadata. Product teams can sort the Linear backlog by customer demand to inform sprint prioritization.",
      },
      {
        title: "Link HubSpot bug reports to existing Linear issues",
        description:
          "When a customer reports a bug in HubSpot that matches an already-open Linear issue by keyword or description similarity, GAIA links the HubSpot ticket to the existing issue and increments an affected-customers counter rather than creating duplicates.",
      },
      {
        title: "Update HubSpot deal stage when engineering milestones are hit",
        description:
          "When a Linear project associated with a HubSpot opportunity reaches a configurable completion percentage, GAIA moves the deal to the relevant pipeline stage — such as Feature In Beta — so sales stays in sync with engineering progress.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Linear to GAIA",
        description:
          "Authorize GAIA with your HubSpot portal and Linear workspace. Define which HubSpot deal stages, ticket types, or properties should trigger Linear issue creation.",
      },
      {
        step: "Configure customer context mapping",
        description:
          "Map HubSpot deal properties — company name, ARR, contact owner — to Linear issue fields or labels so engineering always sees the business context behind a feature request.",
      },
      {
        step: "Close the loop between customers and engineering",
        description:
          "GAIA monitors both platforms and propagates updates in both directions. Sales knows when features ship. Engineering knows how much customer demand backs each backlog item.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA filter which HubSpot tickets create Linear issues based on deal value?",
        answer:
          "Yes. You can set a minimum associated deal value threshold so only feature requests from accounts above a certain ARR generate Linear issues automatically. Requests below the threshold are logged in GAIA's queue for manual review.",
      },
      {
        question:
          "How does GAIA avoid creating duplicate Linear issues when multiple customers report the same request?",
        answer:
          "GAIA uses semantic similarity matching to identify Linear issues that likely correspond to an incoming HubSpot request. If a match above your configured confidence threshold exists, GAIA links the HubSpot ticket to the existing issue and increments the demand count rather than creating a duplicate.",
      },
      {
        question:
          "Does GAIA sync back to HubSpot when a Linear issue is partially complete, or only when Done?",
        answer:
          "You can configure sync triggers for any Linear state transition. Common configurations notify HubSpot at In Review (feature in beta) and Done (feature shipped), giving account owners two touchpoints to manage customer expectations.",
      },
    ],
  },

  "linear-zoom": {
    slug: "linear-zoom",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline:
      "Schedule sprint ceremonies and post Zoom summaries to Linear issues automatically",
    metaTitle:
      "Linear + Zoom Integration - Sprint Meetings Meet Issue Tracking | GAIA",
    metaDescription:
      "Connect Linear and Zoom with GAIA. Automatically schedule sprint ceremonies from Linear cycle dates, post Zoom meeting summaries to Linear issues, and capture action items as new issues.",
    keywords: [
      "Linear Zoom integration",
      "Linear Zoom automation",
      "sprint ceremony scheduling",
      "Zoom meeting summary Linear",
      "connect Linear and Zoom",
      "engineering meeting automation",
      "Linear Zoom workflow",
    ],
    intro:
      "Engineering sprint ceremonies — planning, standup, review, retrospective — happen in Zoom. The action items, decisions, and issue updates from those meetings should live in Linear. But capturing that context from a Zoom call and getting it back into Linear requires someone to take notes, identify action items, and manually create or update Linear issues after every meeting. That process is rarely done consistently.\n\nGAIA automates the connection between Zoom meetings and Linear by scheduling ceremonies automatically from cycle dates, transcribing and summarizing meetings, and extracting action items as new Linear issues. The team gets a meeting record attached to the right sprint without anyone spending time on post-meeting admin.\n\nThis integration is ideal for remote engineering teams that run all their ceremonies over Zoom and want the insights from those meetings captured in Linear automatically rather than lost in meeting notes that nobody reads.",
    useCases: [
      {
        title: "Auto-schedule sprint ceremonies from Linear cycles",
        description:
          "When a new Linear cycle is created, GAIA schedules recurring Zoom meetings for sprint planning, daily standup, sprint review, and retrospective based on the cycle dates and the team's configured ceremony cadence.",
      },
      {
        title: "Post Zoom meeting summaries to Linear cycles",
        description:
          "After a sprint ceremony ends on Zoom, GAIA generates a meeting summary using the transcript and attaches it as a comment on the corresponding Linear cycle so the team has a searchable record of what was discussed.",
      },
      {
        title: "Create Linear issues from Zoom action items",
        description:
          "GAIA identifies action items in Zoom meeting transcripts — commitments, follow-up tasks, blockers raised — and creates corresponding Linear issues assigned to the relevant team member with the meeting context as the issue description.",
      },
      {
        title: "Add Zoom recording links to Linear issues",
        description:
          "After a Zoom call that references specific Linear issues by ID, GAIA attaches the Zoom recording link to each mentioned issue so engineers can review the conversation context without asking for the recording link.",
      },
      {
        title: "Generate sprint review agenda from Linear cycle",
        description:
          "Before the sprint review Zoom meeting, GAIA generates an agenda document listing all completed Linear issues with their titles and descriptions, ready to share as a Zoom meeting document so the team can walk through shipped work systematically.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Linear to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Linear workspace. Configure the ceremony types, their default durations, and the Zoom meeting settings GAIA should use when scheduling.",
      },
      {
        step: "Map ceremony types to Linear events",
        description:
          "Tell GAIA which Linear cycle events should trigger which Zoom meeting types and where meeting summaries and action items should be posted in Linear.",
      },
      {
        step: "Sprint ceremonies schedule and document themselves",
        description:
          "GAIA creates Zoom meetings when cycles start, joins the meetings to capture transcripts, and posts summaries and action items to Linear automatically after each ceremony ends.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA join Zoom meetings automatically or only if invited?",
        answer:
          "GAIA joins meetings it schedules automatically. For meetings you schedule independently, you can invite GAIA's Zoom participant link and it will join, transcribe, and post a summary to your configured Linear destination.",
      },
      {
        question:
          "How accurate is GAIA's action item extraction from Zoom transcripts?",
        answer:
          "GAIA uses structured prompt analysis on Zoom transcripts to identify action items with high confidence. It flags extracted items for human review before creating Linear issues, so you can approve, edit, or discard each one before it enters the backlog.",
      },
      {
        question:
          "Can GAIA schedule Zoom meetings based on team members' calendar availability?",
        answer:
          "Yes. When connected to Google Calendar or Outlook, GAIA checks team member availability before scheduling ceremony times and picks the slot with the best attendance overlap within your configured working hours.",
      },
    ],
  },

  "linear-airtable": {
    slug: "linear-airtable",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Airtable",
    toolBSlug: "airtable",
    tagline: "Sync engineering metrics and issue data to Airtable dashboards",
    metaTitle:
      "Linear + Airtable Integration - Engineering Metrics in Airtable | GAIA",
    metaDescription:
      "Connect Linear and Airtable with GAIA. Automatically sync Linear issues and sprint metrics to Airtable bases, build engineering dashboards, and give non-technical stakeholders a structured view of engineering output.",
    keywords: [
      "Linear Airtable integration",
      "Linear Airtable sync",
      "engineering metrics Airtable",
      "Linear Airtable dashboard",
      "connect Linear and Airtable",
      "sync Linear to Airtable",
      "sprint metrics automation",
    ],
    intro:
      "Linear is purpose-built for engineering teams. Airtable is purpose-built for structured data that non-technical stakeholders can query, filter, and build views on. The two serve different audiences, but the data that lives in Linear — issue counts, cycle velocity, lead times, label breakdowns — is exactly what operations, finance, and product leadership want to analyze in Airtable.\n\nGAIA syncs Linear data to Airtable automatically so dashboards stay current without anyone manually exporting CSVs. Engineering metrics flow into Airtable bases where stakeholders can build the views, formulas, and reports they need without accessing Linear. When an issue is created, updated, or completed in Linear, Airtable reflects the change in real time.\n\nThis integration is particularly useful for ops teams that track engineering KPIs alongside other business metrics in Airtable, and for companies that use Airtable as their source of truth for cross-functional reporting.",
    useCases: [
      {
        title: "Mirror Linear issues to an Airtable issues base",
        description:
          "GAIA creates a row in Airtable for each Linear issue in your configured scope, keeping fields like status, assignee, priority, label, and cycle synchronized so stakeholders can query, filter, and group issues without Linear access.",
      },
      {
        title: "Sync cycle metrics to an engineering KPIs base",
        description:
          "At the end of each Linear cycle, GAIA appends a new record to the engineering KPIs Airtable base with velocity, completion rate, carry-over percentage, and average cycle time so leadership can track engineering health over time.",
      },
      {
        title: "Build bug triage views in Airtable",
        description:
          "GAIA syncs all Linear issues labeled bug to a dedicated Airtable base where the support team can add triage notes, customer impact ratings, and reproduction steps that live alongside the engineering issue data without cluttering Linear.",
      },
      {
        title: "Track feature delivery commitments in Airtable",
        description:
          "GAIA syncs Linear issues linked to committed features to an Airtable tracking base. Stakeholders see target cycle, current status, and actual delivery date in a format they can embed in executive reports.",
      },
      {
        title: "Aggregate team capacity data for resource planning",
        description:
          "GAIA writes assigned issue counts, story points, and cycle allocations per engineer to an Airtable resource planning base so ops and engineering management can model capacity without manual data collection.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Linear and Airtable to GAIA",
        description:
          "Authorize GAIA with your Linear workspace and Airtable account. Select or create the Airtable base and tables that should receive Linear data.",
      },
      {
        step: "Map Linear fields to Airtable columns",
        description:
          "Define which Linear issue properties map to which Airtable columns. GAIA supports all standard Linear fields as well as custom fields and will create Airtable columns for any that do not already exist.",
      },
      {
        step: "Airtable stays current as Linear changes",
        description:
          "GAIA monitors Linear for issue changes and propagates them to Airtable in near real time. Stakeholders always see current data in their Airtable views without anyone running exports.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA sync historical Linear issues or only new activity?",
        answer:
          "On initial setup, GAIA performs a historical backfill of all existing Linear issues within your configured scope. Going forward, new issues and updates sync in near real time.",
      },
      {
        question:
          "Can Airtable team members update rows and have those changes reflected back in Linear?",
        answer:
          "Bidirectional sync is supported for a limited set of fields — primarily status and assignee. For most teams, Linear is treated as the authoritative source and Airtable is read-optimized, but you can enable write-back for specific columns during setup.",
      },
      {
        question: "How does GAIA handle Linear issues that are deleted?",
        answer:
          "When a Linear issue is deleted, GAIA marks the corresponding Airtable row as archived rather than deleting it, so your historical reporting data is preserved. You can configure hard deletion if your data retention policy requires it.",
      },
    ],
  },

  "linear-stripe": {
    slug: "linear-stripe",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Stripe",
    toolBSlug: "stripe",
    tagline:
      "Link payment bugs to Linear and prioritize issues by revenue impact",
    metaTitle:
      "Linear + Stripe Integration - Revenue-Aware Engineering Prioritization | GAIA",
    metaDescription:
      "Connect Linear and Stripe with GAIA. Automatically create Linear issues from Stripe payment failures, attach revenue context to bugs, and surface the engineering issues with the highest customer impact.",
    keywords: [
      "Linear Stripe integration",
      "Linear Stripe automation",
      "payment bug Linear issue",
      "revenue impact engineering prioritization",
      "connect Linear and Stripe",
      "Stripe error Linear workflow",
      "payment failure issue tracking",
    ],
    intro:
      "Payment failures and billing edge cases discovered in Stripe often lack a clear path to the engineering team. A spike in failed charges that surfaces in the Stripe dashboard requires someone to notice it, decide it is an engineering problem, find the right Linear team, and create an issue with enough context to act on. That chain of manual steps means payment issues sit unresolved longer than they should.\n\nGAIA connects Stripe to Linear so payment-related engineering issues are created automatically with full financial context. When Stripe detects a spike in payment failures, a webhook error, or a subscription lifecycle issue, GAIA creates a Linear issue with the Stripe event data, affected customer count, and estimated revenue impact so engineers can prioritize it accurately.\n\nThis integration is most valuable for SaaS companies where payment reliability is directly tied to revenue and where engineering prioritization should reflect the business impact of technical issues.",
    useCases: [
      {
        title: "Create Linear issues from Stripe payment failure spikes",
        description:
          "When Stripe's failure rate for a given payment method or error code exceeds a configurable threshold, GAIA creates a high-priority Linear issue with the error breakdown, affected customer count, and estimated revenue at risk.",
      },
      {
        title: "Link Stripe webhook failures to Linear bugs",
        description:
          "When Stripe reports repeated webhook delivery failures to your endpoint, GAIA creates a Linear bug with the failing event types, response codes, and a timeline of failures so engineering can diagnose and resolve the integration issue quickly.",
      },
      {
        title: "Attach revenue impact to existing Linear payment issues",
        description:
          "For Linear issues already tagged with a payment label, GAIA queries Stripe for related error events and attaches an estimated revenue impact figure derived from the affected customers' MRR so product teams can prioritize by business value.",
      },
      {
        title: "Alert engineering when Stripe disputes spike",
        description:
          "When Stripe dispute volume exceeds a weekly threshold, GAIA creates a Linear investigation issue with a breakdown of the dispute reasons and amounts so the engineering team can identify whether a code change caused the increase.",
      },
      {
        title: "Close Linear issues when Stripe errors resolve",
        description:
          "When a payment error pattern that triggered a Linear issue returns to baseline in Stripe, GAIA adds a resolution comment to the Linear issue and moves it to Done automatically so resolved payment issues do not linger in the backlog.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Stripe and Linear to GAIA",
        description:
          "Authorize GAIA with your Stripe account and Linear workspace. Configure the Stripe event types and error thresholds that should trigger Linear issue creation.",
      },
      {
        step: "Set revenue impact thresholds and routing rules",
        description:
          "Define the minimum failure rate or revenue impact that warrants a Linear issue, which Linear team should receive payment issues, and how Stripe customer data should be summarized in issue descriptions.",
      },
      {
        step: "Payment issues surface in Linear with business context",
        description:
          "GAIA monitors Stripe events and creates Linear issues automatically when thresholds are crossed. Engineers see the financial impact of payment bugs in their issue tracker and can prioritize accordingly.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA include customer PII from Stripe in Linear issues?",
        answer:
          "No. GAIA is configured to exclude personally identifiable information by default. Linear issues receive aggregate statistics — affected customer count, total revenue at risk, error code distribution — without individual customer names, emails, or payment details.",
      },
      {
        question:
          "Can GAIA distinguish between transient Stripe errors and persistent bugs?",
        answer:
          "Yes. GAIA applies a configurable time-window filter so single transient errors do not create Linear issues. A Linear issue is created only when error rates persist above your threshold across a defined window — for example, a 5% failure rate sustained for 10 minutes.",
      },
      {
        question:
          "What Stripe events does GAIA monitor beyond payment failures?",
        answer:
          "GAIA can monitor any Stripe webhook event including subscription lifecycle events, dispute creation, payout failures, and refund spikes. You configure which event types are relevant for your engineering team during setup.",
      },
    ],
  },

  "jira-notion": {
    slug: "jira-notion",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline:
      "Sync Jira epics to Notion project pages and document sprint retros automatically",
    metaTitle:
      "Jira + Notion Integration - Issue Tracking Meets Documentation | GAIA",
    metaDescription:
      "Connect Jira and Notion with GAIA. Automatically sync Jira epics to Notion project pages, populate sprint retrospective templates, and keep engineering documentation linked to active Jira work.",
    keywords: [
      "Jira Notion integration",
      "Jira Notion sync",
      "sync Jira to Notion",
      "sprint retrospective automation",
      "Jira Notion workflow",
      "connect Jira and Notion",
      "engineering documentation Jira",
    ],
    intro:
      "Jira and Notion serve different but complementary roles in a product engineering organization. Jira tracks the executable: stories, bugs, sprints, and releases. Notion holds the interpretive: specs, ADRs, retros, and project narratives. The problem is that the two rarely stay in sync. Sprint retro templates sit empty in Notion while the data exists in Jira. Epic docs in Notion go stale while the actual work evolves in Jira.\n\nGAIA keeps Jira and Notion synchronized without requiring anyone to manually copy data between them. When a Jira epic is created, GAIA scaffolds a Notion project page with the epic context. When a sprint ends, GAIA populates the Notion retro template with data pulled from Jira. When an epic is marked complete in Jira, the Notion page reflects the final state.\n\nThis integration is most impactful for product engineering teams that invest in documentation quality and want Notion to always reflect what is actually happening in Jira rather than representing a snapshot from the last time someone remembered to update it.",
    useCases: [
      {
        title: "Scaffold Notion project pages from Jira epics",
        description:
          "When a new Jira epic is created, GAIA creates a corresponding Notion project page pre-populated with the epic name, description, acceptance criteria, and a linked table of child stories so the team has a documentation home for the feature from day one.",
      },
      {
        title: "Auto-populate sprint retrospective templates",
        description:
          "At the end of each Jira sprint, GAIA fills the team's Notion retro template with sprint metrics — stories completed, velocity, carry-over, and bugs closed — so the retrospective meeting can focus on insights rather than data gathering.",
      },
      {
        title: "Embed live Jira story status in Notion specs",
        description:
          "GAIA maintains a synchronized table in each Notion epic page showing the current status of all linked Jira stories. Product managers and designers can see engineering progress directly in the spec document without accessing Jira.",
      },
      {
        title: "Create Jira epics from Notion product briefs",
        description:
          "When a Notion product brief is tagged Ready for Engineering, GAIA creates a Jira epic and its child stories from the brief's requirements section, linking each Jira item back to the Notion source document.",
      },
      {
        title: "Update Notion release notes when Jira versions ship",
        description:
          "When a Jira version or release is marked as released, GAIA appends the included stories and bug fixes to the team's Notion release notes page in a formatted, user-facing changelog entry.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Notion to GAIA",
        description:
          "Authorize GAIA with your Jira project and Notion workspace. Map Jira projects to Notion databases or page hierarchies during setup.",
      },
      {
        step: "Configure sync rules and template mappings",
        description:
          "Specify which Jira events trigger Notion page creation or updates, which Notion page templates should be used for epics and retros, and how Jira fields should map to Notion page properties.",
      },
      {
        step: "Documentation and issues stay synchronized",
        description:
          "GAIA monitors both tools and applies updates automatically. Notion pages reflect the current state of Jira work, and Jira epics can be seeded from Notion product briefs.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync Jira subtasks to Notion or only epics and stories?",
        answer:
          "GAIA supports configurable depth. You can sync only epics, epics and stories, or the full epic-story-subtask hierarchy to Notion. Most teams sync epics and stories to keep Notion at a strategic level while leaving tactical subtask details in Jira.",
      },
      {
        question:
          "Will GAIA overwrite content I write manually in a Notion page?",
        answer:
          "GAIA writes only to dedicated sections and database properties it manages. Free-form content you add to a Notion page is never modified. GAIA uses clearly marked blocks and properties to separate its automated content from your manual additions.",
      },
      {
        question:
          "Does GAIA support Jira Service Management projects as well as Software projects?",
        answer:
          "Yes. GAIA supports both Jira Software and Jira Service Management. For service management projects, GAIA can sync incident and request data to Notion knowledge base pages and post-mortem templates.",
      },
    ],
  },

  "jira-todoist": {
    slug: "jira-todoist",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Todoist",
    toolBSlug: "todoist",
    tagline:
      "Create personal Todoist tasks from Jira issues and sync completions back",
    metaTitle:
      "Jira + Todoist Integration - Jira Issues in Your Personal Task List | GAIA",
    metaDescription:
      "Connect Jira and Todoist with GAIA. Automatically create Todoist tasks when Jira issues are assigned to you, sync completions back to Jira, and manage your engineering workload alongside personal tasks.",
    keywords: [
      "Jira Todoist integration",
      "Jira Todoist sync",
      "Jira issues to Todoist",
      "personal task management Jira",
      "Jira Todoist automation",
      "connect Jira and Todoist",
      "engineer productivity Jira",
    ],
    intro:
      "Engineers who use Todoist as their personal task hub face a daily friction: Jira is where assignments live, Todoist is where they plan their day, and keeping both aligned requires constant manual effort. An issue assigned in Jira needs to be manually added to Todoist. A task completed in Todoist needs to be manually marked done in Jira. Over time, the two fall out of sync and engineers either abandon Todoist or lose trust in Jira.\n\nGAIA eliminates this friction by bridging Jira and Todoist automatically. When a Jira issue is assigned to you, GAIA creates the corresponding Todoist task with the right project, priority, and due date. When you complete it in Todoist, GAIA transitions the Jira issue to Done. You manage your day in Todoist and your team sees accurate status in Jira.\n\nThis integration is ideal for engineers who value a personal task management system that gives them a unified view of all their work — code reviews, meetings, errands, and Jira tickets — in one place.",
    useCases: [
      {
        title: "Auto-create Todoist tasks from Jira assignments",
        description:
          "When a Jira issue is assigned to you, GAIA immediately creates a matching Todoist task with the issue summary, priority, due date, and a direct link to Jira so your personal task list is always current.",
      },
      {
        title: "Sync Todoist completions back to Jira",
        description:
          "When you check off a Jira-linked task in Todoist, GAIA transitions the corresponding Jira issue to your configured Done state so the team board stays accurate without requiring you to open Jira.",
      },
      {
        title: "Map Jira projects to Todoist projects",
        description:
          "GAIA routes Jira assignments to the appropriate Todoist project based on the Jira project key, keeping your engineering work organized separately from personal tasks in your Todoist workspace.",
      },
      {
        title: "Surface overdue Jira issues as urgent Todoist tasks",
        description:
          "When a Jira issue assigned to you passes its due date without being resolved, GAIA creates or updates the Todoist task with urgent priority and an overdue flag so it surfaces prominently in your daily planning.",
      },
      {
        title: "Daily Jira queue review task in Todoist",
        description:
          "Each morning GAIA creates a Todoist task with a summary of your Jira queue — issues in progress, upcoming due dates, and new assignments — so you start the day with a prioritized view of your Jira workload.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Todoist to GAIA",
        description:
          "Authorize GAIA with your Jira account and Todoist account. GAIA identifies your Jira user and maps your assignments to your Todoist workspace.",
      },
      {
        step: "Configure project mapping and completion sync",
        description:
          "Map Jira project keys to Todoist projects, set the Jira transition that a Todoist completion should trigger, and choose whether GAIA should sync bidirectionally or only from Jira to Todoist.",
      },
      {
        step: "Manage your workload in Todoist with Jira staying current",
        description:
          "GAIA creates Todoist tasks as you receive Jira assignments and syncs completions back automatically. You plan your day in Todoist while your team sees real-time status in Jira.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA create Todoist tasks for all Jira issues in my project or only assignments?",
        answer:
          "By default GAIA creates Todoist tasks only for Jira issues assigned to your user. You can optionally extend this to issues you are watching, issues in a specific sprint, or issues with a label you specify.",
      },
      {
        question:
          "What Jira transition does GAIA use when I complete a Todoist task?",
        answer:
          "During setup you choose which Jira workflow transition maps to Todoist task completion. For most teams this is the Done or Resolved transition, but you can map it to any transition in your project's workflow.",
      },
      {
        question:
          "Can I snooze or reschedule a Todoist task without affecting Jira?",
        answer:
          "Yes. Rescheduling, snoozing, adding subtasks, or editing the Todoist task title are local-only actions that do not affect Jira. Only task completion triggers a Jira status update.",
      },
    ],
  },

  "jira-clickup": {
    slug: "jira-clickup",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline:
      "Bridge Jira development tracking with ClickUp product planning seamlessly",
    metaTitle:
      "Jira + ClickUp Integration - Development and Product Planning in Sync | GAIA",
    metaDescription:
      "Connect Jira and ClickUp with GAIA. Automatically sync Jira stories to ClickUp tasks, propagate status updates across both tools, and eliminate manual handoffs between product and engineering teams.",
    keywords: [
      "Jira ClickUp integration",
      "Jira ClickUp sync",
      "sync Jira to ClickUp",
      "development product planning sync",
      "Jira ClickUp automation",
      "connect Jira and ClickUp",
      "product engineering workflow",
    ],
    intro:
      "Product teams that plan and track delivery in ClickUp often run into a wall when engineering uses Jira for day-to-day development. Each team has legitimate reasons for their tool preference, but the boundary between them creates a coordination overhead that neither team should have to manage manually. Status updates made in Jira do not appear in ClickUp. Requirements changed in ClickUp do not reach engineers in Jira.\n\nGAIA bridges Jira and ClickUp by syncing the relevant data in both directions automatically. Engineering progress in Jira flows to the ClickUp delivery board. Product requirement changes in ClickUp propagate to the corresponding Jira stories. Both teams work in their preferred tool and trust that the other side stays current.\n\nThis integration is particularly valuable for organizations that have standardized on ClickUp for company-wide project management but allow engineering to use Jira for its superior development tooling — Agile boards, sprint planning, and deep Atlassian ecosystem integrations.",
    useCases: [
      {
        title: "Sync Jira story status to ClickUp tasks",
        description:
          "When a Jira story moves to In Progress or Done, GAIA updates the linked ClickUp task status so product managers always see accurate development progress on their delivery boards without polling engineers.",
      },
      {
        title: "Create Jira stories from ClickUp feature tasks",
        description:
          "When a ClickUp feature task is approved and moved to Ready for Development, GAIA creates a corresponding Jira story with the task description, acceptance criteria, and priority already populated.",
      },
      {
        title: "Propagate ClickUp priority changes to Jira",
        description:
          "When a product manager changes a ClickUp task priority — for example, upgrading a feature from Medium to Critical — GAIA updates the priority of the linked Jira story and notifies the assigned engineer so they can adjust their sprint queue.",
      },
      {
        title: "Sync Jira sprint dates to ClickUp milestones",
        description:
          "GAIA reads Jira sprint start and end dates and creates or updates corresponding ClickUp milestones, keeping the product delivery timeline in ClickUp aligned with actual engineering sprints.",
      },
      {
        title: "Surface Jira blockers in ClickUp",
        description:
          "When a Jira story is marked as blocked, GAIA adds a comment to the linked ClickUp task summarizing the blocker so product managers can take cross-team action without waiting for engineering stand-up.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and ClickUp to GAIA",
        description:
          "Authorize GAIA with your Jira project and ClickUp workspace. Map Jira projects to ClickUp Spaces and Folders during initial configuration.",
      },
      {
        step: "Define field mappings and sync direction",
        description:
          "Map Jira workflow statuses to ClickUp task statuses, define which fields are authoritative in which tool, and configure which events should trigger cross-platform actions.",
      },
      {
        step: "Both tools stay synchronized automatically",
        description:
          "GAIA monitors both platforms for relevant changes and propagates updates in real time. Product managers work in ClickUp; engineers work in Jira; both boards always reflect the same current state.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA handle the Jira epic-story-subtask hierarchy versus ClickUp's task-subtask model?",
        answer:
          "GAIA maps Jira epics to ClickUp tasks and Jira stories to ClickUp subtasks by default, or you can map each level to a separate ClickUp hierarchy tier. The mapping is configurable to match your team's organizational conventions.",
      },
      {
        question: "Can GAIA sync Jira custom fields to ClickUp custom fields?",
        answer:
          "Yes. During setup you map Jira custom fields to corresponding ClickUp custom fields. GAIA handles type conversion — for example, mapping a Jira number field to a ClickUp numeric field — and logs any fields that cannot be mapped cleanly.",
      },
      {
        question:
          "What happens to ClickUp tasks that have no corresponding Jira story?",
        answer:
          "GAIA only syncs tasks that match your configured rules — typically tasks that have been explicitly linked or that match a trigger like being moved to a Ready for Development list. Unlinked ClickUp tasks are left untouched.",
      },
    ],
  },

  "jira-trello": {
    slug: "jira-trello",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline: "Sync Jira bugs to a Trello bug tracker board automatically",
    metaTitle:
      "Jira + Trello Integration - Bug Tracking Across Both Tools | GAIA",
    metaDescription:
      "Connect Jira and Trello with GAIA. Automatically sync Jira bugs to Trello bug tracker boards, keep status current in both tools, and give non-technical stakeholders visibility into bug resolution progress.",
    keywords: [
      "Jira Trello integration",
      "Jira Trello sync",
      "sync Jira bugs to Trello",
      "bug tracking workflow automation",
      "connect Jira and Trello",
      "Jira Trello automation",
      "bug board Trello Jira",
    ],
    intro:
      "Engineering teams track bugs in Jira because of its tight integration with sprint boards and version management. But non-technical stakeholders — support managers, product owners, customer success leads — often prefer Trello for its visual clarity and accessibility. When bug information lives only in Jira, the stakeholders who need to see it are locked out unless someone manually maintains a parallel Trello board.\n\nGAIA syncs Jira bugs to Trello automatically so stakeholders get the visual bug tracker they prefer while engineering continues working in Jira. New bugs in Jira appear as Trello cards. Status transitions in Jira move Trello cards across lists. When a bug is resolved, the Trello card updates automatically. Nobody has to maintain both boards.\n\nThis integration is most valuable for support and customer success teams that need visibility into bug resolution timelines without needing Jira access, and for organizations that want a lightweight external bug visibility board without investing in Jira dashboard configuration.",
    useCases: [
      {
        title: "Mirror Jira bugs to a Trello bug tracker board",
        description:
          "When a new bug is created in Jira, GAIA creates a corresponding Trello card with the bug summary, priority, affected version, and a link back to Jira so non-technical stakeholders have a current view of the bug queue.",
      },
      {
        title: "Move Trello cards when Jira bug status changes",
        description:
          "As a Jira bug moves through the workflow — from Open to In Progress to In Review to Resolved — GAIA moves the corresponding Trello card across the matching lists so the Trello board always reflects Jira status in real time.",
      },
      {
        title: "Add Jira fix version to Trello card labels",
        description:
          "When engineering sets a fix version on a Jira bug, GAIA adds the version as a Trello label so stakeholders can filter the bug board by release and understand which fixes are coming in which version.",
      },
      {
        title: "Post Jira bug comments to Trello card activity",
        description:
          "When an engineer adds an investigation update or resolution note to a Jira bug, GAIA mirrors the comment to the Trello card so support staff following the card see the latest engineering notes without Jira access.",
      },
      {
        title: "Escalate high-priority Jira bugs to a Trello escalation list",
        description:
          "When a Jira bug is marked as Critical or Blocker priority, GAIA creates or moves its Trello card to a dedicated Escalations list on the Trello board so critical bugs are visually prominent and easy to track.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Trello to GAIA",
        description:
          "Authorize GAIA with your Jira project and Trello account. Select the Trello board and configure the list structure that should mirror your Jira bug workflow stages.",
      },
      {
        step: "Map Jira statuses to Trello lists",
        description:
          "Define which Jira workflow statuses correspond to which Trello lists and which Jira issue fields should populate Trello card title, description, labels, and due date.",
      },
      {
        step: "Jira and Trello stay in sync automatically",
        description:
          "GAIA creates Trello cards for new Jira bugs and moves them as status changes. Engineering works in Jira; stakeholders watch Trello; both views are always accurate.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA sync all Jira issue types or only bugs?",
        answer:
          "By default GAIA syncs only Jira issues of type Bug. You can extend this to include other issue types such as Tasks or Stories by configuring additional sync rules, each with their own Trello board or list destination.",
      },
      {
        question: "Can Trello users add comments that sync back to Jira?",
        answer:
          "Yes, bidirectional comment sync is supported. When a Trello card member adds a comment, GAIA posts it to the linked Jira issue. You can restrict this to specific Trello board members if you want to limit which comments flow back to Jira.",
      },
      {
        question: "What happens when a Jira bug is deleted?",
        answer:
          "When a Jira bug is deleted, GAIA archives the corresponding Trello card rather than deleting it. This preserves the card history in Trello while keeping the active board clean. You can configure automatic deletion if preferred.",
      },
    ],
  },

  "jira-google-calendar": {
    slug: "jira-google-calendar",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Add Jira sprint dates and due dates to Google Calendar automatically",
    metaTitle:
      "Jira + Google Calendar Integration - Sprint Dates in Your Calendar | GAIA",
    metaDescription:
      "Connect Jira and Google Calendar with GAIA. Automatically add Jira sprint start and end dates, issue due dates, and release milestones to Google Calendar so engineering deadlines are always visible alongside the rest of your schedule.",
    keywords: [
      "Jira Google Calendar integration",
      "Jira Google Calendar sync",
      "Jira sprint dates calendar",
      "engineering deadlines calendar",
      "connect Jira and Google Calendar",
      "Jira calendar automation",
      "sprint milestones calendar",
    ],
    canonicalSlug: "google-calendar-jira",
    intro:
      "Jira knows when sprints start and end, when issues are due, and when releases are planned. Google Calendar is where engineers and managers live for time management. But sprint dates in Jira do not appear in Google Calendar automatically, meaning engineers have to check two places to understand their upcoming obligations and managers have to manually create calendar events for milestones they can see in Jira.\n\nGAIA connects Jira and Google Calendar so every sprint, due date, and release milestone in Jira appears automatically as a calendar event. Engineers see their engineering deadlines alongside meetings and personal events without switching tools. Managers get calendar reminders for sprint reviews and release dates without manually creating events.\n\nThis integration is particularly useful for engineering managers juggling multiple Jira projects who want a single calendar view of all sprint timelines, and for engineers who use Google Calendar as their primary planning tool and want Jira obligations to surface there naturally.",
    useCases: [
      {
        title: "Add Jira sprint start and end dates to Google Calendar",
        description:
          "When a new Jira sprint is created, GAIA creates a Google Calendar event spanning the sprint dates with the sprint name, project, and a link to the Jira sprint board so the team sees sprint boundaries in their calendars automatically.",
      },
      {
        title: "Create calendar events for Jira issue due dates",
        description:
          "When a Jira issue assigned to you receives a due date, GAIA creates a Google Calendar reminder event on that date so engineering deadlines appear alongside meetings and personal commitments in a single view.",
      },
      {
        title: "Add Jira release milestones to the team calendar",
        description:
          "When a Jira version is created with a release date, GAIA adds a milestone event to the shared engineering Google Calendar so the entire team sees upcoming release dates without checking the Jira releases page.",
      },
      {
        title: "Update calendar events when Jira dates change",
        description:
          "When a Jira sprint is extended or an issue due date is pushed, GAIA updates the corresponding Google Calendar event automatically so calendar dates always reflect the current Jira schedule without manual corrections.",
      },
      {
        title: "Schedule sprint ceremonies from Jira sprint dates",
        description:
          "When a Jira sprint is created, GAIA schedules recurring Google Calendar invites for sprint planning, daily standup, sprint review, and retrospective based on the sprint dates and the team's configured ceremony schedule.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Google Calendar to GAIA",
        description:
          "Authorize GAIA with your Jira account and Google Workspace. Select which Jira projects and calendars should be synchronized and which team members should be invited to calendar events.",
      },
      {
        step: "Configure which Jira events create calendar entries",
        description:
          "Choose whether GAIA should sync sprint dates, issue due dates, release milestones, or all three. Set the calendar destination for each event type and configure reminder timing.",
      },
      {
        step: "Jira deadlines appear in Google Calendar automatically",
        description:
          "GAIA monitors Jira for sprint creation, date changes, and release updates and keeps Google Calendar current. Engineers see engineering obligations in their calendar without any manual event creation.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA create individual calendar events for every Jira issue due date or only sprints?",
        answer:
          "Both are configurable. You can sync sprint dates only, issue due dates only, or both. For issue due dates, you can filter by assignee so only issues assigned to each team member create events on their personal calendar.",
      },
      {
        question:
          "What happens to Google Calendar events when a Jira sprint is deleted?",
        answer:
          "GAIA deletes or cancels the corresponding Google Calendar event when a Jira sprint is deleted. If the sprint is renamed or its dates are changed, GAIA updates the calendar event to match.",
      },
      {
        question:
          "Can GAIA add Jira issue due date reminders to a shared team calendar?",
        answer:
          "Yes. You can configure GAIA to write to a shared Google Calendar that all team members subscribe to. This gives the team a unified view of all upcoming Jira deadlines without each member needing personal calendar sync enabled.",
      },
    ],
  },

  "jira-figma": {
    slug: "jira-figma",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline:
      "Link Figma designs to Jira tickets and streamline design review workflows",
    metaTitle:
      "Jira + Figma Integration - Design and Engineering Tickets in Sync | GAIA",
    metaDescription:
      "Connect Jira and Figma with GAIA. Automatically attach Figma designs to Jira tickets, notify designers when tickets enter development, and route design feedback from Jira directly into Figma comments.",
    keywords: [
      "Jira Figma integration",
      "Jira Figma sync",
      "attach Figma to Jira",
      "design handoff Jira Figma",
      "connect Jira and Figma",
      "design review workflow automation",
      "Jira Figma automation",
    ],
    intro:
      "Design handoffs between Figma and Jira are a frequent source of rework. Engineers look for the Figma link and cannot find it, so they build from memory or an outdated screenshot. Designers publish a new version of a spec but the Jira ticket still references the old frame. Design feedback gathered during QA gets posted in Jira and never reaches the designer in Figma.\n\nGAIA connects Figma and Jira so design references are always attached, always current, and always reaching the right person. When a Jira ticket is created for a feature that has a matching Figma frame, GAIA attaches the link automatically. When a designer updates a frame, GAIA comments on the linked Jira ticket. When engineering marks a design issue in Jira, GAIA routes the comment to Figma.\n\nThis integration reduces the rework and confusion that comes from misaligned design-engineering handoffs and is most impactful on teams shipping features quickly across multiple parallel work streams.",
    useCases: [
      {
        title: "Auto-attach Figma frames to Jira tickets",
        description:
          "When a Jira ticket is created for a feature, GAIA searches the linked Figma project for frames matching the ticket name and attaches the Figma URL so engineers have the correct design reference without hunting through Figma.",
      },
      {
        title: "Notify engineers of Figma design updates",
        description:
          "When a designer publishes a new version of a Figma frame linked to an active Jira ticket, GAIA posts a comment on the ticket summarizing what changed and linking to the updated frame so engineers review the latest spec before writing more code.",
      },
      {
        title: "Alert designers when Jira tickets enter development",
        description:
          "When a Jira ticket transitions to In Progress, GAIA notifies the designer credited in the linked Figma file that implementation has begun, giving them a window to catch any overlooked spec issues before code is committed.",
      },
      {
        title: "Route Jira design feedback to Figma comments",
        description:
          "When a QA tester or engineer adds a comment on a Jira ticket describing a visual discrepancy, GAIA posts the feedback as a comment on the linked Figma frame so the designer receives it in their native context rather than having to monitor Jira.",
      },
      {
        title: "Track design approval status in Jira",
        description:
          "GAIA monitors Figma for approval annotations from design reviewers and updates the linked Jira ticket status to Design Approved automatically, advancing the workflow without requiring designers to update Jira manually.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Figma and Jira to GAIA",
        description:
          "Authorize GAIA with your Figma account and Jira project. Map Figma projects to Jira projects during setup so GAIA knows which design files correspond to which engineering work.",
      },
      {
        step: "Configure matching rules and notification routing",
        description:
          "Set naming patterns for automatic frame-to-ticket matching, define which Jira transitions trigger designer notifications, and configure how design feedback comments should be forwarded to Figma.",
      },
      {
        step: "Design and engineering stay synchronized",
        description:
          "GAIA maintains design-to-ticket links automatically and routes feedback and updates between the two tools. Engineers always have current designs; designers always know when their work enters development.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA identify which Figma frame belongs to which Jira ticket?",
        answer:
          "GAIA matches by name similarity between Jira ticket summaries and Figma frame names. You can also paste a Figma URL directly into a Jira ticket field to create an explicit link that GAIA then manages going forward.",
      },
      {
        question: "Can GAIA embed Figma previews inside Jira tickets?",
        answer:
          "GAIA attaches Figma URLs to Jira tickets in the links section. Jira Cloud renders Figma links as visual previews natively when the Figma for Jira app is installed. GAIA works alongside that app and keeps the attached links current.",
      },
      {
        question: "Does GAIA support Figma branching workflows?",
        answer:
          "Yes. You can configure GAIA to link Jira tickets to a specific Figma branch rather than the main file. GAIA can also detect when a Figma branch is merged and update the Jira ticket link to point to the merged main file.",
      },
    ],
  },

  "jira-discord": {
    slug: "jira-discord",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline: "Post Jira issue updates to Discord dev channels automatically",
    metaTitle:
      "Jira + Discord Integration - Engineering Updates in Your Dev Server | GAIA",
    metaDescription:
      "Connect Jira and Discord with GAIA. Automatically post Jira ticket updates, sprint summaries, and blocker alerts to your Discord engineering channels so the team stays informed without monitoring Jira.",
    keywords: [
      "Jira Discord integration",
      "Jira Discord notifications",
      "Jira Discord bot",
      "engineering Discord Jira",
      "connect Jira and Discord",
      "post Jira updates to Discord",
      "Jira Discord webhook",
    ],
    intro:
      "Engineering teams that use Discord as their primary communication hub often find that Jira activity stays invisible in their day-to-day chat. A critical bug is created in Jira but nobody in Discord knows until the next standup. A sprint closes with impressive velocity but the team never sees a summary. Engineers have to tab over to Jira just to find out if their PR review is unblocking the issue they care about.\n\nGAIA brings Jira into Discord by routing the right events to the right channels automatically. Sprint summaries land in the engineering channel at the end of every sprint. Critical bugs trigger immediate alerts. Assigned issues notify engineers in DMs. Teams can also create and update Jira tickets with Discord commands without leaving their chat environment.\n\nThis integration is most impactful for remote engineering teams who run Discord as their virtual office and want Jira activity to flow into their existing communication rhythm rather than requiring constant tool switching.",
    useCases: [
      {
        title: "Post sprint summaries to the engineering channel",
        description:
          "When a Jira sprint closes, GAIA posts a formatted summary to the designated Discord channel including stories completed, velocity, carry-over issues, and top contributors so the team celebrates progress and understands what carried forward.",
      },
      {
        title: "Alert the team to new critical bugs",
        description:
          "When a Jira issue of type Bug is created or upgraded to Critical priority, GAIA immediately posts an alert to the engineering Discord channel with the bug title, reporter, affected component, and link so the team can respond quickly.",
      },
      {
        title: "DM engineers when Jira issues are assigned",
        description:
          "When a Jira issue is assigned to an engineer, GAIA sends them a Discord DM with the issue summary, priority, sprint, and a direct Jira link so they are notified in the tool they are already using.",
      },
      {
        title: "Post blocker notifications to the leads channel",
        description:
          "When a Jira story transitions to Blocked, GAIA posts a structured notification to the team leads Discord channel identifying the blocking dependency and the affected engineer so resolution can be coordinated immediately.",
      },
      {
        title: "Create Jira tickets from Discord slash commands",
        description:
          "Engineers can type a GAIA slash command in Discord to create a new Jira ticket without leaving the chat. GAIA collects the issue type, summary, and priority through a short Discord prompt and creates the ticket, posting the confirmation back to the channel.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Discord to GAIA",
        description:
          "Authorize GAIA with your Jira project and invite the GAIA bot to your Discord server. Map Jira projects and issue types to Discord channels during setup.",
      },
      {
        step: "Configure event routing and notification format",
        description:
          "Choose which Jira events generate Discord messages, which channels or users should receive each event type, and the format of notification embeds.",
      },
      {
        step: "Jira activity flows into Discord in real time",
        description:
          "GAIA monitors Jira and posts updates to the configured Discord destinations as they happen. The team stays informed without leaving Discord.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA route Jira notifications from different projects to different Discord channels?",
        answer:
          "Yes. You can configure separate channel routing rules for each Jira project. For example, mobile Jira tickets go to #mobile-dev and backend tickets go to #backend-dev. You can also route by issue type or priority regardless of project.",
      },
      {
        question:
          "How does GAIA match Discord users to Jira users for DM notifications?",
        answer:
          "During setup you provide a mapping of Jira usernames to Discord user IDs. GAIA uses this mapping to send direct messages to the correct Discord user when their Jira account receives an assignment.",
      },
      {
        question:
          "Can GAIA avoid posting every minor Jira event and keep Discord signal quality high?",
        answer:
          "Yes. GAIA's event filter configuration is very granular. Most teams set it to notify only on issue creation, status transitions to specific states, priority escalations, and sprint boundaries. Routine field edits and comment additions are excluded by default.",
      },
    ],
  },

  "jira-drive": {
    slug: "jira-drive",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Attach requirement docs from Google Drive to Jira epics automatically",
    metaTitle:
      "Jira + Google Drive Integration - Requirements Docs Linked to Epics | GAIA",
    metaDescription:
      "Connect Jira and Google Drive with GAIA. Automatically attach Drive requirement documents to Jira epics, create post-mortem docs from resolved incidents, and keep engineering documentation linked to active work.",
    keywords: [
      "Jira Google Drive integration",
      "Jira Drive automation",
      "attach docs to Jira",
      "requirements document Jira workflow",
      "connect Jira and Google Drive",
      "Jira Drive sync",
      "engineering docs automation",
    ],
    intro:
      "Every Jira epic has documentation that lives somewhere in Google Drive: the product requirements document, the technical design doc, the stakeholder sign-off email, the post-launch notes. But finding and attaching those documents to the right Jira epic is manual work that often does not happen, leaving engineers to dig through Drive each time they need context.\n\nGAIA builds and maintains the link between Google Drive documents and Jira epics automatically. When a product requirements document is created in Drive with a matching name, GAIA attaches it to the corresponding Jira epic. When an incident is resolved in Jira, GAIA creates a post-mortem document in Drive. The documentation system and the issue tracking system stay connected without anyone manually managing the relationship.\n\nThis integration reduces the context-gathering overhead that slows engineers down at the start of each task and ensures that the rationale behind engineering decisions is always accessible from the Jira issue where the work is tracked.",
    useCases: [
      {
        title: "Auto-attach Drive requirement docs to Jira epics",
        description:
          "When a new Google Doc is added to the requirements folder in Drive with a name matching a Jira epic, GAIA attaches the document link to the epic so engineers immediately have access to the full specification without searching Drive.",
      },
      {
        title: "Create Jira epics from new Drive PRDs",
        description:
          "When a Product Requirements Document is created in Drive and marked as Ready for Engineering, GAIA creates a Jira epic with the PRD title, a summary of the requirements, and a link back to the Drive document so engineering can begin planning immediately.",
      },
      {
        title: "Generate post-mortem documents from resolved Jira incidents",
        description:
          "When a Jira incident issue is transitioned to Resolved, GAIA creates a post-mortem document in Drive pre-populated with the incident title, timeline from Jira comments, and a structured template so the team can complete the analysis without starting from a blank page.",
      },
      {
        title: "Attach technical design docs to Jira stories",
        description:
          "When an engineer creates a technical design document in Drive and includes a Jira story key in the document title, GAIA attaches the document to the referenced Jira story so future engineers can find the design rationale in the issue.",
      },
      {
        title: "Maintain a Drive folder structure mirroring Jira projects",
        description:
          "GAIA creates and maintains a Google Drive folder structure that mirrors your Jira project hierarchy. When a new Jira project or epic is created, GAIA creates the corresponding Drive folder so document organization stays consistent automatically.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Drive and Jira to GAIA",
        description:
          "Authorize GAIA with your Google Workspace account and Jira project. Designate the Drive folders GAIA should monitor and map them to Jira projects.",
      },
      {
        step: "Configure naming conventions and trigger rules",
        description:
          "Define the naming patterns GAIA should use to match Drive documents to Jira epics and stories, which Drive events should create Jira issues, and which Jira events should create Drive documents.",
      },
      {
        step: "Docs attach to Jira issues automatically",
        description:
          "GAIA monitors both platforms and maintains links between documents and issues in real time. Engineers click through from Jira to the right Drive document without searching; documents in Drive reference their linked Jira issues.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA require documents to follow a specific naming format?",
        answer:
          "GAIA works best with consistent naming but supports flexible matching patterns including partial name matches and regular expressions. You can also link Drive documents to Jira epics manually and GAIA will maintain those explicit links going forward.",
      },
      {
        question:
          "Can GAIA attach files from shared drives, not just personal Drive?",
        answer:
          "Yes. GAIA can access any Google Drive location that the authorized Google account has access to, including shared drives and files shared with the domain. It respects existing Drive sharing permissions and does not modify them.",
      },
      {
        question:
          "What happens to Drive links in Jira when a document is moved to a different Drive folder?",
        answer:
          "Google Drive URLs are stable and do not change when a file is moved between folders. Jira links remain valid after file moves. GAIA does log the move event so you have a record of where the document currently lives.",
      },
    ],
  },

  "jira-hubspot": {
    slug: "jira-hubspot",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "HubSpot",
    toolBSlug: "hubspot",
    tagline:
      "Sync customer bug reports from HubSpot to Jira tickets automatically",
    metaTitle:
      "Jira + HubSpot Integration - Customer Bugs Reach Engineering Fast | GAIA",
    metaDescription:
      "Connect Jira and HubSpot with GAIA. Automatically create Jira tickets from HubSpot customer bug reports, attach deal context to engineering issues, and notify account owners when bugs are resolved.",
    keywords: [
      "Jira HubSpot integration",
      "Jira HubSpot sync",
      "customer bug reports to Jira",
      "HubSpot Jira automation",
      "connect Jira and HubSpot",
      "CRM engineering bug workflow",
      "customer reported bugs Jira",
    ],
    intro:
      "Customer-reported bugs logged in HubSpot need to reach engineering in Jira, but the handoff is almost always manual. A support rep logs a bug in HubSpot, then someone reads it, decides it belongs in Jira, creates the ticket, and periodically checks back to update HubSpot when engineering resolves it. That chain is slow, inconsistent, and dependent on people remembering to close the loop.\n\nGAIA automates the path from HubSpot bug report to Jira ticket and back. When a customer bug is logged in HubSpot and meets your configured criteria, GAIA creates a Jira ticket with the full customer context attached. As the ticket progresses in Jira, GAIA updates the HubSpot ticket. When engineering resolves the bug, GAIA notifies the account owner in HubSpot so they can communicate the fix to the customer.\n\nThis integration is most impactful for B2B SaaS teams where customer-reported bugs have direct revenue implications and where closing the loop with the customer requires coordination between customer success, engineering, and sales.",
    useCases: [
      {
        title: "Create Jira tickets from HubSpot customer bug reports",
        description:
          "When a HubSpot support ticket is classified as a bug and linked to an account above your ARR threshold, GAIA creates a Jira bug ticket with the customer description, affected account, deal value, and HubSpot ticket link so engineering has full context to reproduce and prioritize the issue.",
      },
      {
        title: "Notify HubSpot account owners when Jira bugs are resolved",
        description:
          "When a Jira bug ticket linked to a HubSpot account is resolved, GAIA creates a HubSpot activity on the deal and sends a task to the account owner so they know to reach out to the customer with the good news.",
      },
      {
        title: "Aggregate customer impact on existing Jira bugs",
        description:
          "When multiple HubSpot tickets report the same underlying bug, GAIA links them to a single Jira ticket and increments an affected-accounts counter on the issue. Engineering can sort the backlog by customer impact to prioritize fixes that affect the most accounts.",
      },
      {
        title: "Post Jira status updates back to HubSpot tickets",
        description:
          "As a Jira bug moves through the workflow — to In Progress, In Review, and Resolved — GAIA posts corresponding status updates to the linked HubSpot support ticket so the support team can answer customer inquiries about fix timing without checking Jira.",
      },
      {
        title: "Escalate HubSpot VIP bug reports to urgent Jira priority",
        description:
          "When a bug report comes from a HubSpot contact at an account designated as a VIP tier, GAIA creates the Jira ticket with Blocker priority and sends an immediate notification to the engineering lead so high-value customer issues are never deprioritized by accident.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Jira to GAIA",
        description:
          "Authorize GAIA with your HubSpot portal and Jira project. Configure which HubSpot ticket properties and deal characteristics should trigger Jira ticket creation.",
      },
      {
        step: "Define customer context mapping and escalation rules",
        description:
          "Map HubSpot deal properties to Jira fields, set the account tier or ARR threshold that determines Jira priority, and configure which Jira state transitions should update HubSpot.",
      },
      {
        step: "Bugs flow from customers to engineering and back automatically",
        description:
          "GAIA monitors HubSpot for qualifying bug reports, creates Jira tickets with customer context, and keeps HubSpot updated as engineering progresses. The customer loop closes without anyone managing it manually.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA prevent duplicate Jira tickets when multiple customers report the same bug?",
        answer:
          "GAIA uses semantic similarity matching to identify existing Jira tickets that likely correspond to a new HubSpot report. If a match above your configured confidence threshold exists, GAIA links the HubSpot ticket to the existing Jira issue and increments the customer impact counter rather than creating a duplicate.",
      },
      {
        question:
          "Does GAIA include customer PII from HubSpot in Jira tickets?",
        answer:
          "By default GAIA includes only the company name, account tier, and deal ARR in Jira tickets — not individual contact names or email addresses. You can configure how much customer context to include based on your data handling policies.",
      },
      {
        question:
          "Can GAIA handle the reverse flow — engineering bugs that should proactively notify affected HubSpot accounts?",
        answer:
          "Yes. You can configure GAIA to search HubSpot for accounts likely affected by a newly filed Jira bug based on product usage data or account properties. GAIA then creates HubSpot tasks for the relevant account owners to proactively notify their customers.",
      },
    ],
  },

  "linear-jira": {
    slug: "linear-jira",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Jira",
    toolBSlug: "jira",
    canonicalSlug: "jira-linear",
    tagline:
      "Sync Linear and Jira so modern and enterprise dev teams stay aligned",
    metaTitle: "Linear + Jira Integration - Cross-Team Issue Sync | GAIA",
    metaDescription:
      "Automate Linear and Jira with GAIA. Sync issues between Linear and Jira, keep cross-team projects aligned, and eliminate friction managing work across two engineering tools.",
    keywords: [
      "Linear Jira integration",
      "Linear Jira sync",
      "Linear Jira automation",
      "cross-team issue sync",
      "Linear to Jira tickets",
      "engineering workflow integration",
    ],
    intro:
      "Modern product teams often adopt Linear for its speed and developer-friendly UX, while enterprise counterparts or client organizations remain on Jira. The resulting split creates a synchronization burden: issues created in one tool must be manually mirrored in the other, status updates diverge, and neither side has reliable visibility into the other's progress.\n\nGAIA eliminates that burden by keeping Linear and Jira in continuous sync. When an issue is created in Linear, GAIA can open the corresponding Jira ticket automatically. When a Jira issue changes status, GAIA updates the Linear counterpart. Sprint data flows between both platforms so managers in either tool see accurate progress without manual reconciliation.\n\nThis integration is especially valuable for agencies and consultancies that run internal work in Linear but must report progress through a client's Jira instance, and for companies mid-migration from Jira to Linear who need both systems live during the transition.",
    useCases: [
      {
        title: "Bidirectional issue sync",
        description:
          "GAIA mirrors issues created in Linear to Jira and vice versa, including title, description, priority, and assignee, so both systems always reflect the same source of truth.",
      },
      {
        title: "Status change propagation",
        description:
          "When an engineer moves a Linear issue to In Review or Done, GAIA updates the corresponding Jira ticket's status automatically, keeping project managers in Jira informed without manual updates.",
      },
      {
        title: "Sprint planning across tools",
        description:
          "GAIA reads Linear cycle data and creates or updates the matching Jira sprint so sprint start dates, end dates, and issue assignments stay consistent across both platforms.",
      },
      {
        title: "GitHub PR linking in both tools",
        description:
          "When a pull request referencing a Linear issue is opened, GAIA attaches the PR link to both the Linear issue and the corresponding Jira ticket so reviewers in either tool have full context.",
      },
      {
        title: "Cross-team progress reporting",
        description:
          "GAIA generates a unified progress report aggregating Linear and Jira data, giving leadership a single view of delivery status regardless of which tool each team uses.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Linear and Jira to GAIA",
        description:
          "Authenticate your Linear workspace and Jira instance in GAIA's integration settings. GAIA uses OAuth for Linear and API tokens for Jira, keeping your credentials secure.",
      },
      {
        step: "Map projects and issue fields",
        description:
          "Tell GAIA which Linear teams map to which Jira projects, and how fields like priority, status, and labels should translate between the two systems.",
      },
      {
        step: "GAIA keeps both systems in sync automatically",
        description:
          "Once configured, GAIA monitors both platforms for changes and propagates updates in real time. You can adjust mapping rules anytime using natural language commands.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA sync only specific Linear teams to Jira?",
        answer:
          "Yes. You can scope the sync to specific Linear teams and Jira projects. For example, you might sync only your platform team's Linear issues to a client's Jira board while keeping other teams' work private.",
      },
      {
        question:
          "What happens if an issue is updated in both tools simultaneously?",
        answer:
          "GAIA uses a last-write-wins strategy by default and flags conflicts for your review. You can configure which tool is treated as the master source of truth for specific fields.",
      },
      {
        question:
          "Does GAIA sync comments and attachments between Linear and Jira?",
        answer:
          "GAIA can sync comments and file attachments between the two tools. This is configurable — some teams prefer to sync only status and assignee changes to avoid comment noise.",
      },
      {
        question: "Is this useful during a Jira-to-Linear migration?",
        answer:
          "Yes. GAIA can run both systems in parallel during a migration period, syncing issues bidirectionally so neither team loses continuity while the organization transitions fully to Linear.",
      },
    ],
  },

  "linear-salesforce": {
    slug: "linear-salesforce",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Salesforce",
    toolBSlug: "salesforce",
    tagline:
      "Connect Linear engineering sprints to Salesforce opportunities and cases",
    metaTitle:
      "Linear + Salesforce Integration - Engineering and CRM Sync | GAIA",
    metaDescription:
      "Automate Linear and Salesforce with GAIA. Link engineering issues to Salesforce opportunities, update cases with bug fix status, and align product delivery with revenue goals.",
    keywords: [
      "Linear Salesforce integration",
      "Linear Salesforce sync",
      "Linear Salesforce automation",
      "engineering CRM alignment",
      "Salesforce Linear workflow",
      "product delivery Salesforce",
    ],
    intro:
      "Enterprise sales teams rely on Salesforce to manage opportunities and customer cases, while engineering teams build and ship in Linear. When a customer-blocking bug or a deal-winning feature lives in Linear, Salesforce has no visibility into its progress — and account executives are left manually chasing engineering updates before customer calls.\n\nGAIA connects Linear and Salesforce so customer-facing teams always have accurate engineering status. Salesforce cases linked to known bugs receive automatic progress updates from Linear. Feature requests attached to high-value opportunities are tracked as Linear issues with revenue context baked in. When engineering ships, Salesforce records update automatically.\n\nFor enterprise software companies with dedicated sales engineering and customer success teams, this integration eliminates an entire category of internal coordination work that currently consumes hours every week.",
    useCases: [
      {
        title: "Opportunity-linked feature tracking",
        description:
          "Sales reps attach feature requests to Salesforce opportunities. GAIA creates corresponding Linear issues tagged with the opportunity value so product teams can prioritize by revenue impact.",
      },
      {
        title: "Case-to-bug issue creation",
        description:
          "When a Salesforce case is escalated as a product bug, GAIA opens a Linear issue with full case context and keeps the Salesforce case status updated as the bug moves through the fix cycle.",
      },
      {
        title: "Deal stage-triggered engineering escalation",
        description:
          "When a Salesforce opportunity moves to Negotiation or Close Won and has open engineering dependencies, GAIA escalates the linked Linear issues to ensure delivery commitments are met.",
      },
      {
        title: "Customer delivery notifications via Salesforce",
        description:
          "When a Linear issue tied to a Salesforce opportunity ships, GAIA triggers a Salesforce task for the account executive to notify the customer, keeping the relationship warm.",
      },
      {
        title: "Engineering roadmap in Salesforce reports",
        description:
          "GAIA syncs Linear project and cycle completion data to Salesforce custom objects so sales leadership can include engineering delivery timelines in account planning reports.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Linear and Salesforce to GAIA",
        description:
          "Authenticate your Linear workspace and Salesforce org in GAIA's settings. GAIA uses Salesforce Connected App OAuth and Linear API tokens, requesting only the permissions your workflows need.",
      },
      {
        step: "Map Salesforce objects to Linear issues",
        description:
          "Define which Salesforce objects (opportunities, cases, accounts) should link to Linear issues, and which Linear status changes should write back to Salesforce fields.",
      },
      {
        step: "GAIA syncs engineering progress to CRM automatically",
        description:
          "GAIA runs continuously in the background, keeping Salesforce records updated with the latest Linear issue status so sales teams always have accurate information for customer conversations.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA link a single Linear issue to multiple Salesforce opportunities?",
        answer:
          "Yes. A platform issue or widely-requested feature can be linked to multiple opportunities. When it ships, all linked Salesforce records are updated and tasks are created for each account executive.",
      },
      {
        question:
          "Does GAIA write to standard Salesforce fields or custom fields?",
        answer:
          "Both. GAIA can update standard fields like Case Status and create or update custom fields you define. The mapping is fully configurable without code.",
      },
      {
        question: "Can this integration help with Salesforce CPQ or contracts?",
        answer:
          "Indirectly. If a contract or quote is linked to an opportunity with engineering dependencies tracked in Linear, GAIA can surface the Linear status on the opportunity record visible to your CPQ workflow.",
      },
      {
        question:
          "Is this suitable for teams with Salesforce Enterprise or higher?",
        answer:
          "Yes. GAIA's Salesforce integration works with Professional, Enterprise, and Unlimited editions. API access is required, which is available on Enterprise and Unlimited, and as an add-on for Professional.",
      },
    ],
  },

  "linear-teams": {
    slug: "linear-teams",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Microsoft Teams",
    toolBSlug: "teams",
    tagline:
      "Surface Linear issue updates and sprint progress inside Microsoft Teams",
    metaTitle:
      "Linear + Microsoft Teams Integration - Dev Updates in Teams | GAIA",
    metaDescription:
      "Automate Linear and Microsoft Teams with GAIA. Post sprint summaries, issue notifications, and PR updates to Teams channels so your engineering team stays aligned without leaving chat.",
    keywords: [
      "Linear Microsoft Teams integration",
      "Linear Teams notifications",
      "Linear Teams automation",
      "engineering sprint updates Teams",
      "Linear issue alerts Teams",
      "dev team Microsoft Teams workflow",
    ],
    intro:
      "Organizations that standardized on Microsoft Teams for communication often have engineering teams using Linear for issue tracking. Without integration, engineering updates live exclusively in Linear while the rest of the organization communicates in Teams — creating a visibility gap that forces stakeholders to request manual status updates constantly.\n\nGAIA bridges Linear and Microsoft Teams so engineering progress is visible to the entire organization in the communication tool they already use. Issue assignments, sprint updates, PR merges, and escalations appear in the relevant Teams channels as formatted notifications. Non-engineers can ask GAIA in Teams for the status of any Linear project without needing a Linear account.\n\nFor enterprise teams running on Microsoft 365, this integration fits naturally into an existing Teams-centric workflow and eliminates the need for separate project status meetings.",
    useCases: [
      {
        title: "Sprint progress channel updates",
        description:
          "GAIA posts daily sprint burn-down updates to a designated Teams channel showing completed, in-progress, and blocked issues so stakeholders can track progress without interrupting engineers.",
      },
      {
        title: "Issue assignment notifications",
        description:
          "When a Linear issue is assigned, GAIA sends a Teams message to the assigned engineer with full issue details, due date, and a direct link to the issue.",
      },
      {
        title: "Cross-functional release announcements",
        description:
          "When a Linear cycle completes, GAIA posts a formatted release summary to the organization-wide Teams channel listing all shipped features, with links to any associated documentation.",
      },
      {
        title: "Escalation alerts to management channels",
        description:
          "When a Linear issue is escalated to Urgent or a cycle is at risk of missing its target date, GAIA posts an alert to the engineering manager's Teams channel for immediate attention.",
      },
      {
        title: "Linear queries from Teams",
        description:
          "Team members can ask GAIA directly in Teams — 'What's in the current sprint?' or 'Who owns the login bug?' — and receive an accurate answer pulled live from Linear.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Linear and Microsoft Teams to GAIA",
        description:
          "Authenticate your Linear workspace and install the GAIA app in your Microsoft Teams organization. Configure the Teams channels where Linear notifications should be posted.",
      },
      {
        step: "Configure notification preferences",
        description:
          "Define which Linear events generate Teams notifications — sprint events, issue assignments, priority changes, PR links — and map each event type to the appropriate Teams channel.",
      },
      {
        step: "GAIA delivers updates and answers queries",
        description:
          "GAIA posts real-time Linear updates to Teams and responds to natural language queries about issue status, cycle progress, and team workload directly within Teams conversations.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA support Teams channels within specific Teams (team spaces)?",
        answer:
          "Yes. GAIA can post to any channel in any team space within your Microsoft Teams organization. You can map different Linear teams to different Teams channels with full granularity.",
      },
      {
        question:
          "Can Teams users create Linear issues without opening Linear?",
        answer:
          "Yes. Users can describe a bug or feature request to GAIA in a Teams chat or channel, and GAIA creates the Linear issue and confirms the link in the conversation.",
      },
      {
        question:
          "Does GAIA support Teams Adaptive Cards for richer notifications?",
        answer:
          "Yes. GAIA uses Adaptive Cards to format Linear notifications in Teams, including issue titles, descriptions, priority badges, assignees, and action buttons for common Linear operations.",
      },
      {
        question: "Is this compatible with Teams on mobile?",
        answer:
          "Yes. GAIA's Teams integration works on the Teams mobile app as well as desktop and web. Notifications appear in real time across all Teams clients.",
      },
    ],
  },

  "linear-loom": {
    slug: "linear-loom",
    toolA: "Linear",
    toolASlug: "linear",
    toolB: "Loom",
    toolBSlug: "loom",
    tagline:
      "Attach Loom video walkthroughs to Linear issues for richer async context",
    metaTitle:
      "Linear + Loom Integration - Video Context for Engineering Issues | GAIA",
    metaDescription:
      "Automate Linear and Loom with GAIA. Attach Loom bug recordings to Linear issues, send video updates on blocked issues, and replace status meetings with async Loom summaries.",
    keywords: [
      "Linear Loom integration",
      "Linear Loom automation",
      "bug recording Linear",
      "async engineering updates Loom",
      "Loom to Linear issues",
      "video engineering workflow",
    ],
    intro:
      "Text descriptions in Linear issues often fall short for complex bugs or nuanced feature feedback. A ten-second Loom recording of a UI bug conveys more than three paragraphs of written description — but attaching that recording to the right Linear issue requires remembering the issue number, opening Linear, and manually pasting the Loom link.\n\nGAIA makes Loom and Linear work together seamlessly. When a Loom recording is created with a specific tag or title convention, GAIA identifies the relevant Linear issue and attaches the video automatically. Bug recordings made in Loom generate new Linear issues with the video embedded. Sprint update Looms are posted as comments on all issues completed that week.\n\nFor remote and async-first dev teams, this integration enables a richer asynchronous communication layer on top of Linear's structured workflow — combining the precision of issue tracking with the clarity of video communication.",
    useCases: [
      {
        title: "Bug recording to Linear issue",
        description:
          "When a QA tester or user records a Loom showing a bug, GAIA creates a Linear issue with the Loom video embedded as the primary description, making it immediately actionable for the assigned engineer.",
      },
      {
        title: "Design feedback videos on issues",
        description:
          "Designers record Loom walkthroughs of design feedback and GAIA attaches them to the corresponding Linear implementation issues so engineers see the exact changes requested without a meeting.",
      },
      {
        title: "Sprint demo recordings on completed issues",
        description:
          "After a sprint demo, GAIA attaches the Loom recording to each Linear issue demonstrated, creating a permanent video record of what was built and how it works.",
      },
      {
        title: "Async standup updates",
        description:
          "Engineers record daily Loom standup updates mentioning their Linear issues. GAIA parses the video transcript and posts relevant updates as comments on each mentioned issue.",
      },
      {
        title: "Onboarding walkthroughs linked to issues",
        description:
          "GAIA attaches relevant Loom onboarding and architecture walkthrough videos to Linear issues in specific areas, giving new engineers video context alongside written issue descriptions.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Linear and Loom to GAIA",
        description:
          "Authenticate your Linear workspace and Loom workspace in GAIA's settings. GAIA uses Loom's API to access video metadata and transcripts.",
      },
      {
        step: "Define video-to-issue linking rules",
        description:
          "Tell GAIA how to identify which Loom videos relate to which Linear issues — by title convention (e.g., including the issue ID), by folder, or by transcript content analysis.",
      },
      {
        step: "GAIA links videos to issues automatically",
        description:
          "When a new Loom is created matching your rules, GAIA attaches it to the appropriate Linear issue as a comment or description link and notifies the relevant team member.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create a Linear issue from a Loom recording without a pre-existing issue?",
        answer:
          "Yes. If a Loom recording title includes a trigger phrase (e.g., 'Bug:' or 'Issue:'), GAIA creates a new Linear issue using the video title as the issue name and embeds the Loom link as the description.",
      },
      {
        question:
          "Does GAIA use Loom transcripts to populate Linear issue fields?",
        answer:
          "Yes. GAIA reads the Loom transcript to extract a summary, steps to reproduce (for bugs), and any mentioned issue numbers, using this content to populate the Linear issue description and comments.",
      },
      {
        question:
          "Does attaching a Loom to Linear require the viewer to have a Loom account?",
        answer:
          "Not necessarily. Loom videos can be set to public or shared-link access. GAIA attaches videos using their shared link so anyone with the Linear issue can view the recording without a Loom login.",
      },
      {
        question:
          "Can GAIA attach Loom videos to sub-issues or just top-level issues?",
        answer:
          "GAIA can attach Loom links to both top-level Linear issues and sub-issues. This is particularly useful for QA feedback on specific acceptance criteria tracked as sub-issues.",
      },
    ],
  },

  "jira-asana": {
    slug: "jira-asana",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Asana",
    toolBSlug: "asana",
    canonicalSlug: "asana-jira",
    tagline:
      "Sync Jira engineering tickets with Asana project tasks automatically",
    metaTitle: "Jira + Asana Integration - Product and Engineering Sync | GAIA",
    metaDescription:
      "Automate Jira and Asana with GAIA. Sync Jira tickets with Asana tasks, keep product and engineering aligned, and eliminate manual status updates between project management tools.",
    keywords: [
      "Jira Asana integration",
      "Jira Asana sync",
      "Jira Asana automation",
      "product engineering sync",
      "Jira to Asana tasks",
      "project management integration",
    ],
    intro:
      "Product teams track work in Asana while engineering teams work in Jira. The gap between them is where projects slow down — product managers create Asana tasks that need corresponding Jira tickets, status updates must be manually mirrored across both tools, and neither side has full visibility into the other.\n\nGAIA synchronizes Jira and Asana so the right information is in both places without double entry. Asana tasks create Jira tickets. Jira status changes update Asana. Product managers see engineering progress in Asana. Engineers see product context in Jira. Both teams work in their preferred tool while GAIA keeps them aligned.\n\nFor enterprise product organizations running structured program management in Asana alongside Jira-based engineering sprints, this integration is the connective tissue that removes weekly sync meetings and manual spreadsheet updates from the delivery process.",
    useCases: [
      {
        title: "Feature task to Jira ticket",
        description:
          "When a product manager creates a feature task in Asana and marks it engineering-ready, GAIA opens a corresponding Jira story in the appropriate project, pre-filled with acceptance criteria from the Asana task.",
      },
      {
        title: "Jira sprint status in Asana timelines",
        description:
          "As engineers progress Jira tickets through the sprint, GAIA reflects those status changes on the Asana task so project timelines and program-level reports stay accurate automatically.",
      },
      {
        title: "Epic-to-portfolio alignment",
        description:
          "GAIA maps Jira epics to Asana portfolios, keeping high-level roadmap items synchronized so executive stakeholders can track progress at the portfolio level without Jira access.",
      },
      {
        title: "Bug escalation from Asana to Jira",
        description:
          "When a bug is flagged in Asana during UAT or customer feedback review, GAIA creates a prioritized Jira bug ticket and routes it to the on-call engineering team for triage.",
      },
      {
        title: "Sprint completion milestone updates",
        description:
          "When a Jira sprint closes, GAIA marks the corresponding Asana milestone complete and posts a sprint summary to the project feed so stakeholders see delivery confirmation without attending sprint review.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Asana to GAIA",
        description:
          "Authenticate your Jira instance and Asana organization in GAIA's settings. GAIA uses OAuth for Asana and API tokens for Jira, requesting only the permissions required for your configured workflows.",
      },
      {
        step: "Map projects, epics, and field translations",
        description:
          "Define which Asana projects correspond to which Jira projects, how Asana task fields map to Jira issue fields, and which status transitions in one tool should update the other.",
      },
      {
        step: "GAIA keeps both tools synchronized",
        description:
          "GAIA monitors Asana and Jira continuously, propagating changes in real time. You can adjust sync rules at any time by describing the change you want to GAIA in plain language.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA sync every Asana task to Jira?",
        answer:
          "Only tasks you configure for sync. You can filter by Asana project, section, tag, or custom field so only engineering-ready tasks generate Jira tickets.",
      },
      {
        question: "Can GAIA sync Jira epics and sub-tasks to Asana?",
        answer:
          "Yes. GAIA can map Jira epics to Asana projects or milestones, and Jira sub-tasks to Asana subtasks. The hierarchy mapping is configurable to fit your team's structure.",
      },
      {
        question: "What happens when a Jira ticket is resolved?",
        answer:
          "When a Jira ticket is marked Done or Closed, GAIA updates the linked Asana task status accordingly. You can configure whether this marks the task complete or simply updates a status custom field.",
      },
      {
        question: "Can we use this during a migration from Jira to Asana?",
        answer:
          "Yes. Many teams use this integration during a phased migration, running Jira and Asana in parallel with GAIA keeping them in sync until the team is fully on Asana.",
      },
    ],
  },

  "jira-salesforce": {
    slug: "jira-salesforce",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Salesforce",
    toolBSlug: "salesforce",
    tagline:
      "Connect Jira engineering tickets to Salesforce cases and opportunities",
    metaTitle:
      "Jira + Salesforce Integration - Enterprise CRM and Dev Alignment | GAIA",
    metaDescription:
      "Automate Jira and Salesforce with GAIA. Link Jira tickets to Salesforce cases and opportunities, update CRM records as bugs are fixed, and give sales teams live engineering status.",
    keywords: [
      "Jira Salesforce integration",
      "Jira Salesforce sync",
      "Jira Salesforce automation",
      "enterprise CRM engineering sync",
      "Salesforce Jira workflow",
      "customer bug Jira Salesforce",
    ],
    intro:
      "Enterprise software companies run their customer relationships in Salesforce and their engineering operations in Jira. When a customer reports a critical bug or requests a feature, the information must travel from Salesforce to Jira for engineering action — and back to Salesforce when the fix ships. Without automation, that journey is manual, slow, and unreliable.\n\nGAIA connects Jira and Salesforce so customer-facing teams always know the status of the engineering work that affects their accounts. Salesforce cases escalated as bugs auto-generate Jira tickets. Jira ticket resolutions update Salesforce case statuses. High-value opportunities with engineering dependencies surface their Jira ticket status directly on the Salesforce record.\n\nFor enterprise B2B SaaS companies where customer trust depends on reliable communication about engineering timelines, this integration ensures every customer-affecting issue is tracked end-to-end across both systems.",
    useCases: [
      {
        title: "Salesforce case to Jira bug ticket",
        description:
          "When a Salesforce case is escalated as a product defect, GAIA creates a Jira bug ticket with the case description, account tier, ARR at risk, and a link back to the Salesforce case for full customer context.",
      },
      {
        title: "Jira resolution to Salesforce case closure",
        description:
          "When a Jira ticket linked to a Salesforce case is resolved, GAIA updates the Salesforce case status and creates an activity for the account owner to notify the customer that their issue has been fixed.",
      },
      {
        title: "Revenue-weighted Jira priority",
        description:
          "GAIA enriches Jira tickets created from Salesforce cases with the linked account's ARR and opportunity value, giving engineering a revenue-weighted backlog view for enterprise customer issues.",
      },
      {
        title: "Deal-blocking issue escalation",
        description:
          "When a Salesforce opportunity is marked as blocked by a technical issue, GAIA escalates the linked Jira ticket to Blocker priority and notifies the engineering lead, ensuring deal timelines are protected.",
      },
      {
        title: "Quarterly business review readiness",
        description:
          "GAIA generates a summary of all Jira tickets linked to a Salesforce account and their current status, giving customer success managers a complete engineering history before QBR calls.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Salesforce to GAIA",
        description:
          "Authenticate your Jira instance and Salesforce org in GAIA's settings. GAIA uses Salesforce Connected App OAuth and Jira API tokens, scoped to the minimum permissions your workflows require.",
      },
      {
        step: "Configure case and opportunity mapping",
        description:
          "Define which Salesforce case categories or opportunity stages trigger Jira ticket creation, how Salesforce fields map to Jira issue fields, and which Jira transitions write back to Salesforce.",
      },
      {
        step: "GAIA automates the customer-to-engineering loop",
        description:
          "GAIA monitors both systems and executes your workflows continuously, ensuring Salesforce cases become Jira tickets promptly and Jira resolutions reach Salesforce without manual intervention.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA work with Salesforce Service Cloud as well as Sales Cloud?",
        answer:
          "Yes. GAIA integrates with both Sales Cloud (opportunities and accounts) and Service Cloud (cases and entitlements). You can configure workflows for each object type independently.",
      },
      {
        question:
          "Can GAIA prioritize Jira tickets by Salesforce account tier?",
        answer:
          "Yes. GAIA reads Salesforce account tier or custom priority fields and maps them to Jira priority levels. Enterprise or Platinum tier accounts can automatically generate Blocker-priority Jira tickets.",
      },
      {
        question:
          "How does GAIA handle Salesforce cases that don't require engineering action?",
        answer:
          "GAIA only creates Jira tickets for cases that match your configured criteria — specific case categories, escalation flags, or custom field values. Non-engineering cases are ignored.",
      },
      {
        question:
          "Can I see Jira ticket status inside Salesforce without switching tools?",
        answer:
          "Yes. GAIA writes Jira ticket status back to a custom Salesforce field on the linked case or opportunity, so account managers see live engineering status directly in Salesforce without a Jira login.",
      },
    ],
  },

  "jira-zoom": {
    slug: "jira-zoom",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline: "Turn Zoom meeting action items into Jira tickets automatically",
    metaTitle: "Jira + Zoom Integration - Meeting Action Items to Jira | GAIA",
    metaDescription:
      "Automate Jira and Zoom with GAIA. Convert sprint planning and standup action items into Jira tickets, attach meeting summaries to issues, and schedule ceremonies linked to active sprints.",
    keywords: [
      "Jira Zoom integration",
      "Jira Zoom automation",
      "meeting action items Jira",
      "Zoom to Jira tickets",
      "sprint planning Zoom Jira",
      "enterprise standup Jira workflow",
    ],
    intro:
      "Enterprise engineering teams run their sprint ceremonies — planning, refinement, standups, retrospectives — over Zoom. Every meeting generates action items, decisions, and issue updates that need to land in Jira. Without automation, a dedicated note-taker manually transcribes outcomes into tickets after every call, a process that's slow, incomplete, and unsustainable at scale.\n\nGAIA connects Zoom and Jira so meeting outcomes become Jira artifacts automatically. Sprint planning calls generate new Jira tickets for committed items. Standups with flagged blockers create or update Jira impediments. Retrospective action items land in the team's backlog with the appropriate labels. Meeting summaries are attached to relevant Jira tickets for traceability.\n\nFor distributed enterprise teams where most cross-team coordination happens over video, this integration ensures every decision made in a Zoom call is captured and tracked in Jira.",
    useCases: [
      {
        title: "Sprint planning to Jira sprint",
        description:
          "After a sprint planning Zoom call, GAIA processes the transcript and creates Jira stories for each committed item, assigns them to the engineers who accepted ownership, and adds them to the active sprint.",
      },
      {
        title: "Standup blocker tracking",
        description:
          "When an engineer mentions a blocker during a Zoom standup, GAIA creates or updates the relevant Jira ticket with an impediment flag and notifies the Scrum Master to schedule a resolution.",
      },
      {
        title: "Retrospective action items as Jira tasks",
        description:
          "GAIA processes retrospective meeting transcripts and converts process improvement actions into Jira tasks, assigned to the appropriate owners and labeled for tracking across sprints.",
      },
      {
        title: "Meeting summary on Jira issues",
        description:
          "When a Zoom meeting is specifically linked to a Jira issue, GAIA attaches a concise AI-generated summary to the ticket as a comment so any team member can understand what was discussed.",
      },
      {
        title: "Sprint ceremony scheduling",
        description:
          "GAIA schedules Zoom meetings for Jira sprint start and end dates automatically, inviting all sprint assignees and including the sprint goal and issue list in the meeting agenda.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Zoom to GAIA",
        description:
          "Authenticate your Jira instance and Zoom account in GAIA's settings. Enable Zoom cloud recording with transcription (available on Pro and above) for automatic action item extraction.",
      },
      {
        step: "Tag sprint meetings for Jira processing",
        description:
          "Add a GAIA keyword to Zoom meeting titles or use calendar metadata to indicate which meetings are sprint ceremonies. GAIA applies the appropriate Jira workflow to each meeting type.",
      },
      {
        step: "GAIA processes meetings and updates Jira",
        description:
          "After each tagged Zoom meeting, GAIA reads the transcript, extracts action items and decisions, and creates or updates Jira issues automatically. A summary is posted for team review.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA need Zoom cloud recording enabled?",
        answer:
          "Zoom cloud recording with transcription provides the best results. For teams without cloud recording, GAIA can also process a pasted meeting summary or notes document to extract Jira action items.",
      },
      {
        question:
          "Can GAIA create Jira epics, stories, and sub-tasks from a single planning meeting?",
        answer:
          "Yes. GAIA infers the appropriate Jira issue type from the meeting context. High-level items become epics or stories while granular tasks become sub-tasks under the relevant story.",
      },
      {
        question:
          "Will GAIA create duplicate Jira issues from recurring standup mentions?",
        answer:
          "GAIA checks for existing open Jira issues before creating new ones. If a matching open issue exists, GAIA adds a standup update comment rather than creating a duplicate ticket.",
      },
      {
        question:
          "Can GAIA link Zoom meeting recordings to Jira issues for reference?",
        answer:
          "Yes. GAIA can attach the Zoom cloud recording link to all Jira issues created from that meeting, providing a permanent video reference alongside the extracted action items.",
      },
    ],
  },

  "jira-teams": {
    slug: "jira-teams",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Microsoft Teams",
    toolBSlug: "teams",
    tagline:
      "Deliver Jira sprint updates and issue alerts directly in Microsoft Teams",
    metaTitle:
      "Jira + Microsoft Teams Integration - Dev Updates in Teams | GAIA",
    metaDescription:
      "Automate Jira and Microsoft Teams with GAIA. Post sprint summaries, issue notifications, and blocker alerts to Teams channels so stakeholders stay informed without accessing Jira.",
    keywords: [
      "Jira Microsoft Teams integration",
      "Jira Teams notifications",
      "Jira Teams automation",
      "enterprise sprint updates Teams",
      "Jira issue alerts Teams",
      "dev team Microsoft Teams workflow",
    ],
    intro:
      "Microsoft Teams is the enterprise communication standard for organizations running on Microsoft 365, and Jira is the enterprise issue tracker of choice for software teams. Despite how often they're used together, keeping Teams informed of Jira progress requires either manual posting or a limited built-in connector that lacks contextual formatting and intelligent routing.\n\nGAIA provides a richer Jira-Teams integration. Sprint summaries, blocker alerts, release notifications, and high-priority issue escalations are posted to the right Teams channels with structured, readable formatting. Non-technical stakeholders can query GAIA in Teams for Jira project status without needing a Jira license. Engineering managers receive personalized digests of their team's sprint progress.\n\nFor large enterprises where Teams is the operational hub, this integration ensures Jira data reaches the right people in the right channels with the right context — automatically.",
    useCases: [
      {
        title: "Daily sprint status digest",
        description:
          "GAIA posts a morning sprint status digest to the engineering Teams channel showing yesterday's completions, today's planned work, and any open blockers requiring immediate attention.",
      },
      {
        title: "High-priority issue escalation alerts",
        description:
          "When a Jira ticket is raised to Blocker or Critical priority, GAIA posts an alert to the team's Teams channel and tags the assignee and engineering lead for immediate response.",
      },
      {
        title: "Release notification to stakeholder channels",
        description:
          "When a Jira sprint or version is released, GAIA posts a formatted release announcement to the designated Teams channel listing all resolved issues, suitable for sharing with business stakeholders.",
      },
      {
        title: "Jira queries answered in Teams",
        description:
          "Stakeholders can ask GAIA in Teams — 'What's the status of the payments project?' or 'Is the login bug fixed yet?' — and receive an accurate, real-time answer sourced from Jira.",
      },
      {
        title: "New issue assignment notifications",
        description:
          "When a Jira issue is assigned to a team member, GAIA sends them a Teams message with the issue summary, priority, due date, and sprint assignment so they're immediately aware of new work.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Microsoft Teams to GAIA",
        description:
          "Authenticate your Jira instance and install the GAIA app in your Microsoft Teams organization. Map Jira projects to the Teams channels where notifications should be delivered.",
      },
      {
        step: "Configure notification and alert rules",
        description:
          "Define which Jira events generate Teams notifications — issue assignments, priority escalations, sprint events, deployments — and configure the format and routing for each event type.",
      },
      {
        step: "GAIA notifies Teams and responds to queries",
        description:
          "GAIA monitors Jira continuously and posts structured notifications to Teams in real time. Team members can also query GAIA directly within Teams for live Jira project status.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA post to different Teams channels based on Jira project?",
        answer:
          "Yes. You can configure a separate Teams channel for each Jira project or board. GAIA routes notifications to the appropriate channel automatically based on the issue's project assignment.",
      },
      {
        question: "Can Teams users create Jira issues without a Jira account?",
        answer:
          "Yes. Users can ask GAIA in a Teams message to create a Jira issue, providing a description and priority. GAIA creates the issue under the appropriate project and returns the Jira link.",
      },
      {
        question:
          "Does GAIA support Microsoft Teams Adaptive Cards for Jira notifications?",
        answer:
          "Yes. GAIA formats Jira notifications as Adaptive Cards in Teams, including issue summary, priority indicator, assignee, sprint name, and action buttons to transition issue status from within Teams.",
      },
      {
        question:
          "How is this different from the standard Jira connector for Teams?",
        answer:
          "The standard Jira connector sends basic webhook notifications. GAIA adds AI-powered filtering, intelligent routing, natural language queries, and two-way actions (like creating or updating Jira issues) directly from Teams.",
      },
    ],
  },

  "jira-airtable": {
    slug: "jira-airtable",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Airtable",
    toolBSlug: "airtable",
    tagline:
      "Sync Jira sprint data with Airtable for cross-functional reporting",
    metaTitle:
      "Jira + Airtable Integration - Engineering Data in Your Database | GAIA",
    metaDescription:
      "Automate Jira and Airtable with GAIA. Sync Jira issues to Airtable, build cross-functional dashboards, and give ops and product teams a live database view of engineering work.",
    keywords: [
      "Jira Airtable integration",
      "Jira Airtable sync",
      "Jira Airtable automation",
      "engineering database Airtable",
      "Jira to Airtable records",
      "cross-functional reporting Jira",
    ],
    intro:
      "Operations, program management, and business teams love Airtable for its flexible views, formulas, and reporting. Engineering teams depend on Jira for sprint management, issue tracking, and release planning. When these groups need to collaborate on roadmaps, resourcing, or executive reporting, the data gap between Jira and Airtable forces manual exports and stale spreadsheets.\n\nGAIA bridges Jira and Airtable in real time. Jira issues, epics, sprints, and version data flow into Airtable records automatically, giving business teams the database views they need without a Jira license. Airtable intake forms generate Jira tickets instantly. Executive dashboards built in Airtable pull live sprint velocity and burn-down data from Jira.\n\nFor enterprise organizations using Airtable as a cross-functional operations hub, this integration makes engineering delivery data a first-class citizen in every operational report.",
    useCases: [
      {
        title: "Jira issues as Airtable records",
        description:
          "GAIA syncs Jira issues to a configured Airtable table, with records for each ticket containing status, assignee, priority, sprint, fix version, and story points, updated in real time.",
      },
      {
        title: "Airtable intake forms to Jira backlog",
        description:
          "Business teams submit requests via Airtable forms. GAIA converts qualifying submissions into Jira issues automatically and writes the Jira ticket link back to the Airtable record.",
      },
      {
        title: "Executive roadmap dashboard in Airtable",
        description:
          "GAIA feeds Jira epic and version data into a dedicated Airtable base configured as an executive roadmap view, giving leadership accurate delivery timelines without Jira access.",
      },
      {
        title: "Sprint velocity tracking",
        description:
          "GAIA writes Jira sprint velocity and story point completion data to Airtable after each sprint, enabling operations teams to build capacity planning models using native Airtable formulas.",
      },
      {
        title: "SLA monitoring for customer-linked tickets",
        description:
          "GAIA syncs Jira tickets tagged with customer identifiers to Airtable and triggers alerts when tickets approach or breach SLA thresholds, based on Airtable automation rules.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Airtable to GAIA",
        description:
          "Authenticate your Jira instance and Airtable account in GAIA's settings. Specify the Airtable base and table where Jira issue data should be synced.",
      },
      {
        step: "Map Jira fields to Airtable columns",
        description:
          "Define the mapping between Jira issue fields and Airtable table columns. GAIA provides a default schema covering standard Jira fields and supports custom field mapping for advanced configurations.",
      },
      {
        step: "GAIA keeps Airtable updated with live Jira data",
        description:
          "GAIA monitors Jira for changes and updates Airtable records in real time. Airtable form submissions are also monitored and converted to Jira issues on a configurable schedule.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA sync Jira epics and sprints as well as individual issues?",
        answer:
          "Yes. GAIA can sync Jira epics, sprints, and versions to separate Airtable tables or as linked records, giving you a relational database view of your entire Jira project structure.",
      },
      {
        question:
          "Can Airtable users update Jira tickets by editing Airtable records?",
        answer:
          "Selective writeback is supported. You can configure specific columns (like assignee or priority) to push updates back to Jira when changed in Airtable, while keeping other fields read-only.",
      },
      {
        question: "How often does GAIA sync Jira data to Airtable?",
        answer:
          "By default, GAIA syncs in near real time for high-signal events (status changes, assignments, new issues) and on a periodic schedule for bulk data like sprint velocity metrics.",
      },
      {
        question:
          "Can I use this to build a public-facing roadmap in Airtable?",
        answer:
          "Yes. GAIA can sync a filtered subset of Jira issues (e.g., issues tagged as public roadmap items) to an Airtable base configured for public sharing, giving you a live roadmap without manual updates.",
      },
    ],
  },

  "jira-loom": {
    slug: "jira-loom",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Loom",
    toolBSlug: "loom",
    tagline:
      "Attach Loom video context to Jira tickets for faster issue resolution",
    metaTitle:
      "Jira + Loom Integration - Video Bug Reports and Sprint Updates | GAIA",
    metaDescription:
      "Automate Jira and Loom with GAIA. Attach Loom bug recordings to Jira tickets, create issues from video reports, and link sprint demo recordings to completed tickets automatically.",
    keywords: [
      "Jira Loom integration",
      "Jira Loom automation",
      "video bug reports Jira",
      "Loom to Jira tickets",
      "async engineering updates Jira",
      "sprint demo recording Jira",
    ],
    intro:
      "Jira tickets that describe complex bugs or nuanced requirements in text alone often lead to back-and-forth clarification threads that slow down resolution. A brief Loom recording demonstrating a bug or walking through a feature requirement communicates in seconds what paragraphs of text struggle to convey — but connecting that recording to the right Jira ticket requires manual effort.\n\nGAIA automates the link between Loom and Jira. Bug recordings created in Loom generate Jira tickets with the video embedded. Loom recordings referencing a Jira issue ID are automatically attached to that ticket as a comment. Sprint demo recordings are attached to the completed Jira issues they cover, creating a permanent video audit trail of delivered features.\n\nFor enterprise teams managing complex Jira backlogs where issue clarity directly affects resolution speed, Loom video context reduces the clarification cycle dramatically and keeps async collaboration productive.",
    useCases: [
      {
        title: "Bug recording to Jira ticket",
        description:
          "When a tester records a Loom demonstrating a bug, GAIA creates a Jira bug ticket with the Loom video embedded as the issue description, complete with steps to reproduce extracted from the transcript.",
      },
      {
        title: "Requirement walkthrough attached to stories",
        description:
          "Product managers record Loom walkthroughs of new feature requirements and GAIA attaches them to the corresponding Jira stories so engineers have rich context without a synchronous meeting.",
      },
      {
        title: "Sprint demo recordings on completed issues",
        description:
          "After a sprint review, GAIA attaches the Loom demo recording to each Jira issue demonstrated, creating a permanent video record of what was delivered that stakeholders can review asynchronously.",
      },
      {
        title: "Design change walkthroughs on in-progress tickets",
        description:
          "When a designer records a Loom showing a design change on an in-progress Jira ticket, GAIA attaches the video to the ticket and flags the assignee to review before continuing implementation.",
      },
      {
        title: "Incident post-mortems with video evidence",
        description:
          "During incident response, engineers record Loom walkthroughs of the issue and remediation steps. GAIA attaches these recordings to the Jira incident ticket as a post-mortem reference.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Loom to GAIA",
        description:
          "Authenticate your Jira instance and Loom workspace in GAIA's settings. GAIA uses Loom's API to monitor new recordings and access video transcripts.",
      },
      {
        step: "Define video-to-ticket linking conventions",
        description:
          "Tell GAIA how to match Loom recordings to Jira tickets — by Jira issue ID in the video title, by Loom folder, or by transcript content analysis. Set trigger phrases for auto-creating new tickets.",
      },
      {
        step: "GAIA attaches videos and creates tickets automatically",
        description:
          "When a new Loom is created matching your rules, GAIA attaches it to the correct Jira ticket or creates a new one, notifying the relevant team member with a link to both the video and the ticket.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create a Jira ticket from a Loom recording without a pre-existing issue?",
        answer:
          "Yes. If a Loom title includes a trigger phrase like 'Bug:' or 'Issue:', GAIA creates a new Jira ticket using the video title as the issue summary and embeds the Loom link in the description.",
      },
      {
        question: "Does GAIA use the Loom transcript to populate Jira fields?",
        answer:
          "Yes. GAIA processes the Loom transcript to extract a description, steps to reproduce, and acceptance criteria, using this content to populate the Jira ticket's Description and Comments fields.",
      },
      {
        question: "Do Jira users need a Loom account to view attached videos?",
        answer:
          "Not necessarily. Loom recordings shared via a public or workspace link can be viewed by anyone with the link. GAIA attaches videos using their shared link so Jira users can view them without a Loom login if the video is set to shared-link access.",
      },
      {
        question: "Can GAIA attach Loom videos to Jira sub-tasks?",
        answer:
          "Yes. GAIA can attach Loom links to Jira stories, epics, tasks, sub-tasks, and bugs. This is particularly useful for QA recordings that correspond to specific acceptance criteria tracked as sub-tasks.",
      },
    ],
  },

  "jira-stripe": {
    slug: "jira-stripe",
    toolA: "Jira",
    toolASlug: "jira",
    toolB: "Stripe",
    toolBSlug: "stripe",
    tagline:
      "Escalate Stripe billing failures into Jira tickets with revenue context",
    metaTitle:
      "Jira + Stripe Integration - Revenue-Critical Bug Tracking | GAIA",
    metaDescription:
      "Automate Jira and Stripe with GAIA. Convert Stripe payment failures into Jira tickets, annotate issues with revenue impact, and ensure billing-critical bugs reach engineering fast.",
    keywords: [
      "Jira Stripe integration",
      "Jira Stripe automation",
      "Stripe billing bugs Jira",
      "payment failure Jira ticket",
      "revenue impact Jira",
      "enterprise billing Jira workflow",
    ],
    intro:
      "For enterprise SaaS companies, Stripe is the revenue engine and Jira is the engineering command center. When Stripe reports payment failures, webhook errors, or subscription anomalies, those events require immediate engineering investigation — but the path from a Stripe dashboard alert to a properly filed, prioritized Jira ticket is rarely automated.\n\nGAIA connects Stripe and Jira so revenue-critical events automatically generate engineering tickets with the context needed for fast resolution. Payment failure spikes create urgent Jira bugs with error codes and affected plan data. Webhook delivery failures become Jira tasks with replay instructions. API deprecation notices create Jira tickets with deadlines and code references. Engineers prioritize billing work with full revenue impact data visible in the Jira issue.\n\nFor companies where billing reliability is a board-level metric, this integration ensures that Stripe anomalies never wait in someone's inbox before reaching the engineering team.",
    useCases: [
      {
        title: "Payment failure spike to Jira incident ticket",
        description:
          "When Stripe reports a spike in payment failures above your configured threshold, GAIA creates a Blocker-priority Jira incident ticket with the failure rate, error codes, affected plan types, and estimated MRR impact.",
      },
      {
        title: "Revenue impact annotation on billing tickets",
        description:
          "GAIA enriches Jira tickets related to Stripe issues with live revenue data — MRR at risk, number of affected subscriptions, and churn probability — so engineering can prioritize by financial impact.",
      },
      {
        title: "Webhook failure tracking",
        description:
          "When Stripe webhook delivery fails for a critical event type, GAIA creates a Jira task with the event ID, endpoint URL, failure reason, and instructions for replaying the event.",
      },
      {
        title: "Stripe API deprecation management",
        description:
          "When Stripe announces API version deprecations, GAIA creates Jira tickets for each affected integration endpoint in your codebase, tagged with the deprecation deadline and migration guide link.",
      },
      {
        title: "Churn event to Jira escalation",
        description:
          "When a subscription cancellation in Stripe cites a billing or product defect, GAIA identifies the corresponding open Jira ticket and escalates its priority, attaching the churn event data as evidence.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Jira and Stripe to GAIA",
        description:
          "Provide GAIA with a restricted Stripe API key (read-only) and authenticate your Jira instance. Configure which Stripe event types and thresholds should trigger Jira ticket creation.",
      },
      {
        step: "Define revenue thresholds and Jira routing",
        description:
          "Set the Stripe event conditions that warrant Jira tickets — failure rates, MRR thresholds, specific error codes — and map them to Jira projects, issue types, and priority levels.",
      },
      {
        step: "GAIA monitors Stripe and manages Jira automatically",
        description:
          "GAIA listens for the Stripe events you've configured and creates or updates Jira tickets accordingly, annotating each with revenue context so your team can prioritize and resolve billing issues efficiently.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA need write access to the Stripe account?",
        answer:
          "No. GAIA uses read-only Stripe API access for monitoring events and subscription data. GAIA never initiates charges, refunds, or any financial transactions.",
      },
      {
        question:
          "Can GAIA distinguish between transient Stripe errors and systemic issues?",
        answer:
          "Yes. GAIA applies configurable thresholds and time windows to distinguish a temporary gateway blip from a systemic billing failure. Only events exceeding your thresholds generate Jira tickets.",
      },
      {
        question:
          "Can GAIA correlate Stripe errors with recent Jira deployments?",
        answer:
          "GAIA can correlate the timing of a Stripe error spike with recently completed Jira tickets or sprint deployments, surfacing likely root cause candidates in the incident ticket.",
      },
      {
        question:
          "What if a Stripe issue resolves before engineering investigates?",
        answer:
          "GAIA monitors the Stripe event stream continuously. If an error condition clears, GAIA comments on the Jira ticket noting the resolution and suggests closing or downgrading its priority.",
      },
    ],
  },
};
