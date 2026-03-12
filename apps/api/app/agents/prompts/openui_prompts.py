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
- ONLY use OpenUI for: weather data, calendar events, search results
- Use markdown for: conversational replies, explanations, lists, code
- Pass the complete data object from tool results — do not omit fields
- Do NOT use OpenUI for greetings, opinions, or conversational text
""".format(component_library=OPENUI_COMPONENT_LIBRARY_PROMPT)
