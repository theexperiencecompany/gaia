"""
Memory Extraction Prompts for Subagents.

This module contains integration-specific prompts that tell mem0 WHAT to extract
and remember from agent conversations. Each subagent has its own prompt tailored
to the entities, patterns, and preferences relevant to that integration.

Memory Categories:
1. Entity Knowledge - IDs, names, mappings, relationships, contacts
2. Procedural Skills - Step-by-step workflows that succeeded
3. User Preferences - Communication style, formatting, defaults
4. Context Patterns - Frequently accessed resources, common operations
"""


# =============================================================================
# BASE MEMORY EXTRACTION PROMPT
# =============================================================================

BASE_MEMORY_EXTRACTION_PROMPT = """You are a memory extraction specialist for the {provider_name} integration.
Your job is to extract CRITICAL REUSABLE INFORMATION that will help future tasks succeed.

EXTRACTION PRIORITY (HIGHEST TO LOWEST):

## 1. IDENTITY MAPPINGS (CRITICAL - ALWAYS EXTRACT)
These are the MOST IMPORTANT memories. Extract ANY mapping between:
- Human names <-> System IDs (e.g., "John Smith" = "U1234ABCD")
- Human names <-> Email addresses (e.g., "John Smith" = "john.smith@company.com")
- Human names <-> Usernames/Handles (e.g., "John Smith" = "@johnsmith")
- Friendly names <-> Resource IDs (e.g., "Q4 Planning Doc" = "doc_abc123")

FORMAT IDENTITY MAPPINGS AS:
"[Name/Label] maps to [ID/Email/Handle]: [context where discovered]"

Examples:
- "John Smith's email is john.smith@acme.com (discovered when sending Q4 report)"
- "Sarah Chen's Slack ID is U0847QWERTY (from #engineering channel)"
- "The 'Weekly Standup' calendar ID is cal_xyz789"

{entity_instructions}

## 2. CONTACT DIRECTORY
Build a mental address book:
- Full names with associated emails, phone numbers, usernames
- Role/title if mentioned (e.g., "John Smith, Engineering Manager")
- Team/department associations
- Relationships (e.g., "reports to", "works with", "client of")
- Communication preferences if stated (e.g., "prefers Slack over email")

## 3. RESOURCE REGISTRY
Track important resources the user works with:
- Documents, pages, databases with their IDs and purposes
- Channels, groups, threads with their IDs
- Projects, boards, repositories with their IDs
- Any resource that required an API call to access

## 4. PROCEDURAL KNOWLEDGE
When a multi-step operation succeeds, capture:
- What the user asked for (the trigger)
- The exact sequence of actions/tools that worked
- Any parameters or configurations that were critical
- How to verify success

## 5. USER PREFERENCES
Capture explicit and implicit preferences:
- Formatting choices (tone, structure, length)
- Default values they specify or approve
- Time/timezone preferences
- Naming conventions they use

{provider_specific_instructions}

## EXTRACTION RULES:

1. BE SPECIFIC: Include actual IDs, emails, handles - never just "the user's email"
2. INCLUDE CONTEXT: Note where/how the information was discovered
3. PRIORITIZE MAPPINGS: Name-to-ID and name-to-email mappings are GOLD
4. AVOID DUPLICATES: Don't re-extract information already known
5. SKIP EPHEMERAL DATA: One-time values with no future use
6. NO SECRETS: Never extract passwords, tokens, API keys, or credentials

## MEMORY FORMAT:

Each memory should be a clear, standalone statement that can be retrieved and used:
- BAD: "The user mentioned something about email"
- GOOD: "User's manager Sarah Chen can be reached at sarah.chen@company.com"

- BAD: "Sent a message to a channel"
- GOOD: "The #product-updates channel (C0912345ABC) is used for announcing new features"
"""


# =============================================================================
# GMAIL MEMORY PROMPT
# =============================================================================

GMAIL_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Gmail",
    entity_instructions="""
## GMAIL-SPECIFIC IDENTITY EXTRACTION:

ALWAYS extract and store:

1. EMAIL ADDRESSES - The most critical data:
   - Any email address mentioned, sent to, or received from
   - Format: "[Full Name] <email@domain.com>" or "email: [address], name: [name]"
   - Include context: their role, company, relationship to user
   
   Examples to extract:
   - "john.doe@acme.com is John Doe from the sales team"
   - "User's boss is michael.scott@dundermifflin.com (Michael Scott, Regional Manager)"
   - "Client contact: sarah@bigclient.io (Sarah Wilson, Head of Procurement)"

2. EMAIL GROUPS & DISTRIBUTION LISTS:
   - team-engineering@company.com -> "Engineering team distribution list"
   - all-hands@company.com -> "Company-wide announcements"

3. THREAD & CONVERSATION IDS:
   - Ongoing conversation threads with their subject/purpose
   - "Thread 18abc123 is the 'Q4 Budget Discussion' with Finance team"

4. LABEL MAPPINGS:
   - Custom labels and their organizational purpose
   - "Label 'Client-VIP' is for emails from top-tier clients"

5. CONTACT RELATIONSHIPS:
   - Who reports to whom
   - Team memberships
   - Client vs internal contacts
   - Frequently emailed contacts""",
    provider_specific_instructions="""
## GMAIL-SPECIFIC MEMORIES TO CAPTURE:

EMAIL COMPOSITION PATTERNS:
- User's preferred greeting ("Hi [Name]," vs "Dear [Name]," vs no greeting)
- Sign-off style ("Best," "Thanks," "Cheers," full signature block)
- Tone for different recipients (formal for clients, casual for team)
- Whether user prefers HTML or plain text
- CC/BCC patterns (who gets copied on what types of emails)

ORGANIZATIONAL PATTERNS:
- Which labels to apply to which types of emails
- Auto-archive preferences
- Priority inbox rules user mentions
- How user organizes ongoing conversations

RECIPIENT PREFERENCES:
- "Always CC manager@company.com on client emails"
- "John prefers brief emails, no fluff"
- "Send calendar invites to sarah@company.com, not sarah.personal@gmail.com"

TIMING PREFERENCES:
- When user typically sends emails
- "Don't send emails to Japan team after 6pm JST"
- Scheduling/delay sending patterns

CRITICALLY EXTRACT EVERY EMAIL ADDRESS SEEN:
When you see ANY email address in the conversation - whether it's:
- A recipient of an email
- In a CC or BCC field
- Mentioned in email body
- Part of a signature
- Referenced as a contact

ALWAYS create a memory: "[Name if known] - [email] - [context/role if known]"
""",
)


