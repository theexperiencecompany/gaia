"""
Rich marketplace content for native integrations.

Each entry is keyed by the integration ID and imported into oauth_config.py
to populate the content field on each OAuthIntegration — keeping
oauth_config.py clean while keeping content colocated with the config.

Content is only returned from the /integrations/public/{id} detail endpoint,
never from the list or config endpoints.
"""

from app.models.oauth_models import (
    IntegrationContent,
    IntegrationFAQ,
    IntegrationHowItWorksStep,
)

GOOGLECALENDAR_CONTENT = IntegrationContent(
    use_cases=[
        "Schedule meetings by describing your availability in plain English, and GAIA books the slot instantly",
        "Get a morning briefing of every event happening today, delivered to your chat",
        "Find open time slots across multiple calendars with a single question",
        "Create recurring events, set reminders, and invite attendees without opening Calendar",
        "Reschedule or cancel events on the fly by just telling GAIA what changed",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Google Calendar to GAIA",
            body="Open the GAIA Marketplace, find Google Calendar, and click \"Add to your GAIA\". You'll be redirected to Google's OAuth consent screen. Grant calendar access and you're connected in under two minutes.",
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what to schedule in plain English",
            body='Say things like "block two hours tomorrow for deep work" or "schedule a 30-minute call with Alex on Friday at 3 PM and send him an invite". GAIA understands context and handles the details.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA manages your calendar automatically",
            body="GAIA can monitor your calendar, send you proactive reminders before events, and trigger workflows, like sending a Slack message when a meeting is about to start.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA access all my Google Calendars?",
            answer="Yes. GAIA requests access to all calendars in your Google account. You can ask it to read from or write to any specific calendar by name, or use your primary calendar by default.",
        ),
        IntegrationFAQ(
            question="Will GAIA send invites to other people?",
            answer="Yes, if you ask GAIA to invite attendees when creating an event, it will add them and Google Calendar will send the invite on your behalf, exactly as if you'd created it manually.",
        ),
        IntegrationFAQ(
            question="Can I set up automatic reminders for upcoming events?",
            answer="Absolutely. You can ask GAIA to remind you X minutes before any event, or set up a daily morning briefing that summarises your schedule for the day automatically.",
        ),
        IntegrationFAQ(
            question="Does the Google Calendar integration work with Google Meet?",
            answer="Yes. When creating events, GAIA can automatically add a Google Meet link. You can also connect the separate Google Meet integration for even deeper meeting management.",
        ),
    ],
)

GOOGLEDOCS_CONTENT = IntegrationContent(
    use_cases=[
        "Create a fully formatted Google Doc by describing what you need, and GAIA writes and structures it",
        "Search across all your documents and pull out specific information without opening Drive",
        "Update or append to an existing document by just telling GAIA what to change",
        "Generate meeting notes, project briefs, or reports from a short description",
        "Copy and repurpose existing documents into new ones with a single instruction",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Google Docs to GAIA",
            body='Open the GAIA Marketplace, find Google Docs, and click "Add to your GAIA". Authorise access via Google OAuth, which takes under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Describe what you need in plain English",
            body='Say "create a project proposal for a mobile app redesign" or "find my Q3 review doc and add a summary section". GAIA handles the creation, formatting, and editing for you.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA writes, edits, and organises your docs",
            body="GAIA can create new documents with proper structure, update existing ones, search your Drive for content, and even trigger workflows when documents are created or modified.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA create documents with proper formatting?",
            answer="Yes. GAIA creates Google Docs with markdown-style formatting (headings, bullet points, bold text, and more) rendered natively in Google Docs.",
        ),
        IntegrationFAQ(
            question="Can GAIA search my existing documents?",
            answer="Yes. You can ask GAIA to find documents by name, topic, or content. It will search your Google Drive and return matching documents.",
        ),
        IntegrationFAQ(
            question="Can GAIA edit a document I already have?",
            answer="Yes. GAIA can append content, replace text, update sections, or rewrite portions of an existing document. Just describe what you want changed.",
        ),
        IntegrationFAQ(
            question="Does GAIA need full access to my Google Drive?",
            answer="GAIA requests the minimum scopes needed for Docs operations. It can create, read, and edit Google Docs files but does not access other Drive file types unless you connect additional integrations.",
        ),
    ],
)

GOOGLEDRIVE_CONTENT = IntegrationContent(
    use_cases=[
        "Find any file by name, type, or content without digging through folders",
        "Ask GAIA to organize files: create folders, move files, and tidy up your Drive",
        "Share a file or folder with someone at the right permission level in one instruction",
        "Pull a file from Drive straight into an email as an attachment",
        "Save notes, summaries, or generated content to Drive as a new file",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Google Drive to GAIA",
            body='Open the GAIA Marketplace, find Google Drive, and click "Add to your GAIA". Authorise access via Google OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what you need from your files",
            body='Say "find the signed lease PDF" or "share the Q4 folder with priya@company.com as a viewer". GAIA searches, organizes, shares, and retrieves for you.',
        ),
        IntegrationHowItWorksStep(
            title="Use your files anywhere in GAIA",
            body="A file in Drive can flow into the rest of GAIA. Attach it to a Gmail draft, summarize it, or reference it in a task, all from chat.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA find a file when I only remember roughly what it is?",
            answer="Yes. Describe the file by name, type, or what's in it and GAIA searches your Drive, then returns the matches with links.",
        ),
        IntegrationFAQ(
            question="Can GAIA attach a Drive file to an email?",
            answer="Yes. GAIA can pull a file from Drive and attach it to a Gmail draft, so you can review and send it without downloading anything yourself.",
        ),
        IntegrationFAQ(
            question="Will GAIA delete my files?",
            answer="Only if you ask, and permanent deletes always require your explicit confirmation first. GAIA prefers moving files to trash, which is recoverable.",
        ),
        IntegrationFAQ(
            question="Who can see files GAIA shares on my behalf?",
            answer="Only the people you name, at the permission level you specify. GAIA does not change sharing settings unless you ask it to.",
        ),
    ],
)

GMAIL_CONTENT = IntegrationContent(
    use_cases=[
        "Send emails by describing who you're writing to and what you want to say, and GAIA drafts and sends it",
        "Get a briefing every morning of what needs your reply, what you're waiting on, and today's events",
        "Search your inbox by topic, sender, or keyword instantly from chat",
        'Reply to emails with a quick instruction like "reply and say I\'ll join at 3 PM"',
        "Trigger workflows when specific emails arrive, like logging leads from contact form submissions",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Gmail to GAIA",
            body="Open the GAIA Marketplace, find Gmail, and click \"Add to your GAIA\". You'll be redirected to Google's OAuth consent screen. Grant mail access and you're done in under two minutes.",
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what to do with your email",
            body='Say "send Alex a follow-up about the proposal" or "find all emails from Stripe this month and summarise them". GAIA handles composing, sending, searching, and summarising.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA manages your inbox in the background",
            body="Set up email triggers: GAIA can notify you on Slack when a VIP sender writes, automatically log incoming leads to a spreadsheet, or send you a weekly summary of unread threads.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA send emails on my behalf?",
            answer="Yes. When you ask GAIA to send an email, it composes and delivers it from your Gmail account exactly as if you'd sent it manually. You can review the draft first if you prefer.",
        ),
        IntegrationFAQ(
            question="Can GAIA read all my emails?",
            answer="GAIA requests Gmail read access to search and summarise emails when you ask, and to read new mail once a day for your morning inbox briefing. You can change when that briefing runs, or stop it, by telling GAIA.",
        ),
        IntegrationFAQ(
            question="Can I set up email-based triggers for workflows?",
            answer="Yes. You can create GAIA workflows that fire when emails matching specific criteria arrive, for example from a particular sender, with a subject keyword, or containing attachments.",
        ),
        IntegrationFAQ(
            question="Does GAIA store copies of my emails?",
            answer="No. GAIA fetches email data on demand to fulfill your requests. It does not store email content beyond what's needed to complete the current task.",
        ),
    ],
)

