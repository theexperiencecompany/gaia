import type { PromptOptions } from "@openuidev/react-lang";

export const gaiaPromptOptions: PromptOptions = {
  preamble:
    "You can render rich UI components inline in your responses using OpenUI Lang syntax. Use these ONLY for presenting structured data from tool results — never for conversational text.",
  additionalRules: [
    "Wrap ALL OpenUI output in :::openui and ::: fences.",
    "root = ComponentName(...) is the entry point for each block.",
    "Use plain markdown for conversational replies, explanations, and lists.",
    "ONLY use OpenUI for: weather data, calendar events, search results.",
    "Do NOT use OpenUI for: greetings, opinions, advice, emotional support, or any conversational response.",
    "Pass the complete data object from tool results — do not omit or summarize fields.",
    "You may include markdown text before and after OpenUI blocks.",
  ],
  examples: [
    `User: "What's the weather in San Francisco?"
After receiving weather tool results, respond with:

checking the weather rn

:::openui
root = WeatherCard(coord={"lon": -122.42, "lat": 37.77}, weather=[{"id": 800, "main": "Clear", "description": "clear sky", "icon": "01d"}], main={"temp": 18, "feels_like": 17, "temp_min": 15, "temp_max": 21, "pressure": 1013, "humidity": 65}, wind={"speed": 3.5, "deg": 270}, dt=1710000000, sys={"country": "US", "sunrise": 1709980000, "sunset": 1710020000}, timezone=-28800, name="San Francisco", location={"city": "San Francisco", "country": "US", "region": "CA"})
:::

pretty nice out today ngl`,
  ],
};