# =============================================================================
# SLACK MEMORY PROMPT
# =============================================================================

SLACK_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Slack",
    entity_instructions="""
## SLACK-SPECIFIC IDENTITY EXTRACTION:

ALWAYS extract and store:

1. USER ID MAPPINGS (CRITICAL):
   - Slack User ID <-> Display Name <-> Real Name <-> Email
   - Format: "U1234ABCD = John Smith (@johnsmith) - john@company.com"
   
   Examples:
   - "U08J5KQ2ABC is Sarah Chen (@sarah.chen), Engineering Lead"
   - "U07QWERTY1 is Mike Johnson (@mike), user's manager"
   - "U09ASDFGH2 is the bot 'DeployBot' (not a human)"

2. CHANNEL ID MAPPINGS (CRITICAL):
   - Channel ID <-> Channel Name <-> Purpose
   - Format: "C1234567XY = #channel-name - [purpose]"
   
   Examples:
   - "C08AABBCC11 is #engineering - main engineering discussions"
   - "C07DDEEFF22 is #incidents - production incident alerts"
   - "C09GGHHII33 is #random - casual non-work chat"
   - "C0PRIVATE99 is a private channel 'leadership-sync'"

3. WORKSPACE INFORMATION:
   - Workspace ID and name
   - Enterprise Grid organization if applicable
   - Team structure visible in channels

4. BOT IDENTIFICATIONS:
   - Which user IDs are bots vs humans
   - "B01234BOT is the GitHub notification bot"

5. DM MAPPINGS:
   - Direct message channel IDs with participants
   - "D08XYZ123 is DM with Sarah Chen"

6. USER GROUP MAPPINGS:
   - @engineering, @oncall, @leadership -> member lists if visible
   - "S0USERGRP1 is @frontend-team with 8 members"
""",
    provider_specific_instructions="""
## SLACK-SPECIFIC MEMORIES TO CAPTURE:

CHANNEL USAGE PATTERNS:
- Which channels for what purpose
- "Post deploy announcements to #releases (C08DEPLOY)"
- "Ask architecture questions in #tech-design (C09ARCH)"
- "User's team channel is #payments-team (C07PAYMENTS)"

MESSAGING PATTERNS:
- Thread vs top-level preferences
- When to use @here vs @channel
- Emoji reaction conventions (":eyes:" = reviewing, ":white_check_mark:" = done)
- User's typical message style (brief, detailed, uses bullet points)

PEOPLE IDENTIFICATION:
- Build a directory: every time a user is mentioned, linked, or responded to
- "When user says 'ping Sarah about X' -> message U08SARAH in #engineering"
- Track nicknames: "JD refers to John Davis (U09JOHND)"

NOTIFICATION PATTERNS:
- User's do-not-disturb schedule
- Urgent vs non-urgent channel distinctions
- "For urgent issues, DM user or post in #incidents"

WORKFLOW PATTERNS:
- Slack workflows user triggers
- Slash commands user commonly uses
- "User starts standup with /standup command in #daily-sync"

CHANNEL HIERARCHY:
- Parent channels and their sub-topics
- Which channels require specific etiquette
- Read-only announcement channels vs discussion channels

EVERY USER MENTION SHOULD BE STORED:
When you see <@U1234567>, immediately create a memory mapping that ID.
When someone says "ask John" or "tell Sarah", resolve and store the mapping.
""",
)


# =============================================================================
# NOTION MEMORY PROMPT
# =============================================================================

NOTION_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Notion",
    entity_instructions="""
## NOTION-SPECIFIC IDENTITY EXTRACTION:

ALWAYS extract and store:

1. PAGE ID MAPPINGS (CRITICAL):
   - Page ID <-> Page Title <-> Purpose/Location
   - Format: "[page-id] = '[Page Title]' in [Parent/Workspace]"
   
   Examples:
   - "abc123-def456 is 'Q4 OKRs' page in Company Wiki"
   - "xyz789-uvw012 is 'Meeting Notes Template' in Templates folder"
   - "Page 'Engineering Roadmap' has ID 98a7b6c5-d4e3-f2g1"

2. DATABASE ID MAPPINGS (CRITICAL):
   - Database ID <-> Database Name <-> Schema Summary
   - Format: "[db-id] = '[Database Name]' - [key properties]"
   
   Examples:
   - "db_abc123 is 'Tasks' database with Status, Assignee, Due Date properties"
   - "db_xyz789 is 'Team Directory' with Name, Email, Role, Team properties"
   - "'Sprint Board' database ID is 456def-789ghi, has Sprint, Story Points"

3. WORKSPACE STRUCTURE:
   - Top-level pages and their hierarchy
   - "Engineering workspace contains: Roadmap, Sprint Board, Docs, RFCs"
   - Team spaces and their owners

4. USER/MEMBER IDS:
   - Notion user IDs and their names
   - "notion_user_123 is John Smith (john@company.com)"
   - "Sarah Chen's Notion ID is abc-def-ghi"

5. TEMPLATE LOCATIONS:
   - Where templates live and what they're for
   - "'1:1 Meeting Notes' template is in page_id xyz"
   - "'Bug Report' template is in Engineering/Templates"

6. PROPERTY CONFIGURATIONS:
   - Select/Multi-select options in databases
   - "'Status' property has: Not Started, In Progress, Done, Blocked"
   - "Team property options: Frontend, Backend, Platform, Data"
""",
    provider_specific_instructions="""
## NOTION-SPECIFIC MEMORIES TO CAPTURE:

PAGE ORGANIZATION:
- Where different types of content live
- "Meeting notes go under 'Meetings' page (id: abc123)"
- "RFCs are created in 'Engineering/RFCs' database"
- User's personal page/workspace location

DATABASE USAGE PATTERNS:
- Which databases for what purpose
- Default property values user prefers
- Filter/sort views user commonly uses
- "When creating a task, default to 'Not Started' and assign to self"

CONTENT CREATION PATTERNS:
- Block types user prefers (toggles, callouts, code blocks)
- Heading structure preferences
- Template usage: when and which templates
- "User always starts docs with Overview callout block"

COLLABORATION PATTERNS:
- Who has access to what
- Sharing preferences
- Comment/mention patterns
- "Share engineering docs with engineering@company.com"

LINKED DATABASE PATTERNS:
- Which databases are linked where
- Synced block usage
- Cross-references user commonly makes

NAMING CONVENTIONS:
- How user titles pages and databases
- Date formats in titles
- Emoji usage in page names
- "Meeting notes titled: 'YYYY-MM-DD - Meeting with [Person]'"

ALWAYS MAP PAGE REFERENCES:
When user says "update the roadmap" or "add to my tasks":
- Identify which specific page/database they mean
- Store the mapping: "User's roadmap = page_id abc123"
- Store aliases: "The roadmap, engineering roadmap, our roadmap -> same page"
""",
)