NOTION_CONTENT = IntegrationContent(
    use_cases=[
        "Create new Notion pages and database entries by describing them in plain English",
        "Search across your entire Notion workspace and pull out specific information instantly",
        "Add meeting notes, action items, or journal entries to Notion without opening the app",
        "Query Notion databases: filter, sort, and summarise records with natural language",
        "Trigger workflows when new Notion pages are created in a specific database",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Notion to GAIA",
            body='Open the GAIA Marketplace, find Notion, and click "Add to your GAIA". Authorise via OAuth and grant GAIA access to the pages and databases you want it to work with.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA to read or write to Notion",
            body='Say "add a new task to my Projects database with a due date of Friday" or "find all pages tagged #marketing and summarise them". GAIA knows your Notion structure and handles the details.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps Notion in sync with your work",
            body="GAIA can automatically log completed tasks, create weekly review pages, or update database properties when you finish work, all triggered by your natural language instructions.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Which Notion pages can GAIA access?",
            answer="GAIA can only access pages and databases you explicitly share with it during the OAuth connection. You can update these permissions at any time from your Notion settings.",
        ),
        IntegrationFAQ(
            question="Can GAIA create entries in a Notion database?",
            answer="Yes. GAIA can create database entries with properties like text, dates, selects, and relations. Just describe the entry you want and it handles the rest.",
        ),
        IntegrationFAQ(
            question="Can GAIA search inside Notion pages?",
            answer="Yes. GAIA can search your Notion workspace by keyword, page title, or content and return relevant results, useful for quickly finding notes, docs, or project info.",
        ),
        IntegrationFAQ(
            question="Can GAIA update existing Notion pages?",
            answer="Yes. GAIA can append content to pages, update database properties, and modify existing records. Just tell it what to change and it finds and updates the right page.",
        ),
    ],
)

TWITTER_CONTENT = IntegrationContent(
    use_cases=[
        "Post tweets and threads by describing what you want to say, and GAIA writes and publishes them",
        "Search Twitter for mentions, keywords, or trending topics and get a clean summary",
        "Monitor mentions of your handle and get notified in chat when someone tags you",
        "Draft replies to tweets by giving GAIA context on how you want to respond",
        "Research what's being said about a topic or competitor with a single question",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Twitter to GAIA",
            body='Open the GAIA Marketplace, find Twitter, and click "Add to your GAIA". Authorise via Twitter OAuth, which takes under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what to post or find",
            body='Say "tweet about our new feature launch in a casual tone" or "find tweets mentioning @yourbrand from the last 24 hours". GAIA handles the writing and the API calls.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps you on top of Twitter",
            body="Set up monitoring workflows: GAIA can alert you when you get mentioned, summarise trending discussions in your niche, or help you maintain a consistent posting schedule.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA post tweets directly from chat?",
            answer="Yes. When you ask GAIA to post a tweet, it publishes immediately to your connected Twitter account. You can ask it to draft first for review if you prefer.",
        ),
        IntegrationFAQ(
            question="Can GAIA post threads?",
            answer="Yes. GAIA can compose and post multi-tweet threads. Just describe the topic and key points, and GAIA writes the thread and posts each tweet in sequence.",
        ),
        IntegrationFAQ(
            question="Can GAIA search Twitter for specific topics?",
            answer="Yes. You can ask GAIA to search Twitter for any keyword, hashtag, or mention and get a summarised report of what's being said.",
        ),
        IntegrationFAQ(
            question="Does GAIA support scheduling tweets?",
            answer="GAIA can post tweets immediately on your behalf. For scheduled posting, combine it with GAIA workflows: set a trigger time and GAIA will post at the specified time.",
        ),
    ],
)

GOOGLESHEETS_CONTENT = IntegrationContent(
    use_cases=[
        "Add rows to a Google Sheet by describing the data, and GAIA finds the right sheet and inserts it",
        "Query spreadsheet data with plain English, like 'what's the total revenue in column D for March?'",
        "Create new spreadsheets with pre-filled data from a short description",
        "Update or overwrite cell ranges without touching a formula",
        "Trigger workflows when new rows are added to a tracking sheet",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Google Sheets to GAIA",
            body='Open the GAIA Marketplace, find Google Sheets, and click "Add to your GAIA". Authorise via Google OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA to read or write your spreadsheets",
            body='Say "add a new lead to my CRM sheet with name John, email john@acme.com, source LinkedIn" or "what\'s the sum of column B in the sales tracker?". GAIA handles the rest.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps your sheets up to date automatically",
            body="Connect Sheets to other integrations: GAIA can log incoming emails, completed tasks, or new form submissions directly into a spreadsheet row, 24/7.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA add data to a specific sheet tab?",
            answer="Yes. When you name the sheet or describe its purpose, GAIA identifies the right spreadsheet and the correct tab, then inserts data in the appropriate columns.",
        ),
        IntegrationFAQ(
            question="Can GAIA read and summarise spreadsheet data?",
            answer="Yes. GAIA can read cell ranges, calculate totals, find max/min values, and summarise trends from your spreadsheet data in plain English.",
        ),
        IntegrationFAQ(
            question="Can GAIA create a new spreadsheet from scratch?",
            answer="Yes. Ask GAIA to create a spreadsheet with any structure you describe, and it will set up the headers, tabs, and initial data as instructed.",
        ),
        IntegrationFAQ(
            question="Does GAIA work with Google Sheets formulas?",
            answer="GAIA can read formula results and insert plain values. For complex formula authoring, describe the calculation you need and GAIA will insert the appropriate formula in the correct cell.",
        ),
    ],
)

LINKEDIN_CONTENT = IntegrationContent(
    use_cases=[
        "Post LinkedIn updates by describing your message, and GAIA writes and publishes in your voice",
        "Search for people, companies, or jobs on LinkedIn with plain English queries",
        "Draft personalised connection request messages for specific profiles",
        "Get a summary of a LinkedIn profile or company page without opening the app",
        "Research prospects before a sales call by pulling their LinkedIn context into chat",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect LinkedIn to GAIA",
            body='Open the GAIA Marketplace, find LinkedIn, and click "Add to your GAIA". Authorise via LinkedIn OAuth, which takes under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what to post or research",
            body='Say "post about a lesson I learned this week about leadership" or "look up the CTO of Acme Corp and summarise their background". GAIA handles the writing and the API calls.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA helps you build your professional presence",
            body="Set up content workflows: GAIA can draft and post weekly thought leadership updates, research your target accounts automatically, or alert you to job openings matching your criteria.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA post to LinkedIn on my behalf?",
            answer="Yes. GAIA can compose and publish LinkedIn posts directly from chat. It writes in your voice based on your description and posts immediately or holds for your review.",
        ),
        IntegrationFAQ(
            question="Can GAIA send LinkedIn connection requests?",
            answer="Yes. GAIA can send connection requests with personalised messages. Just tell it who to connect with and the context for the connection.",
        ),
        IntegrationFAQ(
            question="Can GAIA search LinkedIn for prospects?",
            answer="Yes. You can describe the type of person or company you're looking for and GAIA will search LinkedIn and return matching profiles with summaries.",
        ),
        IntegrationFAQ(
            question="Does GAIA access my LinkedIn messages?",
            answer="GAIA requests the scopes needed for posting and profile search. Direct messaging access depends on your LinkedIn permissions. Check the OAuth consent screen for the exact permissions granted.",
        ),
    ],
)

GITHUB_CONTENT = IntegrationContent(
    use_cases=[
        "Create issues, PRs, and branches by describing them, and GAIA handles all the GitHub API calls",
        "Get a daily summary of open pull requests, failing CI checks, and pending reviews",
        "Search code, commits, and issues across all your repositories with plain English",
        "Automate release notes from merged PRs with a single instruction",
        "Trigger GAIA workflows when a PR is opened, merged, or a CI check fails",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect GitHub to GAIA",
            body='Open the GAIA Marketplace, find GitHub, and click "Add to your GAIA". Authorise via GitHub OAuth and select which repositories GAIA should access.',
        ),
        IntegrationHowItWorksStep(
            title="Describe what you need in plain English",
            body='Say "create an issue in the backend repo for the login timeout bug" or "what PRs are waiting for my review?". GAIA knows your repos and handles the GitHub API.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps you on top of your codebase",
            body="Set up GitHub triggers: GAIA can notify you when CI fails on main, summarise weekly merge activity, or automatically draft release notes when you cut a new tag.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA access private repositories?",
            answer="Yes. During OAuth authorisation, you select which repositories (public and/or private) GAIA can access. You can update this from your GitHub settings at any time.",
        ),
        IntegrationFAQ(
            question="Can GAIA create pull requests?",
            answer="Yes. GAIA can create branches, push commits, and open pull requests. Just describe the change and the target repository.",
        ),
        IntegrationFAQ(
            question="Can GAIA read and summarise code?",
            answer="Yes. GAIA can read files, search for code patterns, and summarise what a function or module does, useful for onboarding, code reviews, or answering 'how does X work?'.",
        ),
        IntegrationFAQ(
            question="Does GAIA support GitHub Actions?",
            answer="GAIA can trigger workflow dispatches and monitor workflow run status. For full CI/CD visibility, you can set up triggers that alert you when GitHub Actions runs complete or fail.",
        ),
    ],
)

