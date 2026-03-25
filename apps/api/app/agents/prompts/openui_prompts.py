"""OpenUI Lang component library prompt for the comms agent.

This prompt section teaches the LLM to output OpenUI Lang syntax
for presenting structured tool results as rich UI components.
The frontend Renderer parses these blocks and maps them to React components.

Regenerate from the frontend library:
  npx @openuidev/cli generate src/config/openui/gaiaLibrary.ts \
    --out src/config/openui/generated-prompt.txt
"""

OPENUI_COMPONENT_LIBRARY_PROMPT = """
Available Components:

1. WeatherCard(coord, weather, main, wind, dt, sys, timezone, name, location, ...)
   - Displays current weather with temperature, forecast, and details.
   - coord: {lon: number, lat: number}
   - weather: [{id: number, main: string, description: string, icon: string}]
   - main: {temp: number, feels_like: number, temp_min: number, temp_max: number, pressure: number, humidity: number}
   - visibility: number (optional)
   - wind: {speed: number, deg: number, gust?: number}
   - dt: number (unix timestamp)
   - sys: {country: string, sunrise: number, sunset: number}
   - timezone: number (offset in seconds)
   - name: string (city name)
   - location: {city: string, country: string|null, region: string|null}
   - forecast: [{date: string, timestamp: number, temp_min: number, temp_max: number, humidity: number, weather: {main: string, description: string, icon: string}}] (optional)

2. CalendarListCard(events)
   - Displays a list of calendar events.
   - events: [{summary: string, start_time: string, end_time: string, calendar_name: string, background_color: string}]

3. SearchResultsTabs(web?, images?, news?, answer?, query?)
   - Displays search results in tabs: web, images, and news.
   - web: [{title: string, url: string, content: string, score: number, favicon?: string}] (optional)
   - images: [string] (optional, array of image URLs)
   - news: [{title: string, url: string, content: string, score: number, favicon?: string}] (optional)
   - answer: string (optional, direct answer)
   - query: string (optional, search query)

4. EmailListCard(emails)
   - Displays a list of emails with sender, subject, and time.
   - emails: [{id: string, from: string, subject: string, time: string, thread_id?: string (optional)}]
   - Pass the emails array from email_fetch_data tool result.

5. EmailThreadCard(thread_id, messages, messages_count)
   - Displays a full email thread with all messages expanded in an accordion.
   - thread_id: string
   - messages: [{id: string, from: string, subject: string, time: string, snippet: string, body: string, content?: {text: string, html: string} (optional)}]
   - messages_count: number
   - Pass the thread object directly (not wrapped in a "thread" key) from email_thread_data tool result.

6. ContactListCard(contacts)
   - Displays a list of contacts with name, email, and phone number.
   - contacts: [{name: string, email: string, resource_name: string, phone?: string (optional)}]
   - Pass the contacts array from contacts_data tool result.

7. PeopleSearchCard(people)
   - Displays people search results with name, email, and phone number.
   - people: [{name: string, email: string, resource_name: string, phone?: string (optional)}]
   - Pass the people array from people_search_data tool result.

8. TodoListCard(todos?, projects?, stats?, action?, message?)
   - Displays todos, projects, and task statistics in an interactive card.
   - todos: [{id: string, title: string, completed: boolean, priority: string, labels: [string], created_at: string, updated_at: string, description?: string (optional), due_date?: string (optional), project_id?: string (optional), project?: {id, name, ...} (optional), subtasks: [{id: string, title: string, completed: boolean}], workflow?: any (optional)}] (optional)
   - projects: [{id: string, name: string, description?: string (optional), color?: string (optional), is_default?: boolean (optional), todo_count?: number (optional), completion_percentage?: number (optional)}] (optional)
   - stats: {total: number, completed: number, pending: number, overdue: number, today: number, upcoming: number} (optional)
   - action: string (optional)
   - message: string (optional)
   - Pass all fields from todo_data tool result.

9. GoalCard(goals?, stats?, action?, message?, goal_id?, deleted_goal_id?, error?)
   - Displays goals with progress, roadmap nodes, and statistics.
   - goals: [{id: string, title: string, description?: string (optional), progress?: number (optional), roadmap?: {nodes: [...], edges: [...]} (optional), created_at?: string (optional), todo_project_id?: string (optional), todo_id?: string (optional)}] (optional)
   - stats: {total_goals: number, goals_with_roadmaps: number, total_tasks: number, completed_tasks: number, overall_completion_rate: number, active_goals: [{id, title, progress}], active_goals_count: number} (optional)
   - action: string (optional)
   - message: string (optional)
   - goal_id: string (optional)
   - deleted_goal_id: string (optional)
   - error: string (optional)
   - Pass all fields from goal_data tool result.

10. NotificationCard(notifications, title?)
    - Displays a list of notifications with type, status, and actions.
    - notifications: [{id: string, user_id: string, status: string, type: string, created_at: string, source: string, content: {title: string, body: string, actions?: any (optional), rich_content?: any (optional)}, channels: [{channel_type: string, status: string, delivered_at?: string (optional), error_message?: string (optional), retry_count?: number (optional)}], delivered_at?: string (optional), read_at?: string (optional), metadata?: object (optional)}]
    - title: string (optional)
    - Pass the notifications array and optional title from notification_data tool result.

11. IntegrationListCard(suggestedIntegrations?)
    - Displays available and suggested integrations with connect actions.
    - suggestedIntegrations: [{id: string, name: string, description: string, category: string, relevanceScore: number, slug: string, iconUrl?: string (optional), authType?: string (optional)}] (optional)
    - Pass the suggestedIntegrations array from integration_list_data tool result.

12. DocumentCard(document_data)
    - Displays a document card with file info and a download button.
    - document_data: {filename: string, url: string, is_plain_text: boolean, title: string, metadata: object}
    - Pass the document_data object from document_data tool result.

13. GoogleDocsCard(google_docs_data)
    - Displays a Google Docs document with title, action, and a link to open it.
    - google_docs_data: {document: {id: string, title: string, url: string, created_time: string, modified_time: string, type: string}, query?: string|null (optional), action: string, message: string, type: string}
    - Pass the google_docs_data object from google_docs_data tool result.

14. DeepResearchCard(deep_research_results)
    - Displays deep research results with enhanced web results, original search, and metadata tabs.
    - deep_research_results: {original_search?: {web?, images?, news?, answer?, query?} (optional), enhanced_results?: [{title: string, url: string, content: string, score: number, raw_content?: string (optional), favicon?: string (optional), full_content?: string (optional), screenshot_url?: string (optional)}] (optional), screenshots_taken?: boolean (optional), metadata?: {total_content_size?: number (optional), elapsed_time?: number (optional), query?: string (optional)} (optional)}
    - Pass the deep_research_results object from deep_research_results tool result.

15. CalendarListFetchCard(calendars)
    - Displays a list of fetched calendars with names, descriptions, and color indicators.
    - calendars: [{name: string, id: string, description: string, backgroundColor?: string (optional)}]
    - Pass the calendars array from calendar_list_fetch_data tool result.

16. TwitterSearchCard(twitter_search_data)
    - Displays Twitter search results as tweet cards with author info and engagement metrics.
    - twitter_search_data: {tweets: [{id: string, text: string, author: {id: string, username: string, name: string, description?: string (optional), profile_image_url?: string (optional), verified?: boolean (optional), public_metrics?: object (optional), created_at?: string (optional), location?: string (optional), url?: string (optional)}, created_at?: string (optional), public_metrics?: {retweet_count?, reply_count?, like_count?, quote_count?, bookmark_count?, impression_count?} (optional), conversation_id?: string (optional)}], result_count?: number (optional), next_token?: string (optional)}
    - Pass the twitter_search_data object from twitter_search_data tool result.
"""

OPENUI_INSTRUCTIONS = """
---OpenUI Lang (Rich UI Components)---

When presenting data from tool results, use OpenUI Lang syntax wrapped in :::openui fences.

{component_library}

Syntax rules:
- Wrap ALL OpenUI output in :::openui and ::: fences
- root = ComponentName(arg1=value1, arg2=value2) is the entry point
- Use Stack([item1, item2]) to compose multiple components
- Plain text before/after the fences is rendered as normal markdown
- Use OpenUI for: weather data, calendar events, search results, email lists, email threads, contacts, people search, todos, goals, notifications, integrations list, documents, Google Docs, deep research, calendar list, Twitter search
- Use markdown for: conversational replies, explanations, write-action confirmations, anything not in the above list
- Pass the complete data object from tool results — do not omit fields
- Do NOT use OpenUI for greetings, opinions, or conversational text
""".format(component_library=OPENUI_COMPONENT_LIBRARY_PROMPT)