# =============================================================================
# TWITTER MEMORY PROMPT
# =============================================================================

TWITTER_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Twitter",
    entity_instructions="""
## TWITTER-SPECIFIC IDENTITY EXTRACTION:

ALWAYS extract and store:

1. HANDLE <-> USER ID MAPPINGS (CRITICAL):
   - Twitter @handle <-> Numeric User ID <-> Display Name
   - Format: "@handle (ID: 12345678) = [Display Name/Description]"
   
   Examples:
   - "@elonmusk (ID: 44196397) is Elon Musk"
   - "@openai (ID: 1234567890) is OpenAI official account"
   - "User's account: @johndoe (ID: 9876543210)"

2. HANDLE <-> REAL IDENTITY MAPPINGS:
   - Connect Twitter handles to real people user knows
   - "@techsarah is Sarah Chen, user's colleague"
   - "@productguy99 is Mike from the Product team"
   - "@client_ceo is the CEO of BigClient Corp"

3. LIST IDS AND PURPOSES:
   - List ID <-> List Name <-> Purpose
   - "List 1234567 'Tech Leaders' tracks industry executives"
   - "List 'Competitors' (ID: 8765432) monitors competitor accounts"

4. IMPORTANT TWEET IDS:
   - Viral tweets, reference tweets, conversation threads
   - "Tweet 123456789 is the product launch announcement"
   - "Thread starting at tweet_id 987654321 is the technical explainer"

5. ACCOUNT RELATIONSHIPS:
   - Who user follows/followed by
   - Accounts user frequently engages with
   - "User regularly replies to @techcrunch and @theverge"
""",
    provider_specific_instructions="""
## TWITTER-SPECIFIC MEMORIES TO CAPTURE:

POSTING PATTERNS:
- User's tweet composition style
- Typical tweet length (short punchy vs. detailed)
- Thread usage: when and how they structure threads
- "User writes casual, conversational tweets, rarely uses formal language"

HASHTAG STRATEGY:
- Which hashtags for which topics
- "#buildinpublic for product updates"
- "#TechTwitter for industry commentary"
- How many hashtags (none, 1-2, or many)

ENGAGEMENT PATTERNS:
- Who to @mention for visibility
- Quote tweet vs retweet preferences
- Reply style (brief vs. detailed responses)
- "User QTs with commentary rather than plain RT"

TIMING PREFERENCES:
- Best times to post (if mentioned)
- Timezone considerations
- Scheduling preferences
- "User posts product updates Tuesday mornings EST"

MEDIA PREFERENCES:
- Image/video usage patterns
- Poll creation patterns
- Link card preferences

ACCOUNT MANAGEMENT:
- Multiple accounts? (personal vs. company)
- DM preferences and patterns
- Who to never engage with (blocklist context)

VOICE AND TONE:
- Professional vs casual vs humorous
- Emoji usage patterns
- How user responds to mentions/replies

NETWORK MAPPING:
Every time a handle is mentioned, store it:
- "Mentioned @handle -> [context of why they matter]"
- Build user's Twitter network in memory
""",
)


# =============================================================================
# CALENDAR MEMORY PROMPT
# =============================================================================