REDDIT_CONTENT = IntegrationContent(
    use_cases=[
        "Search Reddit for discussions, reviews, or opinions on any topic with plain English",
        "Monitor a subreddit for new posts matching your keywords and get alerted in chat",
        "Summarise the top posts and comments from any subreddit this week",
        "Draft and post Reddit submissions to relevant communities",
        "Research what real users say about a product or competitor by searching Reddit threads",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Reddit to GAIA",
            body='Open the GAIA Marketplace, find Reddit, and click "Add to your GAIA". Authorise via Reddit OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what to find or post",
            body='Say "what are people saying about Notion on r/productivity this week?" or "post this update to r/startups". GAIA searches, summarises, and posts on your behalf.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA monitors Reddit for you",
            body="Set up Reddit monitoring workflows: GAIA can alert you when your brand is mentioned, track competitor discussions, or surface the most upvoted posts in your niche daily.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA post to Reddit on my behalf?",
            answer="Yes. GAIA can submit text posts and links to any subreddit you have access to post in, directly from chat.",
        ),
        IntegrationFAQ(
            question="Can GAIA search specific subreddits?",
            answer="Yes. You can ask GAIA to search within a specific subreddit or across all of Reddit for posts, comments, or discussions matching your query.",
        ),
        IntegrationFAQ(
            question="Can GAIA summarise long Reddit threads?",
            answer="Yes. GAIA can fetch a thread and summarise the top comments, key opinions, and main points of discussion, saving you from reading hundreds of comments.",
        ),
        IntegrationFAQ(
            question="Can GAIA comment on Reddit posts?",
            answer="Yes. GAIA can post comments on existing threads. Describe the context and what you want to say, and GAIA will draft and post the reply.",
        ),
    ],
)

AIRTABLE_CONTENT = IntegrationContent(
    use_cases=[
        "Add records to any Airtable base by describing the data, and GAIA finds the right table and inserts it",
        "Query your Airtable bases with plain English: filter, sort, and summarise records",
        "Create new Airtable records from inputs in other tools (emails, forms, Slack messages)",
        "Update or patch existing records by describing what changed",
        "Get a daily summary of new records added to your CRM, project tracker, or content calendar",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Airtable to GAIA",
            body='Open the GAIA Marketplace, find Airtable, and click "Add to your GAIA". Authorise via Airtable OAuth and choose which bases GAIA should access.',
        ),
        IntegrationHowItWorksStep(
            title="Describe what you want to read or write",
            body='Say "add a new contact to my CRM base with name Sarah and company TechCorp" or "list all projects in the pipeline view that are overdue". GAIA handles the Airtable API.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps your Airtable bases in sync",
            body="Connect Airtable with other integrations: GAIA can automatically create records from incoming emails, completed tasks, or form submissions, keeping your bases always up to date.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA access all my Airtable bases?",
            answer="GAIA accesses the bases you authorise during OAuth setup. You can grant access to specific bases or your entire workspace.",
        ),
        IntegrationFAQ(
            question="Can GAIA filter and query Airtable records?",
            answer="Yes. You can ask GAIA to list records matching specific criteria, like 'show all contacts added this month with status Qualified,' and it will query Airtable and return the results.",
        ),
        IntegrationFAQ(
            question="Can GAIA update existing Airtable records?",
            answer="Yes. GAIA can find and patch existing records by ID or by matching criteria. Just describe what you want to change and it handles the update.",
        ),
        IntegrationFAQ(
            question="Does GAIA work with Airtable linked record fields?",
            answer="GAIA can read and create linked record relationships when you describe them. For complex relational structures, describe the relationship and GAIA will set up the link correctly.",
        ),
    ],
)

LINEAR_CONTENT = IntegrationContent(
    use_cases=[
        "Create Linear issues and assign them by just describing the bug or feature request",
        "Get a daily standup summary: open issues, blockers, and what's in progress on your team",
        "Move issues between cycles or change their status with a plain English command",
        "Search for issues by keyword, assignee, or label instantly from chat",
        "Trigger GAIA workflows when Linear issues are created, updated, or completed",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Linear to GAIA",
            body='Open the GAIA Marketplace, find Linear, and click "Add to your GAIA". Authorise via Linear OAuth, which takes under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Manage issues in plain English",
            body='Say "create a bug report for the login page timeout issue and assign it to high priority" or "what issues are blocking the current sprint?". GAIA handles your Linear workspace.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps your team in sync",
            body="Set up Linear triggers: GAIA can post to Slack when a high-priority issue is created, send a daily digest of cycle progress, or alert you when an issue is overdue.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA create issues in specific Linear teams?",
            answer="Yes. When you name the team or describe the project, GAIA creates the issue in the correct team and assigns it to the right cycle if one is active.",
        ),
        IntegrationFAQ(
            question="Can GAIA update issue status and priority?",
            answer="Yes. Ask GAIA to move an issue to In Progress, mark it as Done, or change its priority, and it will find the issue and update it instantly.",
        ),
        IntegrationFAQ(
            question="Can GAIA search across all my Linear projects?",
            answer="Yes. You can search for issues by title, description, label, assignee, or status across all teams and projects in your Linear workspace.",
        ),
        IntegrationFAQ(
            question="Does GAIA support Linear cycles and projects?",
            answer="Yes. GAIA can assign issues to cycles, query which issues are in the current cycle, and report on cycle progress, all from a plain English question.",
        ),
    ],
)

SLACK_CONTENT = IntegrationContent(
    use_cases=[
        "Send messages to any Slack channel or DM directly from GAIA chat",
        "Get a summary of what was discussed in a Slack channel while you were away",
        "Set up GAIA to post automated updates to Slack, like daily briefings or workflow results",
        "Search Slack for past conversations, decisions, or files with plain English",
        "Trigger GAIA workflows when specific messages are posted in a Slack channel",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Slack to GAIA",
            body='Open the GAIA Marketplace, find Slack, and click "Add to your GAIA". Authorise via Slack OAuth and select the workspace GAIA should access.',
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what to send or find",
            body='Say "post a message in #general saying the deployment is live" or "summarise what was discussed in #product this week". GAIA handles all Slack API calls.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA becomes your Slack automation layer",
            body="Connect Slack with other integrations: GAIA can post GitHub CI results, Airtable record updates, or calendar reminders directly to the right Slack channel, automatically.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA send messages to private Slack channels?",
            answer="Yes, as long as the GAIA Slack app has been added to that private channel. You'll need to invite the app to private channels you want it to post in.",
        ),
        IntegrationFAQ(
            question="Can GAIA send direct messages to teammates?",
            answer="Yes. GAIA can send DMs to any member of your Slack workspace. Just tell it who to message and what to say.",
        ),
        IntegrationFAQ(
            question="Can GAIA read and summarise Slack conversations?",
            answer="Yes. GAIA can read channel history and summarise discussions, decisions, or action items from any channel it has access to.",
        ),
        IntegrationFAQ(
            question="Can I use Slack messages as triggers for GAIA workflows?",
            answer="Yes. You can set up GAIA workflows that fire when specific messages are posted in a Slack channel, for example notifying you when someone posts in #on-call or #alerts.",
        ),
    ],
)

