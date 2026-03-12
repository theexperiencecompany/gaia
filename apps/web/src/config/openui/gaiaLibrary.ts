import type { Library } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import type { CalendarFetchData } from "@/types/features/calendarTypes";
import type { SearchResults } from "@/types/features/searchTypes";
import type { WeatherData } from "@/types/features/weatherTypes";

// We build the Library object manually instead of using defineComponent/createLibrary
// because those functions call `schema.register(z.globalRegistry)` which requires
// zod v4. The project uses zod@3.25 (v3 compat bridge) whose default import lacks
// globalRegistry. The Renderer only needs `library.components[name].component` and
// `library.components[name].props.shape` — both work with zod 3.25 schemas.

// --- Zod Schemas ---

const weatherConditionSchema = z.object({
  id: z.number(),
  main: z.string(),
  description: z.string(),
  icon: z.string(),
});

const forecastDaySchema = z.object({
  date: z.string(),
  timestamp: z.number(),
  temp_min: z.number(),
  temp_max: z.number(),
  humidity: z.number(),
  weather: z.object({
    main: z.string(),
    description: z.string(),
    icon: z.string(),
  }),
});

const weatherDataSchema = z.object({
  coord: z.object({ lon: z.number(), lat: z.number() }),
  weather: z.array(weatherConditionSchema),
  base: z.string().optional(),
  main: z.object({
    temp: z.number(),
    feels_like: z.number(),
    temp_min: z.number(),
    temp_max: z.number(),
    pressure: z.number(),
    humidity: z.number(),
    sea_level: z.number().optional(),
    grnd_level: z.number().optional(),
  }),
  visibility: z.number().optional(),
  wind: z.object({
    speed: z.number(),
    deg: z.number(),
    gust: z.number().optional(),
  }),
  clouds: z.object({ all: z.number() }).optional(),
  dt: z.number(),
  sys: z.object({
    country: z.string(),
    sunrise: z.number(),
    sunset: z.number(),
  }),
  timezone: z.number(),
  id: z.number().optional(),
  name: z.string(),
  cod: z.number().optional(),
  location: z.object({
    city: z.string(),
    country: z.string().nullable(),
    region: z.string().nullable(),
  }),
  forecast: z.array(forecastDaySchema).optional(),
});

const calendarEventSchema = z.object({
  summary: z.string(),
  start_time: z.string(),
  end_time: z.string(),
  calendar_name: z.string(),
  background_color: z.string(),
});

const calendarListSchema = z.object({
  events: z.array(calendarEventSchema),
});

const webResultSchema = z.object({
  title: z.string(),
  url: z.string(),
  content: z.string(),
  score: z.number(),
  raw_content: z.string().optional(),
  favicon: z.string().optional(),
});

const newsResultSchema = z.object({
  title: z.string(),
  url: z.string(),
  content: z.string(),
  score: z.number(),
  raw_content: z.string().optional(),
  favicon: z.string().optional(),
});

const searchResultsSchema = z.object({
  web: z.array(webResultSchema).optional(),
  images: z.array(z.string()).optional(),
  news: z.array(newsResultSchema).optional(),
  answer: z.string().optional(),
  query: z.string().optional(),
  response_time: z.number().optional(),
  request_id: z.string().optional(),
});

// --- Component Definitions ---

const components = {
  WeatherCard: {
    name: "WeatherCard",
    props: weatherDataSchema,
    description:
      "Displays current weather conditions with temperature, forecast, and details for a location.",
    component: ({
      props,
    }: {
      props: Record<string, unknown>;
      renderNode: unknown;
    }) => {
      return React.createElement(WeatherCard, {
        weatherData: props as unknown as WeatherData,
      });
    },
  },
  CalendarListCard: {
    name: "CalendarListCard",
    props: calendarListSchema,
    description:
      "Displays a list of calendar events with times, names, and calendar colors.",
    component: ({
      props,
    }: {
      props: Record<string, unknown>;
      renderNode: unknown;
    }) => {
      const { events } = props as unknown as { events: CalendarFetchData[] };
      return React.createElement(CalendarListCard, { events });
    },
  },
  SearchResultsTabs: {
    name: "SearchResultsTabs",
    props: searchResultsSchema,
    description:
      "Displays search results in tabs: web results, image gallery, and news articles.",
    component: ({
      props,
    }: {
      props: Record<string, unknown>;
      renderNode: unknown;
    }) => {
      return React.createElement(SearchResultsTabs, {
        search_results: props as unknown as SearchResults,
      });
    },
  },
};

// --- Library (manually constructed to avoid zod v4 globalRegistry dependency) ---

export const gaiaLibrary: Library = {
  components: components as unknown as Library["components"],
  componentGroups: [
    {
      name: "Data Display",
      components: ["WeatherCard", "CalendarListCard", "SearchResultsTabs"],
      notes: [
        "Use these components to present tool results visually.",
        "Always pass the full data object from the tool result.",
      ],
    },
  ],
  root: undefined,
  prompt() {
    // We maintain the backend prompt manually in openui_prompts.py
    // since the auto-generation requires zod v4 globalRegistry.
    return "";
  },
  toJSONSchema() {
    return {};
  },
};