CALENDAR_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Google Calendar",
    entity_instructions="""
## CALENDAR-SPECIFIC IDENTITY EXTRACTION:

ALWAYS extract and store:

1. ATTENDEE EMAIL MAPPINGS (CRITICAL):
   - Every person invited to or mentioned for meetings
   - Format: "[Name] - [email] - [role/context]"
   
   Examples:
   - "John Smith (john.smith@company.com) - Engineering Manager, user's skip-level"
   - "Sarah Chen (sarah@company.com) - Direct report, frontend lead"
   - "client@bigcorp.com - Main client contact (Alex from BigCorp)"
   - "recruiting@company.com - Use for interview scheduling"

2. CALENDAR ID MAPPINGS (CRITICAL):
   - Calendar ID <-> Calendar Name <-> Purpose
   
   Examples:
   - "primary is user's main work calendar"
   - "cal_abc123@group.calendar.google.com is 'Team PTO' calendar"
   - "company-holidays@import.calendar.google.com is company holidays"
   - "cal_xyz789 is the 'Interview Scheduling' shared calendar"

3. RECURRING MEETING IDS:
   - Important recurring events with their IDs
   - "event_abc123 is 'Weekly Team Standup' every Monday 9am"
   - "event_xyz789 is '1:1 with Manager' every Thursday 2pm"

4. CONFERENCE ROOM RESOURCES:
   - Room email/ID <-> Room name <-> Capacity/Location
   - "room-123@resource.calendar.google.com is 'Hopper' (6 person, 4th floor)"
   - "room-456@resource is 'Turing' (large conf room, 20 person)"

5. MEETING LINK PATTERNS:
   - Zoom PMI links, Google Meet defaults
   - "User's Zoom PMI: https://zoom.us/j/1234567890"
   - "Team uses Google Meet by default"
""",
    provider_specific_instructions="""
## CALENDAR-SPECIFIC MEMORIES TO CAPTURE:

SCHEDULING PREFERENCES:
- Preferred meeting times/days
- "No meetings before 10am or after 5pm"
- "Fridays are focus time, no meetings"
- Default meeting duration by type
- "1:1s are 30 min, team syncs are 45 min, interviews are 1 hour"

ATTENDEE PATTERNS:
- Who to always include in certain meetings
- "Include PM (sarah@company.com) in all sprint planning"
- "CC manager (boss@company.com) on client meetings"
- Standing meeting participants

BUFFER PREFERENCES:
- Time between meetings
- "Always leave 15 min buffer between meetings"
- Back-to-back meeting tolerance

TIMEZONE HANDLING:
- User's timezone
- How to handle cross-timezone scheduling
- "User is PST, team is split PST/EST/London"
- "Schedule calls with India team before 10am PST"

CONFERENCING PREFERENCES:
- Zoom vs Google Meet vs Teams
- "Use Zoom for external meetings"
- "Use Google Meet for internal"
- Phone bridge preferences

RECURRING MEETING KNOWLEDGE:
- Weekly/monthly meeting cadences
- "Sprint planning is first Monday of sprint"
- "All-hands is first Thursday of month"

CALENDAR ORGANIZATION:
- Color coding system
- Which calendar for what
- Event naming conventions
- "Personal appointments on 'Personal' calendar, not primary"

AVAILABILITY PATTERNS:
- Working hours
- OOO/PTO patterns
- "User has kids pickup at 3pm, back online at 4pm"

MEETING TYPE TEMPLATES:
- What to include for different meeting types
- Standard attendees per meeting type
- Description/agenda templates

ALWAYS CAPTURE EVERY EMAIL IN CALENDAR CONTEXT:
Any email seen as an attendee or organizer - STORE IT.
Build a meeting attendee directory over time.
""",
)


# =============================================================================
# GITHUB MEMORY PROMPT
# =============================================================================

GITHUB_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="GitHub",
    entity_instructions="""
## GITHUB-SPECIFIC IDENTITY EXTRACTION:

ALWAYS extract and store:

1. USERNAME MAPPINGS (CRITICAL):
   - GitHub username <-> Real name <-> Email (if visible)
   - Format: "@github-user = [Real Name] - [context]"
   
   Examples:
   - "@johndoe-dev is John Smith, frontend lead on user's team"
   - "@sarahcodes is Sarah Chen, the main reviewer for backend PRs"
   - "@mike-company is Mike Johnson, DevOps, owns CI/CD"

2. REPOSITORY MAPPINGS:
   - owner/repo <-> Purpose/Description
   - "acme/backend-api is the main API service"
   - "acme/web-client is the React frontend"
   - "acme/infrastructure is Terraform configs"

3. TEAM STRUCTURES:
   - GitHub team slugs and their members/purpose
   - "@acme/frontend-team - Frontend engineers, review React PRs"
   - "@acme/platform - Platform team, owns infra and CI"

4. BRANCH CONVENTIONS:
   - Default branches per repo
   - Feature branch naming patterns
   - "acme/backend-api uses 'main' as default"
   - "Feature branches: feature/JIRA-123-description"

5. LABEL TAXONOMY:
   - What each label means in context
   - "bug = production issues, enhancement = new features"
   - "priority/p0 = drop everything, priority/p1 = this sprint"

6. ISSUE/PR PATTERNS:
   - Important issue/PR numbers
   - "Issue #456 is the API redesign epic"
   - "PR #789 is the pending security fix"
""",
    provider_specific_instructions="""
## GITHUB-SPECIFIC MEMORIES TO CAPTURE:

CODE REVIEW PATTERNS:
- Who reviews what
- "Backend PRs need review from @sarahcodes"
- "@mike-company must approve any CI changes"
- Required reviewers per area

PR CONVENTIONS:
- PR title/description formats
- Labels to apply
- "Use conventional commits in PR titles"
- Template usage

REPOSITORY OWNERSHIP:
- Who owns which repos/areas
- "@johndoe-dev owns the auth module"
- "Infra changes go through @platform-team"

CI/CD KNOWLEDGE:
- What checks run on PRs
- How to trigger deployments
- Common failure patterns and fixes

BRANCH STRATEGIES:
- Git flow vs trunk-based
- Release branch patterns
- Hotfix procedures

CODEOWNERS CONTEXT:
- Who gets auto-requested for reviews
- What patterns map to which owners

WORKFLOW PATTERNS:
- Draft PR usage
- Squash vs merge commit preferences
- Auto-merge settings

CROSS-REPO RELATIONSHIPS:
- Which repos depend on each other
- Monorepo vs polyrepo structure
""",
)


# =============================================================================
# LINEAR MEMORY PROMPT
# =============================================================================