HUBSPOT_CONTENT = IntegrationContent(
    use_cases=[
        "Create contacts, companies, and deals in HubSpot by describing them in plain English",
        "Get a pipeline summary (open deals, stage distribution, and total value) without opening HubSpot",
        "Log calls, emails, and notes to CRM records with a quick chat message",
        "Search for contacts or deals by name, company, or deal stage instantly",
        "Trigger GAIA workflows when new leads come in or deal stages change",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect HubSpot to GAIA",
            body='Open the GAIA Marketplace, find HubSpot, and click "Add to your GAIA". Authorise via HubSpot OAuth, which takes under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Manage your CRM in plain English",
            body='Say "create a new deal for Acme Corp worth $15k, close date end of month" or "log a call with Sarah from TechCo: discussed pricing, follow up next week". GAIA handles the CRM.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps your pipeline moving",
            body="Set up HubSpot triggers: GAIA can alert you when a new lead is created, send a Slack notification when a deal moves to Closed Won, or generate weekly pipeline reports automatically.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA create contacts and companies in HubSpot?",
            answer="Yes. GAIA can create contacts, companies, and deals, and associate them with each other, from a plain English description.",
        ),
        IntegrationFAQ(
            question="Can GAIA log activity to HubSpot records?",
            answer="Yes. GAIA can log calls, emails, and notes to any contact, company, or deal record. Just describe what happened and GAIA attaches it to the right record.",
        ),
        IntegrationFAQ(
            question="Can GAIA search and update existing HubSpot records?",
            answer="Yes. GAIA can find records by name, email, or company and update properties, change deal stages, or add associations.",
        ),
        IntegrationFAQ(
            question="Does GAIA work with HubSpot custom properties?",
            answer="Yes. GAIA can read and write custom properties on contacts, companies, and deals. Describe the property name and value and GAIA will update it correctly.",
        ),
    ],
)

GOOGLETASKS_CONTENT = IntegrationContent(
    use_cases=[
        "Create tasks and to-dos by just describing what you need to do, and GAIA adds them instantly",
        "Get a list of all your due tasks for today or this week from a single question",
        "Mark tasks as complete without opening Google Tasks",
        "Organise tasks into lists by project or area of life",
        "Set up workflows that automatically create Google Tasks from emails or calendar events",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Google Tasks to GAIA",
            body='Open the GAIA Marketplace, find Google Tasks, and click "Add to your GAIA". Authorise via Google OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what tasks to create or complete",
            body='Say "add a task to review the Q4 report by Friday" or "what tasks do I have due today?". GAIA reads and writes to your Google Tasks lists.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps your task list up to date",
            body="Connect Google Tasks with Gmail or Calendar: GAIA can automatically create tasks from emails that need follow-up or from calendar events that have action items.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA access all my Google Task lists?",
            answer="Yes. GAIA can read and write to all task lists in your Google Tasks account, including the default My Tasks list and any custom lists you've created.",
        ),
        IntegrationFAQ(
            question="Can GAIA set due dates and notes on tasks?",
            answer="Yes. When creating a task, just include the due date and any notes in your description and GAIA will set them correctly.",
        ),
        IntegrationFAQ(
            question="Can GAIA mark tasks as completed?",
            answer="Yes. Ask GAIA to complete a task by describing it and it will find the matching task and mark it done.",
        ),
        IntegrationFAQ(
            question="How is Google Tasks different from GAIA's built-in Todos?",
            answer="GAIA's built-in Todos are stored in your GAIA account. Google Tasks syncs with your existing Google Tasks lists, useful if you already manage tasks in Gmail or Google Calendar.",
        ),
    ],
)

TODOIST_CONTENT = IntegrationContent(
    use_cases=[
        "Add tasks to Todoist by describing them, with due dates, priorities, and labels",
        "Get a daily briefing of your Todoist tasks due today delivered to your chat",
        "Complete, reschedule, or reprioritise tasks with a quick plain English message",
        "Search and filter tasks across all projects without opening Todoist",
        "Trigger GAIA workflows when high-priority tasks are overdue",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Todoist to GAIA",
            body='Open the GAIA Marketplace, find Todoist, and click "Add to your GAIA". Authorise via Todoist OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Manage your Todoist tasks in plain English",
            body='Say "add a P1 task to finish the landing page copy by tomorrow" or "what Todoist tasks are overdue?". GAIA handles creation, updates, and queries.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA automates your Todoist workflow",
            body="Connect Todoist with other integrations: GAIA can create tasks from incoming emails, add action items from meeting notes, or send you a Slack message when you hit your daily task goal.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA add tasks to specific Todoist projects?",
            answer="Yes. Name the project in your request and GAIA will add the task to the correct project. It can also create tasks in your Inbox if no project is specified.",
        ),
        IntegrationFAQ(
            question="Can GAIA set priorities and due dates on Todoist tasks?",
            answer="Yes. GAIA supports Todoist's P1 to P4 priority levels and full due date/time scheduling including recurring tasks.",
        ),
        IntegrationFAQ(
            question="Can GAIA complete tasks in Todoist?",
            answer="Yes. Ask GAIA to complete a task by name or description and it will mark it done in Todoist.",
        ),
        IntegrationFAQ(
            question="Can GAIA add labels and sections to tasks?",
            answer="Yes. GAIA can assign labels, sections, and assignees to Todoist tasks. Just describe what you want and it handles the details.",
        ),
    ],
)

MICROSOFT_TEAMS_CONTENT = IntegrationContent(
    use_cases=[
        "Send messages to any Teams channel or person directly from GAIA chat",
        "Get a summary of what was discussed in a Teams channel while you were away",
        "Post automated updates from other tools into Teams channels",
        "Search Teams conversations for past decisions, links, or files",
        "Trigger GAIA workflows when messages matching keywords are posted in Teams",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Microsoft Teams to GAIA",
            body='Open the GAIA Marketplace, find Microsoft Teams, and click "Add to your GAIA". Authorise via Microsoft OAuth, which takes under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what to send or find",
            body='Say "post a message in the Engineering channel saying the deployment is complete" or "summarise what was discussed in the Product channel today". GAIA handles the Teams API.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA becomes your Teams automation layer",
            body="Connect Teams with GitHub, Linear, or other tools: GAIA can automatically post PR notifications, issue updates, or daily briefings to the right Teams channel.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA send messages to private Teams channels?",
            answer="Yes, as long as the connected Microsoft account has access to the private channel. GAIA posts with the permissions of the authorised account.",
        ),
        IntegrationFAQ(
            question="Can GAIA send direct messages in Teams?",
            answer="Yes. GAIA can send direct messages to any member in your Microsoft Teams organisation.",
        ),
        IntegrationFAQ(
            question="Can GAIA read Teams message history?",
            answer="Yes. GAIA can read channel and chat history to summarise discussions or find specific messages, within the permissions of your Microsoft account.",
        ),
        IntegrationFAQ(
            question="Does GAIA support Teams meetings?",
            answer="For meeting scheduling and management, combine Microsoft Teams with your calendar integration. GAIA can create Teams meeting links when scheduling events.",
        ),
    ],
)

ZOOM_CONTENT = IntegrationContent(
    use_cases=[
        "Schedule Zoom meetings by describing the participants and time, and GAIA creates the invite",
        "Get a list of your upcoming Zoom meetings for today or this week",
        "Generate Zoom meeting links instantly and share them in chat",
        "Access meeting recordings and get a summary of what was discussed",
        "Trigger GAIA workflows when a meeting ends or a recording becomes available",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Zoom to GAIA",
            body='Open the GAIA Marketplace, find Zoom, and click "Add to your GAIA". Authorise via Zoom OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Schedule and manage meetings in plain English",
            body='Say "create a 30-minute Zoom meeting with the design team for tomorrow at 2 PM" or "what Zoom meetings do I have this week?". GAIA handles the scheduling.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps you on top of your Zoom activity",
            body="Set up Zoom triggers: GAIA can notify you when a recording is ready, send the meeting link to participants via Slack, or log meeting summaries to Notion automatically.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA create Zoom meetings with specific settings?",
            answer="Yes. GAIA can create meetings with your specified duration, topic, passcode, and waiting room settings. Just describe what you need.",
        ),
        IntegrationFAQ(
            question="Can GAIA retrieve Zoom meeting recordings?",
            answer="Yes. GAIA can list and access your cloud recordings and share the download or view links.",
        ),
        IntegrationFAQ(
            question="Can GAIA invite specific people to a Zoom meeting?",
            answer="Yes. When you name the attendees, GAIA creates the Zoom meeting and can send the invite via email or share the meeting link through connected integrations like Slack or Gmail.",
        ),
        IntegrationFAQ(
            question="Does GAIA support Zoom webinars?",
            answer="Yes. GAIA can create and manage Zoom webinars, including setting up registration, panellists, and scheduling, if your Zoom account includes webinar features.",
        ),
    ],
)

