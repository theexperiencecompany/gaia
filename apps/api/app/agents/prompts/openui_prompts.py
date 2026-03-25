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
   - Displays a list of email previews (subject, sender, snippet, date).
   - emails: [{id: string, subject?: string, from?: string, snippet?: string, date?: string, is_read?: boolean}]
   - Pass the full emails array from email_fetch_data tool result.

5. EmailThreadCard(thread)
   - Displays a full email thread with all messages.
   - thread: {thread_id: string, messages: [{id: string, subject?: string, from?: string, to?: string[], body?: string, date?: string}]}
   - Pass the thread object from email_thread_data tool result.

6. ContactListCard(contacts)
   - Displays a list of contacts with name, email, and photo.
   - contacts: [{name?: string, email?: string, photo?: string, job_title?: string, company?: string}]
   - Pass the contacts array from contacts_data tool result.

7. PeopleSearchCard(people)
   - Displays people search results with profile details.
   - people: [{name?: string, email?: string, photo?: string, job_title?: string, company?: string}]
   - Pass the people array from people_search_data tool result.

8. TodoListCard(todos?, projects?, stats?, action?, message?)
   - Displays todo items, projects, and task statistics.
   - todos: [{id: string, content: string, is_completed?: boolean, priority?: number, due_date?: string, project_id?: string}] (optional)
   - projects: [{id: string, name: string, color?: string}] (optional)
   - stats: {total?: number, completed?: number, overdue?: number} (optional)
   - action: string (optional, the action that was performed)
   - message: string (optional, status message)
   - Pass all fields from todo_data tool result.

9. GoalCard(goals?, stats?, action?, message?, goal_id?, deleted_goal_id?, error?)
   - Displays goal tracking data with progress statistics.
   - goals: [{id: string, title: string, description?: string, status?: string, progress?: number}] (optional)
   - stats: {total?: number, completed?: number, in_progress?: number} (optional)
   - action: string (optional)
   - message: string (optional)
   - goal_id: string (optional)
   - deleted_goal_id: string (optional)
   - error: string (optional)
   - Pass all fields from goal_data tool result.

10. NotificationCard(notifications)
    - Displays a list of notifications.
    - notifications: [{id?: string, title?: string, body?: string, type?: string, timestamp?: string, is_read?: boolean}]
    - Pass the notifications array from notification_data.notifications field.

11. IntegrationListCard(suggested?)
    - Displays available integrations the user can connect.
    - suggested: [{id: string, name?: string, description?: string, icon?: string, category?: string}] (optional)
    - Pass the suggested array from integration_list_data tool result.

12. DocumentCard(document_data)
    - Displays a document with title, content, and metadata.
    - document_data: {title?: string, content?: string, url?: string, type?: string, created_at?: string}
    - Pass the document_data object from document_data tool result.

13. GoogleDocsCard(google_docs_data)
    - Displays a Google Doc with title, content preview, and link.
    - google_docs_data: {title?: string, content?: string, url?: string, doc_id?: string, last_modified?: string}
    - Pass the google_docs_data object from google_docs_data tool result.

14. DeepResearchCard(deep_research_results)
    - Displays comprehensive deep research results with sources.
    - deep_research_results: {query?: string, answer?: string, sources?: [{title: string, url: string, content?: string}], images?: [string]}
    - Pass the deep_research_results object from deep_research_results tool result.

15. CalendarListFetchCard(calendars)
    - Displays a list of Google Calendar calendars with names and colors.
    - calendars: [{calendar_id?: string, name?: string, color?: string, is_primary?: boolean}]
    - Pass the calendars array from calendar_list_fetch_data tool result.

16. TwitterSearchCard(twitter_search_data)
    - Displays Twitter/X search results with tweets and metadata.
    - twitter_search_data: {tweets: [{id: string, text: string, author?: string, created_at?: string, likes?: number, retweets?: number}], result_count?: number}
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