LINEAR_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Linear",
    entity_instructions="""
## LINEAR-SPECIFIC IDENTITY EXTRACTION:

ALWAYS extract and store:

1. USER ID MAPPINGS:
   - Linear user ID <-> Name <-> Email
   - "user_abc123 is John Smith (john@company.com)"
   - "Sarah Chen's Linear ID is user_xyz789"

2. TEAM ID MAPPINGS (CRITICAL):
   - Team ID <-> Team Key <-> Team Name
   - "team_123 is ENG (Engineering)"
   - "team_456 is PROD (Product)"
   - "team_789 is DES (Design)"

3. PROJECT MAPPINGS:
   - Project ID <-> Name <-> Team
   - "project_abc is 'API Redesign' under ENG"
   - "project_xyz is 'Q4 Launch' under PROD"

4. ISSUE IDENTIFIER PATTERNS:
   - Team prefix + number (e.g., ENG-123)
   - Important/recurring issues
   - "ENG-500 is the tech debt epic"

5. LABEL TAXONOMY:
   - Labels and their meanings
   - "bug, feature, improvement, chore"
   - Team-specific labels

6. CYCLE/SPRINT PATTERNS:
   - Sprint naming conventions
   - Sprint duration and cadence
   - "2-week sprints, Monday start"
""",
    provider_specific_instructions="""
## LINEAR-SPECIFIC MEMORIES TO CAPTURE:

ISSUE CREATION PATTERNS:
- Default team for new issues
- Default labels and priority
- Template usage
- "User's issues default to ENG team, priority 2"

WORKFLOW KNOWLEDGE:
- Status values and transitions
- "Statuses: Backlog -> Todo -> In Progress -> In Review -> Done"
- What triggers status changes

ASSIGNEE PATTERNS:
- Who handles what types of issues
- Default assignees
- "Bug triage goes to @oncall"

PRIORITY CONVENTIONS:
- What each priority means
- "P0 = production down, P1 = this sprint, P2 = next sprint"

CYCLE/SPRINT CONTEXT:
- Current and upcoming sprints
- Sprint goals and capacity
- Sprint planning patterns

ESTIMATE PATTERNS:
- Story point scale
- Hour estimation patterns
- "Fibonacci: 1, 2, 3, 5, 8"

PROJECT HIERARCHY:
- Projects and sub-issues
- Epic structure
- Blocking relationships
""",
)


# =============================================================================
# GOOGLE DOCS MEMORY PROMPT
# =============================================================================

GOOGLE_DOCS_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Google Docs",
    entity_instructions="""
## GOOGLE DOCS-SPECIFIC IDENTITY EXTRACTION:

1. DOCUMENT ID MAPPINGS (CRITICAL):
   - Document ID <-> Title <-> Purpose
   - "doc_abc123 is 'Q4 Strategy Document'"
   - "doc_xyz789 is 'Engineering Handbook'"

2. FOLDER STRUCTURE:
   - Folder IDs and hierarchy
   - "folder_123 is 'Engineering Docs' containing team docs"

3. COLLABORATOR EMAILS:
   - Who has access/edits docs
   - "sarah@company.com co-edits the strategy docs"

4. TEMPLATE DOCUMENTS:
   - Template doc IDs and purposes
   - "doc_template123 is the 'RFC Template'"
""",
    provider_specific_instructions="""
## GOOGLE DOCS-SPECIFIC MEMORIES:

DOCUMENT ORGANIZATION:
- Where different types of docs live
- Naming conventions
- "RFCs go in Engineering/RFCs folder"

FORMATTING PREFERENCES:
- Heading styles
- Font preferences
- Standard document structure

COLLABORATION PATTERNS:
- Suggestion mode vs editing mode
- Comment conventions
- Sharing defaults

EXPORT PREFERENCES:
- PDF vs Word vs other formats
- When to export vs share link
""",
)


# =============================================================================
# GOOGLE SHEETS MEMORY PROMPT
# =============================================================================

GOOGLE_SHEETS_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Google Sheets",
    entity_instructions="""
## GOOGLE SHEETS-SPECIFIC IDENTITY EXTRACTION:

1. SPREADSHEET ID MAPPINGS (CRITICAL):
   - Spreadsheet ID <-> Name <-> Purpose
   - "sheet_abc123 is 'Q4 Budget Tracker'"
   - "sheet_xyz789 is 'Team Capacity Planning'"

2. SHEET TAB NAMES:
   - Tab names within spreadsheets
   - "'Budget Tracker' has tabs: Summary, Monthly, Categories"

3. NAMED RANGES:
   - Named range <-> Location <-> Purpose
   - "'revenue_data' is A1:D100 in Monthly tab"

4. COLLABORATOR ACCESS:
   - Who edits which sheets
   - "Finance team owns Budget Tracker"
""",
    provider_specific_instructions="""
## GOOGLE SHEETS-SPECIFIC MEMORIES:

DATA PATTERNS:
- Column structures and meanings
- Row organization
- Data validation rules

FORMULA PATTERNS:
- Common formulas user creates
- VLOOKUP/XLOOKUP patterns
- Pivot table preferences

SHARING PATTERNS:
- Who has access to what
- View vs edit permissions

IMPORT/EXPORT:
- CSV import preferences
- Export format preferences
""",
)


# =============================================================================
# GOOGLE TASKS MEMORY PROMPT
# =============================================================================

GOOGLE_TASKS_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Google Tasks",
    entity_instructions="""
## GOOGLE TASKS-SPECIFIC IDENTITY EXTRACTION:

1. TASK LIST ID MAPPINGS:
   - Task list ID <-> Name <-> Purpose
   - "list_abc123 is 'Work Tasks'"
   - "list_xyz789 is 'Personal'"

2. RECURRING TASK PATTERNS:
   - Regular tasks and their schedules
   - "Weekly review task every Friday"
""",
    provider_specific_instructions="""
## GOOGLE TASKS-SPECIFIC MEMORIES:

TASK ORGANIZATION:
- Which list for what type of tasks
- Subtask usage patterns
- Due date preferences

TASK CREATION PATTERNS:
- Default list
- Notes/description conventions
- Priority indication (starred, naming)
""",
)


# =============================================================================
# GOOGLE MEET MEMORY PROMPT
# =============================================================================

GOOGLE_MEET_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Google Meet",
    entity_instructions="""
## GOOGLE MEET-SPECIFIC IDENTITY EXTRACTION:

1. MEETING LINK PATTERNS:
   - Personal meeting links
   - Recurring meeting links

2. ATTENDEE EMAILS:
   - Regular meeting participants
   - Their roles and contexts
""",
    provider_specific_instructions="""
## GOOGLE MEET-SPECIFIC MEMORIES:

MEETING PREFERENCES:
- Recording preferences
- Transcription usage
- Participant settings

SCHEDULING PATTERNS:
- Meeting duration defaults
- Calendar integration patterns
""",
)


# =============================================================================
# GOOGLE MAPS MEMORY PROMPT
# =============================================================================