GOOGLEMEET_CONTENT = IntegrationContent(
    use_cases=[
        "Create Google Meet links instantly and share them in any chat or email",
        "Schedule meetings with automatic Google Meet links attached",
        "Get a list of upcoming meetings with their Meet links for quick access",
        "Start an instant meeting and get the link without opening Google Calendar",
        "Combine with Gmail to send meeting invitations with Meet links automatically",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Google Meet to GAIA",
            body='Open the GAIA Marketplace, find Google Meet, and click "Add to your GAIA". Authorise via Google OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA to create or find meeting links",
            body='Say "create a Google Meet link for a call this afternoon" or "what\'s the Meet link for my 3 PM meeting?". GAIA generates links and retrieves meeting details instantly.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA handles your video meeting logistics",
            body="Connect Google Meet with Gmail and Calendar: GAIA can schedule events with Meet links and send invitations to participants in one step, fully automated.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA create an instant Google Meet link?",
            answer="Yes. Ask GAIA for a Meet link and it will generate one immediately that you can share. No calendar event required.",
        ),
        IntegrationFAQ(
            question="Does GAIA automatically add Meet links to calendar events?",
            answer="Yes. When you ask GAIA to schedule a meeting and mention video call, it will attach a Google Meet link to the Calendar event.",
        ),
        IntegrationFAQ(
            question="Can GAIA get the Meet link for an existing calendar event?",
            answer="Yes. Ask GAIA for the Meet link for a specific meeting and it will find the event and return the link.",
        ),
        IntegrationFAQ(
            question="Is Google Meet separate from Google Calendar in GAIA?",
            answer="They work best together. Google Meet handles video link generation, while Google Calendar handles scheduling. Connect both for the full meeting management experience.",
        ),
    ],
)

GOOGLE_MAPS_CONTENT = IntegrationContent(
    use_cases=[
        "Search for nearby restaurants, cafes, or businesses with a plain English query",
        "Get directions between two locations and estimated travel times",
        "Find the best-rated places of a specific type within a given area",
        "Look up business details, including address, hours, phone, and reviews, instantly",
        "Combine with Calendar to get directions to your next meeting automatically",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Google Maps to GAIA",
            body='Open the GAIA Marketplace, find Google Maps, and click "Add to your GAIA". Authorise access. No complex setup required.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA location-based questions",
            body='Say "find the best sushi restaurants near my office" or "how long does it take to get from SoHo to JFK by car at 5 PM?". GAIA queries Google Maps and returns structured results.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA brings location context into your workflow",
            body="Combine Google Maps with Calendar: GAIA can proactively tell you when to leave for your next meeting based on current traffic conditions.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA search for businesses near a specific location?",
            answer="Yes. Describe the type of place and the area and GAIA will return a list of matching businesses with ratings, addresses, and opening hours.",
        ),
        IntegrationFAQ(
            question="Can GAIA give turn-by-turn directions?",
            answer="GAIA can provide step-by-step directions and estimated travel times by car, public transit, or walking. Just specify your origin and destination.",
        ),
        IntegrationFAQ(
            question="Can GAIA tell me current traffic conditions?",
            answer="Yes. GAIA can query real-time traffic data and factor it into travel time estimates when you ask for directions.",
        ),
        IntegrationFAQ(
            question="Does the Google Maps integration use my location?",
            answer="GAIA uses the location context you provide in your request. You can share your current location or specify any address. It does not require always-on location tracking.",
        ),
    ],
)

ASANA_CONTENT = IntegrationContent(
    use_cases=[
        "Create Asana tasks and assign them by just describing what needs to be done",
        "Get a daily summary of tasks due today and what's overdue across all your projects",
        "Update task status, due dates, and assignees with a plain English command",
        "Search for tasks across all your Asana projects by keyword or assignee",
        "Trigger GAIA workflows when tasks are completed or new ones are added to a project",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Asana to GAIA",
            body='Open the GAIA Marketplace, find Asana, and click "Add to your GAIA". Authorise via Asana OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Manage Asana tasks in plain English",
            body='Say "create a task in the Website Redesign project assigned to Marcus, due next Friday" or "what Asana tasks are blocking the current sprint?". GAIA handles your Asana workspace.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps your team's Asana up to date",
            body="Set up Asana triggers: GAIA can post to Slack when a milestone is completed, generate weekly project status reports, or create recurring tasks automatically.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA create tasks in specific Asana projects?",
            answer="Yes. Name the project in your request and GAIA will create the task in the correct project with all the details you specify.",
        ),
        IntegrationFAQ(
            question="Can GAIA assign tasks to teammates?",
            answer="Yes. GAIA can assign tasks to any member of your Asana workspace. Just include their name in your description.",
        ),
        IntegrationFAQ(
            question="Can GAIA update task status in Asana?",
            answer="Yes. GAIA can mark tasks as complete, change their status, update due dates, or move them between sections, all from a plain English command.",
        ),
        IntegrationFAQ(
            question="Does GAIA support Asana subtasks?",
            answer="Yes. GAIA can create subtasks under a parent task. Describe the task hierarchy and GAIA will set it up correctly in Asana.",
        ),
    ],
)

TRELLO_CONTENT = IntegrationContent(
    use_cases=[
        "Create Trello cards by describing them, and GAIA adds them to the right list and board",
        "Get a summary of what's in progress, blocked, or done across your Trello boards",
        "Move cards between lists with a plain English command, no drag and drop needed",
        "Add labels, due dates, and checklists to cards by describing what you want",
        "Trigger GAIA workflows when cards are moved to a specific list like Done or Blocked",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Trello to GAIA",
            body='Open the GAIA Marketplace, find Trello, and click "Add to your GAIA". Authorise via Trello OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Manage your Trello boards in plain English",
            body='Say "create a card in the Doing list of the Website board for the homepage redesign" or "move the API integration card to Done". GAIA handles all Trello operations.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA automates your Trello workflow",
            body="Set up Trello triggers: GAIA can notify your team on Slack when a card moves to Review, create cards from incoming emails, or generate a weekly board summary.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA create cards on specific Trello boards?",
            answer="Yes. Name the board and list in your request and GAIA will create the card in the right place with the description, labels, and due date you specify.",
        ),
        IntegrationFAQ(
            question="Can GAIA move cards between lists?",
            answer="Yes. Ask GAIA to move a card to a different list, like from In Progress to Review, and it will find the card and move it.",
        ),
        IntegrationFAQ(
            question="Can GAIA add checklists and attachments to cards?",
            answer="Yes. GAIA can add checklists with items, due dates, labels, and members to any Trello card.",
        ),
        IntegrationFAQ(
            question="Can GAIA search for specific Trello cards?",
            answer="Yes. Describe the card you're looking for and GAIA will search across your boards to find it.",
        ),
    ],
)

INSTAGRAM_CONTENT = IntegrationContent(
    use_cases=[
        "Search Instagram for posts, hashtags, or profiles with plain English queries",
        "Get engagement stats for recent posts without opening the Instagram app",
        "Research competitor accounts or trending content in your niche",
        "Monitor brand mentions and get alerted when your handle is tagged",
        "Find the top-performing posts in a specific hashtag for content inspiration",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Instagram to GAIA",
            body='Open the GAIA Marketplace, find Instagram, and click "Add to your GAIA". Authorise via Instagram OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA about Instagram activity",
            body='Say "what are the top posts for #productdesign this week?" or "show me the engagement stats for my last 5 posts". GAIA queries Instagram and returns structured results.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA monitors Instagram for you",
            body="Set up Instagram monitoring: GAIA can alert you when you're mentioned, track hashtag trends in your industry, or summarise your account's weekly performance.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA post to Instagram on my behalf?",
            answer="GAIA can interact with Instagram via the available API capabilities. Posting to personal Instagram accounts has API limitations. GAIA works best for research, monitoring, and business account interactions.",
        ),
        IntegrationFAQ(
            question="Can GAIA search Instagram hashtags?",
            answer="Yes. GAIA can search for posts by hashtag and return top results with engagement metrics.",
        ),
        IntegrationFAQ(
            question="Can GAIA get my Instagram account analytics?",
            answer="Yes. GAIA can retrieve post-level metrics like likes, comments, reach, and impressions for your connected Instagram business account.",
        ),
        IntegrationFAQ(
            question="Does GAIA require an Instagram Business account?",
            answer="For full access to analytics and posting features, an Instagram Business or Creator account is recommended. Personal accounts have more limited API access.",
        ),
    ],
)

