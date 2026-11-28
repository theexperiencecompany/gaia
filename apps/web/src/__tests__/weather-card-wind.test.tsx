// @vitest-environment jsdom
/** The wind tile shows a speed, or is left out when the report has no wind; never "undefined m/s". */
import type { WeatherReport } from "@shared/api/generated";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WeatherCard } from "@/features/weather/components/WeatherCard";

const REPORT: WeatherReport = {
  clouds: null,
  cod: 200,
  coord: null,
  dt: 1_700_000_000,
  forecast: [],
  id: 1,
  location: { city: "Mumbai", country: "IN", region: null },
  main: { temp: 30, feels_like: 32, humidity: 70 },
  name: "Mumbai",
  sys: { sunrise: 1_699_990_000, sunset: 1_700_030_000 },
  timezone: 19_800,
  visibility: null,
  weather: [{ id: 800, main: "Clear", description: "clear sky", icon: "01d" }],
  wind: { speed: 4.1 },
};

describe("WeatherCard wind tile", () => {
  it("shows the wind speed the report carries", () => {
    render(<WeatherCard weatherData={REPORT} />);
    expect(screen.getByText("4.1 m/s")).toBeTruthy();
  });

  it("leaves the tile out when the report has no wind", () => {
    render(<WeatherCard weatherData={{ ...REPORT, wind: null }} />);
    expect(screen.queryByText("Wind")).toBeNull();
    expect(screen.queryByText(/undefined/)).toBeNull();
  });
});