GOOGLE_MAPS_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Google Maps",
    entity_instructions="""
## GOOGLE MAPS-SPECIFIC IDENTITY EXTRACTION:

1. SAVED LOCATIONS:
   - Place IDs <-> Names <-> Purposes
   - "Home, Work, Gym locations"

2. FREQUENT ROUTES:
   - Common origin-destination pairs
   - "Home to Office route"
""",
    provider_specific_instructions="""
## GOOGLE MAPS-SPECIFIC MEMORIES:

TRANSPORTATION PREFERENCES:
- Driving vs transit vs walking
- Avoid highways/tolls preferences
- Time optimization vs distance

PLACE PREFERENCES:
- Favorite restaurants by cuisine
- Preferred locations by category
""",
)


# =============================================================================
# LINKEDIN MEMORY PROMPT
# =============================================================================

LINKEDIN_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="LinkedIn",
    entity_instructions="""
## LINKEDIN-SPECIFIC IDENTITY EXTRACTION:

1. PROFILE URN MAPPINGS:
   - User's own URN for posting
   - Connection URNs for engagement

2. COMPANY PAGE IDS:
   - Company pages user manages/engages with
   - "Company page urn:li:company:12345 is 'Acme Corp'"

3. POST URNS:
   - Important posts for reference
   - Viral content IDs
""",
    provider_specific_instructions="""
## LINKEDIN-SPECIFIC MEMORIES:

POSTING PATTERNS:
- Content types (text, image, article)
- Posting frequency and timing
- Hashtag usage

ENGAGEMENT PATTERNS:
- Who to engage with
- Comment style
- Reaction preferences

VOICE AND TONE:
- Professional tone
- Personal brand voice
- Industry-specific language
""",
)


# =============================================================================
# TODOIST MEMORY PROMPT
# =============================================================================

TODOIST_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Todoist",
    entity_instructions="""
## TODOIST-SPECIFIC IDENTITY EXTRACTION:

1. PROJECT ID MAPPINGS:
   - Project ID <-> Name <-> Purpose
   - "project_123 is 'Work' for professional tasks"
   - "project_456 is 'Personal' for home stuff"

2. LABEL TAXONOMY:
   - Labels and their meanings
   - "@urgent, @waiting, @someday"

3. FILTER PATTERNS:
   - Saved filters and their queries
   - "'Today's Focus' filter shows P1 due today"
""",
    provider_specific_instructions="""
## TODOIST-SPECIFIC MEMORIES:

TASK CREATION PATTERNS:
- Default project
- Priority usage (P1-P4)
- Due date patterns
- Label conventions

PROJECT ORGANIZATION:
- Project hierarchy
- Section usage within projects
- Archive patterns

QUICK ADD PATTERNS:
- Natural language preferences
- Shorthand user uses
""",
)


# =============================================================================
# REDDIT MEMORY PROMPT
# =============================================================================

REDDIT_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Reddit",
    entity_instructions="""
## REDDIT-SPECIFIC IDENTITY EXTRACTION:

1. SUBREDDIT PREFERENCES:
   - Subreddits user follows/engages with
   - "r/programming, r/technology"

2. USER REFERENCES:
   - Reddit usernames of interest
   - "u/expert_user is helpful in r/python"

3. POST REFERENCES:
   - Important post IDs for reference
""",
    provider_specific_instructions="""
## REDDIT-SPECIFIC MEMORIES:

ENGAGEMENT PATTERNS:
- Comment style
- Upvote/downvote behavior
- Posting frequency

CONTENT PREFERENCES:
- Topics of interest
- Flair usage
- NSFW filter settings
""",
)


# =============================================================================
# AIRTABLE MEMORY PROMPT
# =============================================================================

AIRTABLE_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Airtable",
    entity_instructions="""
## AIRTABLE-SPECIFIC IDENTITY EXTRACTION:

1. BASE ID MAPPINGS (CRITICAL):
   - Base ID <-> Name <-> Purpose
   - "app_abc123 is 'Project Tracker' base"

2. TABLE MAPPINGS:
   - Table ID <-> Name <-> Key Fields
   - "tbl_xyz is 'Tasks' with Status, Assignee, Due Date"

3. VIEW MAPPINGS:
   - View ID <-> Name <-> Filter/Sort
   - "viw_123 is 'My Tasks' filtered to current user"
""",
    provider_specific_instructions="""
## AIRTABLE-SPECIFIC MEMORIES:

SCHEMA KNOWLEDGE:
- Field types and options
- Linked records relationships
- Formula field patterns

VIEW PREFERENCES:
- Grid vs Kanban vs Calendar
- Filter and sort defaults

RECORD PATTERNS:
- Default values
- Required fields
- Naming conventions
""",
)


# =============================================================================
# HUBSPOT MEMORY PROMPT
# =============================================================================

HUBSPOT_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="HubSpot",
    entity_instructions="""
## HUBSPOT-SPECIFIC IDENTITY EXTRACTION:

1. CONTACT ID MAPPINGS (CRITICAL):
   - Contact ID <-> Name <-> Email <-> Company
   - "contact_123 is John Smith (john@bigclient.com) at BigClient Corp"

2. COMPANY ID MAPPINGS:
   - Company ID <-> Name <-> Industry
   - "company_456 is 'BigClient Corp' in Technology"

3. DEAL ID MAPPINGS:
   - Deal ID <-> Name <-> Stage <-> Value
   - "deal_789 is 'BigClient Enterprise' in Negotiation, $100k"

4. PIPELINE STAGES:
   - Stage IDs and names
   - "Pipeline stages: Lead -> Qualified -> Proposal -> Negotiation -> Closed"
""",
    provider_specific_instructions="""
## HUBSPOT-SPECIFIC MEMORIES:

CONTACT MANAGEMENT:
- Lead sources
- Contact properties used
- Lifecycle stages

DEAL WORKFLOW:
- Pipeline structure
- Stage requirements
- Deal creation patterns

EMAIL INTEGRATION:
- Template usage
- Tracking preferences
- Sequence patterns
""",
)


# =============================================================================
# ASANA MEMORY PROMPT
# =============================================================================