CLICKUP_CONTENT = IntegrationContent(
    use_cases=[
        "Create ClickUp tasks across any Space, Folder, or List by describing them",
        "Get a daily overview of what's due, in progress, and overdue across your ClickUp workspace",
        "Update task status, priority, and assignees with a quick plain English message",
        "Search tasks across all your ClickUp Spaces by keyword, tag, or assignee",
        "Trigger GAIA workflows when ClickUp tasks reach a specific status",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect ClickUp to GAIA",
            body='Open the GAIA Marketplace, find ClickUp, and click "Add to your GAIA". Authorise via ClickUp OAuth in under two minutes.',
        ),
        IntegrationHowItWorksStep(
            title="Manage ClickUp tasks in plain English",
            body='Say "create an urgent task in the Marketing sprint for the email campaign copy, due Thursday" or "what\'s in review in the Engineering space?". GAIA handles your full ClickUp workspace.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps your ClickUp workspace in sync",
            body="Connect ClickUp with Slack, Gmail, or Linear: GAIA can create tasks from emails, post status updates to Slack, or sync issues across tools automatically.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA create tasks in specific ClickUp Spaces and Lists?",
            answer="Yes. Name the Space, Folder, or List in your request and GAIA will create the task in the correct location.",
        ),
        IntegrationFAQ(
            question="Can GAIA update ClickUp task status?",
            answer="Yes. GAIA can update task status to any custom status in your workflow. Just tell it what the task is and what status to set.",
        ),
        IntegrationFAQ(
            question="Does GAIA support ClickUp custom fields?",
            answer="Yes. GAIA can read and write ClickUp custom fields. Describe the field and value you want to set and GAIA will update it correctly.",
        ),
        IntegrationFAQ(
            question="Can GAIA set time estimates in ClickUp?",
            answer="Yes. Include a time estimate in your task description and GAIA will set it in ClickUp's time tracking field.",
        ),
    ],
)

DEEPWIKI_CONTENT = IntegrationContent(
    use_cases=[
        "Ask deep technical questions about any GitHub repository and get expert answers",
        "Understand how a codebase is structured before diving into it",
        "Get documentation and usage examples for any open-source library instantly",
        "Research how popular projects have solved specific engineering problems",
        "Ask 'how does authentication work in this repo?' and get a clear explanation",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect DeepWiki to GAIA",
            body='Open the GAIA Marketplace, find DeepWiki, and click "Add to your GAIA". DeepWiki uses an MCP server connection. No OAuth required.',
        ),
        IntegrationHowItWorksStep(
            title="Ask technical questions about any GitHub repo",
            body='Say "explain how the auth system works in vercel/next.js" or "what\'s the architecture of the redis/redis codebase?". GAIA queries DeepWiki\'s deep code intelligence.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA becomes your codebase research assistant",
            body="Combine DeepWiki with your development workflow: ask GAIA to research how a library handles edge cases before you integrate it, or understand a dependency's internals before debugging.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Which GitHub repositories does DeepWiki support?",
            answer="DeepWiki covers a large index of popular open-source GitHub repositories. If a repo isn't indexed, DeepWiki may not have detailed information on it.",
        ),
        IntegrationFAQ(
            question="Does DeepWiki require authentication?",
            answer="No. DeepWiki is available without an API key or OAuth flow. It connects directly as an MCP server.",
        ),
        IntegrationFAQ(
            question="Can DeepWiki answer questions about private repositories?",
            answer="DeepWiki primarily indexes public GitHub repositories. Private repository support depends on DeepWiki's indexing capabilities and your access.",
        ),
        IntegrationFAQ(
            question="How is DeepWiki different from reading GitHub directly?",
            answer="DeepWiki builds a deep semantic understanding of the entire codebase (relationships, patterns, and architecture), going beyond simple file browsing to give you expert-level explanations.",
        ),
    ],
)

HACKERNEWS_CONTENT = IntegrationContent(
    use_cases=[
        "Get a daily summary of the top Hacker News posts without opening the site",
        "Search HN for discussions about a specific technology or company",
        "Find the most upvoted posts and comments on any topic in the last week",
        "Monitor Hacker News for mentions of your product or brand",
        "Stay current on tech industry news and trends through your GAIA chat",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Hacker News to GAIA",
            body='Open the GAIA Marketplace, find Hacker News, and click "Add to your GAIA". No OAuth required. Connects instantly via MCP.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA what's happening on HN",
            body='Say "what are the top Hacker News stories today?" or "find HN discussions about Rust vs Go". GAIA fetches and summarises HN content for you.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA keeps you up to date with tech news",
            body="Set up a daily HN digest: GAIA can deliver the top 10 stories every morning, filtered by topics you care about, directly to your chat.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Does GAIA need a Hacker News account?",
            answer="No. The Hacker News integration reads public HN content. No account or authentication required.",
        ),
        IntegrationFAQ(
            question="Can GAIA post to Hacker News?",
            answer="The current integration focuses on reading and searching HN content. Posting requires direct HN account access.",
        ),
        IntegrationFAQ(
            question="Can GAIA search HN comments as well as posts?",
            answer="Yes. GAIA can search both top-level posts and comments on Hacker News to find relevant discussions on any topic.",
        ),
        IntegrationFAQ(
            question="How current is the Hacker News data?",
            answer="GAIA fetches live data from the Hacker News API, so stories and comments are current at the time you ask.",
        ),
    ],
)

INSTACART_CONTENT = IntegrationContent(
    use_cases=[
        "Add items to your Instacart cart by listing what you need in plain English",
        "Search for grocery products and find the best options from local stores",
        "Build a shopping list from a meal plan or recipe and send it to Instacart",
        "Check availability and prices for specific products in your area",
        "Automate your weekly grocery order with a recurring GAIA workflow",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Instacart to GAIA",
            body='Open the GAIA Marketplace, find Instacart, and click "Add to your GAIA". Connects via MCP. No complex OAuth setup required.',
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what groceries you need",
            body='Say "I need ingredients for a pasta carbonara for four people" or "add almond milk, eggs, and sourdough bread to my cart". GAIA handles the search and cart management.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA handles your grocery shopping automatically",
            body="Set up recurring shopping lists: GAIA can automatically populate your Instacart cart every Sunday with your weekly staples, ready for you to confirm and checkout.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA add items directly to my Instacart cart?",
            answer="Yes. GAIA can search for products and add them to your Instacart cart. You review and checkout from the Instacart app.",
        ),
        IntegrationFAQ(
            question="Can GAIA suggest grocery lists from a meal plan?",
            answer="Yes. Give GAIA a list of meals you plan to cook and it will generate a shopping list and add the ingredients to Instacart.",
        ),
        IntegrationFAQ(
            question="Does GAIA know which stores are available in my area?",
            answer="GAIA queries Instacart's product availability based on your location settings in Instacart. Local store inventory is pulled in real time.",
        ),
        IntegrationFAQ(
            question="Can GAIA check prices on Instacart?",
            answer="Yes. Ask GAIA to find the best price for a specific item and it will search available stores and return price comparisons.",
        ),
    ],
)

YELP_CONTENT = IntegrationContent(
    use_cases=[
        "Find top-rated restaurants, bars, or services near any location instantly",
        "Get business details, including hours, address, phone, and reviews, with a single question",
        "Search for businesses by cuisine, category, or specific requirements like pet-friendly",
        "Compare multiple options with ratings, price range, and review summaries",
        "Plan a dinner, event, or errand by finding exactly the right places in your area",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Yelp to GAIA",
            body='Open the GAIA Marketplace, find Yelp, and click "Add to your GAIA". Connects via MCP. No OAuth required.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA to find local businesses",
            body='Say "find the best ramen restaurants in Brooklyn" or "is there a 24-hour pharmacy near Times Square?". GAIA queries Yelp and returns structured results.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA becomes your local discovery assistant",
            body="Combine Yelp with Google Maps: GAIA can find the best restaurant near your next meeting location and add directions to your calendar event, all in one step.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA search Yelp for any type of business?",
            answer="Yes. Yelp covers restaurants, bars, services, shops, healthcare, and more. Describe what you're looking for and GAIA will search the relevant Yelp categories.",
        ),
        IntegrationFAQ(
            question="Can GAIA show Yelp reviews for a business?",
            answer="Yes. GAIA can retrieve review summaries, ratings, and recent feedback for any business on Yelp.",
        ),
        IntegrationFAQ(
            question="Does the Yelp integration require an account?",
            answer="No. The Yelp integration connects via MCP and reads public Yelp data. No Yelp account or authentication is required.",
        ),
        IntegrationFAQ(
            question="Can GAIA filter Yelp results by price or distance?",
            answer="Yes. You can specify filters like price range ($ to $$$$), distance, open now, and amenities in your request.",
        ),
    ],
)

