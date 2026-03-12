import { createLibrary, defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import type { CalendarFetchData } from "@/types/features/calendarTypes";
import type { SearchResults } from "@/types/features/searchTypes";
import type { WeatherData } from "@/types/features/weatherTypes";

// Note: `as never` casts on `props` are needed because the project uses zod@3.25
// (v3 compat bridge for v4) while @openuidev/react-lang bundles zod@4.
// The runtime schemas are fully compatible; only the type signatures differ.
// TODO: Remove `as never` casts once zod versions are aligned.

// --- Weather ---

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

const WeatherCardComponent = defineComponent({
  name: "WeatherCard",
  props: weatherDataSchema as never,
  description:
    "Displays current weather conditions with temperature, forecast, and details for a location.",
  component: ({ props }) => {
    const data = props as unknown as WeatherData;
    return React.createElement(WeatherCard, { weatherData: data });
  },
});

// --- Calendar Events ---

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

const CalendarListCardComponent = defineComponent({
  name: "CalendarListCard",
  props: calendarListSchema as never,
  description:
    "Displays a list of calendar events with times, names, and calendar colors.",
  component: ({ props }) => {
    const { events } = props as unknown as { events: CalendarFetchData[] };
    return React.createElement(CalendarListCard, { events });
  },
});

// --- Search Results ---

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

const SearchResultsTabsComponent = defineComponent({
  name: "SearchResultsTabs",
  props: searchResultsSchema as never,
  description:
    "Displays search results in tabs: web results, image gallery, and news articles.",
  component: ({ props }) => {
    const data = props as unknown as SearchResults;
    return React.createElement(SearchResultsTabs, { search_results: data });
  },
});

// --- Library ---

export const gaiaLibrary = createLibrary({
  components: [
    WeatherCardComponent,
    CalendarListCardComponent,
    SearchResultsTabsComponent,
  ],
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
  root: "Stack",
});