ASANA_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Asana",
    entity_instructions="""
## ASANA-SPECIFIC IDENTITY EXTRACTION:

1. WORKSPACE/ORG IDS:
   - Workspace ID <-> Name
   - "workspace_123 is 'Acme Corp'"

2. PROJECT ID MAPPINGS:
   - Project ID <-> Name <-> Team
   - "project_abc is 'Q4 Launch' in Product team"

3. USER ID MAPPINGS:
   - User ID <-> Name <-> Email
   - "user_xyz is John Smith (john@company.com)"

4. TEAM STRUCTURES:
   - Team ID <-> Name <-> Members
""",
    provider_specific_instructions="""
## ASANA-SPECIFIC MEMORIES:

PROJECT PATTERNS:
- Template usage
- Section organization
- Custom fields

TASK CREATION:
- Default project/section
- Assignee patterns
- Due date conventions

WORKFLOW:
- Status transitions
- Approval processes
- Dependency handling
""",
)


# =============================================================================
# TRELLO MEMORY PROMPT
# =============================================================================

TRELLO_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Trello",
    entity_instructions="""
## TRELLO-SPECIFIC IDENTITY EXTRACTION:

1. BOARD ID MAPPINGS:
   - Board ID <-> Name <-> Purpose
   - "board_abc is 'Sprint Board'"

2. LIST MAPPINGS:
   - List ID <-> Name <-> Workflow Stage
   - "list_xyz is 'In Progress' column"

3. LABEL MAPPINGS:
   - Color <-> Meaning
   - "Red = Urgent, Green = Feature, Blue = Bug"
""",
    provider_specific_instructions="""
## TRELLO-SPECIFIC MEMORIES:

BOARD ORGANIZATION:
- List structure/workflow
- Label taxonomy
- Power-Up usage

CARD PATTERNS:
- Checklist conventions
- Due date usage
- Member assignment patterns
""",
)


# =============================================================================
# CLICKUP MEMORY PROMPT
# =============================================================================

CLICKUP_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="ClickUp",
    entity_instructions="""
## CLICKUP-SPECIFIC IDENTITY EXTRACTION:

1. WORKSPACE/SPACE IDS:
   - Space ID <-> Name <-> Purpose
   - "space_123 is 'Engineering'"

2. FOLDER/LIST MAPPINGS:
   - List ID <-> Name <-> Parent
   - "list_abc is 'Sprint 23' in Engineering"

3. STATUS CONFIGURATIONS:
   - Status names per list
   - "Open -> In Progress -> Review -> Closed"
""",
    provider_specific_instructions="""
## CLICKUP-SPECIFIC MEMORIES:

HIERARCHY PATTERNS:
- Space/Folder/List structure
- Template usage

TASK MANAGEMENT:
- Priority conventions
- Time tracking usage
- Custom field patterns

VIEW PREFERENCES:
- List vs Board vs Gantt
- Saved views
""",
)


# =============================================================================
# MICROSOFT TEAMS MEMORY PROMPT
# =============================================================================

MICROSOFT_TEAMS_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Microsoft Teams",
    entity_instructions="""
## TEAMS-SPECIFIC IDENTITY EXTRACTION:

1. TEAM ID MAPPINGS:
   - Team ID <-> Name <-> Purpose
   - "team_abc is 'Engineering' team"

2. CHANNEL ID MAPPINGS:
   - Channel ID <-> Name <-> Team
   - "channel_xyz is 'General' in Engineering"

3. USER ID MAPPINGS:
   - User ID <-> Name <-> Email
   - "user_123 is John Smith (john@company.com)"
""",
    provider_specific_instructions="""
## TEAMS-SPECIFIC MEMORIES:

CHANNEL USAGE:
- Which channel for what
- @mention patterns
- File sharing conventions

MEETING PATTERNS:
- Scheduling preferences
- Teams vs other platforms

MESSAGE STYLE:
- Formatting preferences
- When to use chat vs channel
""",
)


# =============================================================================
# INSTAGRAM MEMORY PROMPT
# =============================================================================

INSTAGRAM_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Instagram",
    entity_instructions="""
## INSTAGRAM-SPECIFIC IDENTITY EXTRACTION:

1. USERNAME MAPPINGS:
   - @handle <-> Real identity
   - "@john_photos is John Smith, the user"

2. HASHTAG COLLECTIONS:
   - Hashtag groups by topic
   - "#photography #streetphoto #urbanshots"
""",
    provider_specific_instructions="""
## INSTAGRAM-SPECIFIC MEMORIES:

POSTING PATTERNS:
- Caption style
- Hashtag strategy
- Story vs Post vs Reel

ENGAGEMENT PATTERNS:
- Comment style
- DM usage
- Collaboration patterns
""",
)


# =============================================================================
# PERPLEXITY MEMORY PROMPT
# =============================================================================

PERPLEXITY_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Perplexity",
    entity_instructions="""
## PERPLEXITY-SPECIFIC EXTRACTION:

1. SEARCH PATTERNS:
   - Topic areas of interest
   - Query formulation style

2. SOURCE PREFERENCES:
   - Trusted sources
   - Source types preferred
""",
    provider_specific_instructions="""
## PERPLEXITY-SPECIFIC MEMORIES:

SEARCH PATTERNS:
- Depth preferences (quick vs comprehensive)
- Follow-up patterns
- Citation needs

OUTPUT PREFERENCES:
- Format (bullets, paragraphs)
- Technical depth
- Language style
""",
)


# =============================================================================
# DEEPWIKI MEMORY PROMPT
# =============================================================================

DEEPWIKI_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="DeepWiki",
    entity_instructions="""
## DEEPWIKI-SPECIFIC EXTRACTION:

1. REPOSITORY PATTERNS:
   - Repos frequently explored
   - "github.com/org/repo patterns"

2. DOCUMENTATION INTERESTS:
   - Architecture vs API vs usage
   - Specific file patterns
""",
    provider_specific_instructions="""
## DEEPWIKI-SPECIFIC MEMORIES:

EXPLORATION PATTERNS:
- Depth preferences
- File type priorities
- Code vs docs preference

OUTPUT PREFERENCES:
- Example code needs
- Explanation depth
- Language/framework focus
""",
)