CONTEXT7_CONTENT = IntegrationContent(
    use_cases=[
        "Get up-to-date documentation for any library or framework directly in your chat",
        "Ask 'how do I use useQuery in React Query v5?' and get the current API with examples",
        "Avoid outdated AI answers by pulling live docs for rapidly changing libraries",
        "Get code examples for specific library features without leaving your workflow",
        "Research how to integrate two libraries together using their latest documentation",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Context7 to GAIA",
            body='Open the GAIA Marketplace, find Context7, and click "Add to your GAIA". Context7 connects via MCP with a Smithery API key.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA about any library's documentation",
            body='Say "show me the latest Next.js App Router documentation for middleware" or "how do I configure Tailwind v4?". GAIA fetches the current docs from Context7 and answers precisely.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA always uses the latest docs",
            body="With Context7 connected, GAIA automatically pulls current library documentation when answering coding questions, no more answers based on outdated training data.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Which libraries does Context7 support?",
            answer="Context7 indexes documentation for hundreds of popular libraries and frameworks including Next.js, React, Tailwind, Prisma, LangChain, and many more.",
        ),
        IntegrationFAQ(
            question="Does Context7 require an API key?",
            answer="Yes. Context7 connects via the Smithery MCP platform and requires an API key. Enter it when prompted during the GAIA connection setup.",
        ),
        IntegrationFAQ(
            question="How is Context7 different from searching the web?",
            answer="Context7 surfaces structured, version-specific documentation rather than generic web results, giving GAIA precise, current API references and usage examples for the exact version you're using.",
        ),
        IntegrationFAQ(
            question="Does Context7 work for private or internal documentation?",
            answer="Context7 currently indexes public library documentation. For internal docs, you'd need a different solution.",
        ),
    ],
)

PERPLEXITY_CONTENT = IntegrationContent(
    use_cases=[
        "Get real-time web search results with cited sources directly in your GAIA chat",
        "Research any topic and get a concise, sourced summary without leaving your workflow",
        "Ask current events questions that require up-to-date information",
        "Fact-check claims or verify information with live web sources",
        "Combine web research with other tools: research a company on the web, then create a CRM record",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Perplexity to GAIA",
            body='Open the GAIA Marketplace, find Perplexity, and click "Add to your GAIA". Connects via MCP with a Smithery API key.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA anything that requires current web information",
            body='Say "what\'s the latest news about OpenAI?" or "research the top 3 competitors to Notion and summarise their pricing". GAIA uses Perplexity to fetch live, cited answers.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA combines web research with action",
            body="After researching, GAIA can immediately act on what it finds: log findings to Notion, send a Slack summary, or create a task based on research results.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Does Perplexity require an API key?",
            answer="Yes. The Perplexity integration connects via the Smithery MCP platform and requires an API key. Enter it during the GAIA connection setup.",
        ),
        IntegrationFAQ(
            question="How is Perplexity different from GAIA's built-in knowledge?",
            answer="GAIA's built-in knowledge has a training cutoff. Perplexity provides real-time web search with citations, essential for current events, recent releases, and up-to-date facts.",
        ),
        IntegrationFAQ(
            question="Does Perplexity return sources and citations?",
            answer="Yes. Perplexity includes citations with each answer so you can verify information and read the original sources.",
        ),
        IntegrationFAQ(
            question="Can I use Perplexity for deep research tasks?",
            answer="Yes. GAIA can chain multiple Perplexity searches to do multi-step research, then synthesise the findings into a report or take automated actions based on the results.",
        ),
    ],
)

AGENTMAIL_CONTENT = IntegrationContent(
    use_cases=[
        "Give GAIA its own email inbox to send and receive emails on your behalf",
        "Set up GAIA as an email agent that handles inbound requests automatically",
        "Send emails from a dedicated GAIA address without using your personal Gmail",
        "Build automated email workflows where GAIA receives, processes, and responds to emails",
        "Use email as a trigger source for GAIA automations",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect AgentMail to GAIA",
            body='Open the GAIA Marketplace, find AgentMail, and click "Add to your GAIA". AgentMail connects via MCP and provides GAIA with a dedicated email address.',
        ),
        IntegrationHowItWorksStep(
            title="Use GAIA's email capabilities",
            body="GAIA can send emails from its AgentMail inbox, receive and process inbound emails, and act as a full email agent, replying, forwarding, and routing messages automatically.",
        ),
        IntegrationHowItWorksStep(
            title="GAIA becomes an autonomous email agent",
            body="Set up email handling workflows: GAIA can monitor its AgentMail inbox, classify incoming emails, trigger actions based on content, and respond autonomously to routine requests.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="What is AgentMail?",
            answer="AgentMail provides AI agents with dedicated email addresses and inboxes, making it possible for GAIA to send, receive, and process email independently of your personal email account.",
        ),
        IntegrationFAQ(
            question="Does AgentMail require an API key?",
            answer="Yes. AgentMail connects via MCP and requires an API key. Enter it when prompted during the GAIA connection setup.",
        ),
        IntegrationFAQ(
            question="How is AgentMail different from connecting Gmail?",
            answer="Gmail connects your personal inbox to GAIA. AgentMail gives GAIA its own dedicated inbox, useful for separating agent email activity from your personal account.",
        ),
        IntegrationFAQ(
            question="Can GAIA automatically reply to emails via AgentMail?",
            answer="Yes. GAIA can monitor its AgentMail inbox and send automated replies based on rules or content, making it suitable for handling inbound support, lead qualification, or routine requests.",
        ),
    ],
)

POSTHOG_CONTENT = IntegrationContent(
    use_cases=[
        "Query your PostHog analytics data with plain English, like 'how many users signed up this week?'",
        "Get conversion funnel analysis and drop-off points from a single question",
        "Set up GAIA to deliver daily or weekly product analytics briefings to Slack",
        "Investigate user behaviour around a specific feature without writing HogQL",
        "Trigger GAIA alerts when key metrics like DAU or conversion rate drop below a threshold",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect PostHog to GAIA",
            body='Open the GAIA Marketplace, find PostHog, and click "Add to your GAIA". PostHog connects via MCP. Authenticate with your PostHog credentials.',
        ),
        IntegrationHowItWorksStep(
            title="Ask GAIA about your product analytics",
            body='Say "what\'s the sign-up to activation conversion rate for users who joined this month?" or "which features have the most usage in the last 7 days?". GAIA queries your PostHog data.',
        ),
        IntegrationHowItWorksStep(
            title="GAIA surfaces product insights proactively",
            body="Set up analytics workflows: GAIA can send a weekly product metrics summary to Slack, alert you when a key event count drops, or help you investigate anomalies in user behaviour.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Does PostHog require special authentication?",
            answer="Yes. PostHog connects via MCP and requires your PostHog project API key and host URL. These are entered during the GAIA connection setup.",
        ),
        IntegrationFAQ(
            question="Can GAIA query PostHog without writing HogQL?",
            answer="Yes. GAIA translates your plain English questions into PostHog queries. You don't need to write HogQL or know the PostHog query API.",
        ),
        IntegrationFAQ(
            question="Can GAIA access feature flags and experiments in PostHog?",
            answer="Yes. GAIA can query feature flag status, experiment results, and A/B test performance from your PostHog project.",
        ),
        IntegrationFAQ(
            question="Is PostHog analytics data sent to GAIA's servers?",
            answer="GAIA queries your PostHog data on demand to answer your questions. It does not continuously sync or store your analytics data beyond what's needed to respond.",
        ),
    ],
)

CALCOM_CONTENT = IntegrationContent(
    use_cases=[
        "See every upcoming Cal.com booking with attendees and meeting links in one message",
        "Book a meeting on any of your event types by saying who and roughly when, and GAIA finds an open slot",
        "Reschedule or cancel a booking in plain English without opening Cal.com",
        "Get the right booking link for the right meeting type whenever you need to share one",
        "Run a scheduled workflow that briefs you every morning on the day's Cal.com bookings",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Cal.com to GAIA",
            body='Open the GAIA Marketplace, find Cal.com, and click "Add to your GAIA". Authorise via Cal.com OAuth.',
        ),
        IntegrationHowItWorksStep(
            title="Manage bookings in plain English",
            body='Say "what\'s booked on my Cal.com tomorrow?" or "move my 3pm intro call with Sam to Thursday". GAIA checks availability before it books or reschedules anything.',
        ),
        IntegrationHowItWorksStep(
            title="Confirm before anyone is notified",
            body="Cancelling or declining a booking emails your attendee, so GAIA asks for your approval before it does either.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA book meetings on my Cal.com event types?",
            answer="Yes. GAIA lists your event types, checks the available slots, and creates the booking with the attendee's name, email and timezone once you confirm the time.",
        ),
        IntegrationFAQ(
            question="Will GAIA cancel bookings without asking?",
            answer="No. Cancelling and declining are gated behind an approval card because they notify your attendee and can't be undone.",
        ),
        IntegrationFAQ(
            question="Does it work with self-hosted Cal.com?",
            answer="The integration connects to Cal.com's hosted API through OAuth. Self-hosted instances are not supported through this integration.",
        ),
        IntegrationFAQ(
            question="Can GAIA reschedule an existing booking?",
            answer="Yes. GAIA looks up the booking, finds a free slot that works, and reschedules it, optionally with a reason for the attendee.",
        ),
    ],
)

CALENDLY_CONTENT = IntegrationContent(
    use_cases=[
        "Ask what's on your Calendly this week and see each meeting with its invitees",
        "Generate a single-use scheduling link for one person in seconds",
        "Check which times are still open on an event type before you share it",
        "Cancel a scheduled Calendly meeting with a reason, after you approve it",
        "Get a daily briefing of new Calendly bookings through a scheduled workflow",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Calendly to GAIA",
            body='Open the GAIA Marketplace, find Calendly, and click "Add to your GAIA". Authorise via Calendly OAuth.',
        ),
        IntegrationHowItWorksStep(
            title="Ask about your schedule",
            body='Say "who booked time with me this week?" or "send me a one-time link for my 30 minute call". GAIA reads your event types and scheduled events directly.',
        ),
        IntegrationHowItWorksStep(
            title="Share links without leaving the chat",
            body="GAIA creates scheduling links you can paste into email, Slack or WhatsApp, and can draft the message around them.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA create one-time Calendly links?",
            answer="Yes. GAIA can create a single-use scheduling link for any of your event types, so the link stops working after one booking.",
        ),
        IntegrationFAQ(
            question="Can GAIA cancel Calendly meetings?",
            answer="Yes, after you approve it. Cancelling notifies invitees, so it always goes through an approval card first.",
        ),
        IntegrationFAQ(
            question="Can GAIA see who booked a meeting?",
            answer="Yes. GAIA can list the invitees of any scheduled event, including their names, emails and answers to your booking questions.",
        ),
        IntegrationFAQ(
            question="Can I choose which Calendly permissions GAIA gets?",
            answer="Calendly's OAuth does not offer individual scopes, so the connection grants access to your scheduling data as a whole.",
        ),
    ],
)

OUTLOOK_CONTENT = IntegrationContent(
    use_cases=[
        "Summarise your unread Outlook mail and draft replies for the ones that need an answer",
        "Search your Outlook inbox in plain English: 'the invoice Priya sent last month'",
        "Find a meeting time that works for everyone and send the invite with a Teams link",
        "Get today's Outlook calendar as a morning briefing in your chat",
        "Draft emails in your voice and send them only after you approve",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Outlook to GAIA",
            body='Open the GAIA Marketplace, find Outlook, and click "Add to your GAIA". Sign in with your Microsoft account. Some work accounts need an admin to approve the app first.',
        ),
        IntegrationHowItWorksStep(
            title="Manage mail and calendar in plain English",
            body='Say "what needs a reply in my inbox?" or "book 30 minutes with Alex and Dana next week". GAIA reads, drafts, and schedules across your mailbox and calendar.',
        ),
        IntegrationHowItWorksStep(
            title="You approve anything that goes out",
            body="Sending, replying, forwarding and cancelling meetings are gated behind an approval card, so nothing reaches another person without your yes.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Does GAIA send emails from Outlook automatically?",
            answer="No. GAIA prepares drafts, and sending, replying or forwarding always requires your approval first.",
        ),
        IntegrationFAQ(
            question="Does it work with work or school Microsoft accounts?",
            answer="Yes, with personal and work accounts. Some organisations require an administrator to approve the app before you can connect it.",
        ),
        IntegrationFAQ(
            question="Can GAIA schedule Outlook meetings with a Teams link?",
            answer="Yes. GAIA can find a time that suits all attendees and create the event as an online meeting so a Teams link is included.",
        ),
        IntegrationFAQ(
            question="Will GAIA permanently delete my email?",
            answer="Deleting moves mail to Deleted Items, where you can recover it. Permanent deletion is gated and only used when you explicitly ask for it.",
        ),
    ],
)

JIRA_CONTENT = IntegrationContent(
    use_cases=[
        "See every Jira issue assigned to you, ranked by priority, in one message",
        "Create Jira issues by describing the bug or task, and GAIA fills in the project and type",
        "Move issues through your workflow with a plain English command",
        "Turn meeting notes into Jira issues with owners and descriptions",
        "Get a weekly summary of what your team moved to Done through a scheduled workflow",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Jira to GAIA",
            body='Open the GAIA Marketplace, find Jira, and click "Add to your GAIA". Authorise via Atlassian OAuth and pick your Jira site.',
        ),
        IntegrationHowItWorksStep(
            title="Work your backlog in plain English",
            body='Say "what\'s assigned to me that\'s still open?" or "create a bug in MOB for the login crash on Android". GAIA writes the JQL and the issue for you.',
        ),
        IntegrationHowItWorksStep(
            title="Updates stay in your workflow",
            body="GAIA moves issues through your team's real transitions, comments on them, and reassigns them. Deletions always ask for approval first.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Do I need to know JQL?",
            answer="No. Describe what you're looking for and GAIA builds the JQL query for you.",
        ),
        IntegrationFAQ(
            question="Can GAIA change an issue's status?",
            answer="Yes. GAIA looks up the transitions your workflow allows for that issue and applies the right one.",
        ),
        IntegrationFAQ(
            question="Will GAIA delete issues without asking?",
            answer="No. Deleting issues, comments, attachments or worklogs always requires your approval.",
        ),
        IntegrationFAQ(
            question="Does it work with Jira Cloud?",
            answer="Yes. The integration connects to Jira Cloud sites through Atlassian OAuth.",
        ),
    ],
)

DROPBOX_CONTENT = IntegrationContent(
    use_cases=[
        "Find any file in your Dropbox by describing it, no folder digging",
        "Summarise a document stored in Dropbox without downloading it yourself",
        "Organise files into folders with a single instruction",
        "Create a share link for a file, after you approve exposing it",
        "Save files GAIA generates (reports, decks, spreadsheets) straight into Dropbox",
    ],
    how_it_works=[
        IntegrationHowItWorksStep(
            title="Connect Dropbox to GAIA",
            body='Open the GAIA Marketplace, find Dropbox, and click "Add to your GAIA". Authorise via Dropbox OAuth.',
        ),
        IntegrationHowItWorksStep(
            title="Search and read files in plain English",
            body='Say "find the signed contract from Acme" or "summarise the Q3 report in my Finance folder". GAIA searches and reads the file for you.',
        ),
        IntegrationHowItWorksStep(
            title="Sharing always asks first",
            body="Creating share links or adding people to a folder exposes its contents, so GAIA shows an approval card before doing either.",
        ),
    ],
    faqs=[
        IntegrationFAQ(
            question="Can GAIA read the contents of my Dropbox files?",
            answer="Yes. GAIA can read files on demand to summarise them or use them in another task, like attaching them to an email.",
        ),
        IntegrationFAQ(
            question="Will GAIA share my files without asking?",
            answer="No. Share links, folder sharing and adding members are gated behind your approval.",
        ),
        IntegrationFAQ(
            question="What happens if GAIA deletes a file?",
            answer="Dropbox keeps deleted files recoverable, and GAIA can restore a file to an earlier version if you ask.",
        ),
        IntegrationFAQ(
            question="Does GAIA copy my Dropbox to its servers?",
            answer="No. GAIA fetches files only when a request needs them and does not sync or store your Dropbox.",
        ),
    ],
)