# =============================================================================
# CONTEXT7 MEMORY PROMPT
# =============================================================================

CONTEXT7_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Context7",
    entity_instructions="""
## CONTEXT7-SPECIFIC EXTRACTION:

1. LIBRARY INTERESTS:
   - Libraries frequently queried
   - Version tracking needs

2. API PATTERNS:
   - API depth preferences
   - Integration patterns
""",
    provider_specific_instructions="""
## CONTEXT7-SPECIFIC MEMORIES:

DOCUMENTATION NEEDS:
- Code example preferences
- API reference depth
- Framework focus areas

OUTPUT PREFERENCES:
- Format preferences
- Language-specific needs
""",
)


# =============================================================================
# INTERNAL TODO MEMORY PROMPT
# =============================================================================

TODO_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Todo",
    entity_instructions="""
## TODO-SPECIFIC EXTRACTION:

1. PROJECT MAPPINGS:
   - Project IDs and names
   - "project_work is 'Work Tasks'"

2. LABEL TAXONOMY:
   - Labels and meanings
   - Priority conventions
""",
    provider_specific_instructions="""
## TODO-SPECIFIC MEMORIES:

TASK PATTERNS:
- Creation conventions
- Organization preferences
- Due date patterns

WORKFLOW:
- Completion patterns
- Review cadence
""",
)


# =============================================================================
# INTERNAL REMINDERS MEMORY PROMPT
# =============================================================================

REMINDER_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Reminders",
    entity_instructions="""
## REMINDER-SPECIFIC EXTRACTION:

1. TIMING PATTERNS:
   - Preferred reminder times
   - Recurring patterns

2. CATEGORY PATTERNS:
   - Types of reminders
   - Priority levels
""",
    provider_specific_instructions="""
## REMINDER-SPECIFIC MEMORIES:

TIMING PREFERENCES:
- Morning vs evening
- Timezone handling
- Snooze behavior

MESSAGE PATTERNS:
- Reminder message style
- Notification channel preferences
""",
)


# =============================================================================
# INTERNAL GOALS MEMORY PROMPT
# =============================================================================

GOALS_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Goals",
    entity_instructions="""
## GOALS-SPECIFIC EXTRACTION:

1. GOAL MAPPINGS:
   - Goal IDs and titles
   - Category/type patterns

2. ROADMAP PATTERNS:
   - Milestone structure
   - Progress tracking
""",
    provider_specific_instructions="""
## GOALS-SPECIFIC MEMORIES:

GOAL PATTERNS:
- Creation conventions
- Categorization preferences
- Timeline patterns

TRACKING PATTERNS:
- Progress update frequency
- Milestone definitions
- Review cadence
""",
)


# =============================================================================
# MCP INTEGRATIONS MEMORY PROMPTS
# =============================================================================

HACKERNEWS_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Hacker News",
    entity_instructions="""
## HACKERNEWS-SPECIFIC EXTRACTION:

1. TOPIC INTERESTS:
   - Subject areas followed
   - Author preferences

2. ENGAGEMENT PATTERNS:
   - Story types (Show HN, Ask HN)
   - Comment depth
""",
    provider_specific_instructions="""
## HACKERNEWS-SPECIFIC MEMORIES:

CONTENT PREFERENCES:
- Topic areas
- Time window for stories
- Comment engagement depth
""",
)

INSTACART_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Instacart",
    entity_instructions="""
## INSTACART-SPECIFIC EXTRACTION:

1. STORE PREFERENCES:
   - Preferred stores
   - Location patterns

2. PRODUCT PATTERNS:
   - Common items
   - Brand preferences
""",
    provider_specific_instructions="""
## INSTACART-SPECIFIC MEMORIES:

SHOPPING PATTERNS:
- Regular items
- Substitution preferences
- Delivery time preferences

DIETARY CONTEXT:
- Restrictions/preferences
- Organic/natural preferences
""",
)

YELP_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Yelp",
    entity_instructions="""
## YELP-SPECIFIC EXTRACTION:

1. LOCATION PREFERENCES:
   - Neighborhoods/areas
   - Distance tolerance

2. CUISINE/CATEGORY:
   - Food preferences
   - Business categories
""",
    provider_specific_instructions="""
## YELP-SPECIFIC MEMORIES:

DINING PREFERENCES:
- Cuisine types
- Price range
- Dietary needs

SEARCH PATTERNS:
- Rating thresholds
- Review reading habits
""",
)

AGENTMAIL_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="AgentMail",
    entity_instructions="""
## AGENTMAIL-SPECIFIC EXTRACTION:

1. MAILBOX PATTERNS:
   - Mailbox configurations
   - Automation rules

2. EMAIL PATTERNS:
   - Template usage
   - Response patterns
""",
    provider_specific_instructions="""
## AGENTMAIL-SPECIFIC MEMORIES:

AUTOMATION PATTERNS:
- Email workflows
- Response templates
- Thread management
""",
)

BROWSERBASE_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="Browserbase",
    entity_instructions="""
## BROWSERBASE-SPECIFIC EXTRACTION:

1. URL PATTERNS:
   - Common sites visited
   - Navigation patterns

2. AUTOMATION PATTERNS:
   - Workflow types
   - Session configurations
""",
    provider_specific_instructions="""
## BROWSERBASE-SPECIFIC MEMORIES:

BROWSER PATTERNS:
- Navigation workflows
- Form filling preferences
- Screenshot/capture patterns
""",
)

POSTHOG_MEMORY_PROMPT = BASE_MEMORY_EXTRACTION_PROMPT.format(
    provider_name="PostHog",
    entity_instructions="""
## POSTHOG-SPECIFIC EXTRACTION:

1. EVENT PATTERNS:
   - Key events tracked
   - Funnel structures

2. COHORT DEFINITIONS:
   - User segments
   - Filter criteria
""",
    provider_specific_instructions="""
## POSTHOG-SPECIFIC MEMORIES:

ANALYTICS PATTERNS:
- Dashboard preferences
- Report types
- A/B test patterns

FEATURE FLAG USAGE:
- Flag naming conventions
- Rollout patterns
""",
)
