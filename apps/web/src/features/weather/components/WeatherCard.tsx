import { Accordion, AccordionItem } from "@heroui/accordion";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import type { WeatherData } from "@/types/features/convoTypes";
import { WeatherDetailsGrid } from "./WeatherDetailsGrid";
import { WeatherForecastList } from "./WeatherForecastList";
import { WeatherHeader } from "./WeatherHeader";
import { WeatherMainDisplay } from "./WeatherMainDisplay";
import { getWeatherTheme } from "./weatherTheme";
import { celsiusToFahrenheit, formatTime } from "./weatherUtils";

interface WeatherCardProps {
  weatherData: WeatherData;
}

export const WeatherCard: React.FC<WeatherCardProps> = ({ weatherData }) => {
  const [useFahrenheit, setUseFahrenheit] = useState(false);
  const forecastCount = weatherData.forecast?.length ?? 0;

  useEffect(() => {
    trackEvent(ANALYTICS_EVENTS.WEATHER_QUERIED, {
      has_forecast: forecastCount > 0,
    });
  }, [forecastCount]);

  const weatherTheme = useMemo(
    () => getWeatherTheme(weatherData),
    [weatherData],
  );

  if (!weatherTheme) {
    return <div>Loading weather...</div>;
  }

  const displayTemp = useFahrenheit
    ? Math.round(celsiusToFahrenheit(weatherData.main?.temp ?? 0))
    : Math.round(weatherData.main?.temp ?? 0);
  const displayFeelsLike = useFahrenheit
    ? Math.round(celsiusToFahrenheit(weatherData.main?.feels_like ?? 0))
    : Math.round(weatherData.main?.feels_like ?? 0);
  const sunriseTime = weatherData.sys?.sunrise
    ? formatTime(weatherData.sys.sunrise, weatherData.timezone)
    : "N/A";
  const sunsetTime = weatherData.sys?.sunset
    ? formatTime(weatherData.sys.sunset, weatherData.timezone)
    : "N/A";

  return (
    <div
      className={`w-full rounded-3xl sm:w-screen sm:max-w-md ${weatherTheme.gradient} relative overflow-hidden p-6 shadow-lg backdrop-blur-xs`}
    >
      <WeatherHeader
        weatherData={weatherData}
        colorCode={weatherTheme.colorCode}
        useFahrenheit={useFahrenheit}
        onToggleUnit={setUseFahrenheit}
      />

      <WeatherMainDisplay
        weatherData={weatherData}
        icon={weatherTheme.icon}
        displayTemp={displayTemp}
        displayFeelsLike={displayFeelsLike}
        useFahrenheit={useFahrenheit}
        colorCode={weatherTheme.colorCode}
      />

      <Accordion
        className="mt-2"
        isCompact
        selectionMode="multiple"
        itemClasses={{ indicator: "text-white", trigger: "cursor-pointer" }}
        defaultExpandedKeys={["weekly-forecast"]}
      >
        {weatherData.forecast && weatherData.forecast.length > 0 ? (
          <AccordionItem
            key="weekly-forecast"
            aria-label="Weekly Forecast"
            title={
              <div className="flex items-center">
                <span className="text-sm font-normal text-white">
                  Weekly Forecast
                </span>
              </div>
            }
          >
            <WeatherForecastList
              forecast={weatherData.forecast}
              useFahrenheit={useFahrenheit}
              colorCode={weatherTheme.colorCode}
            />
          </AccordionItem>
        ) : null}

        <AccordionItem
          key="weather-details"
          aria-label="Weather Details"
          title={
            <div className="flex items-center">
              <span className="text-sm font-normal text-white">
                Additional Information
              </span>
            </div>
          }
        >
          <WeatherDetailsGrid
            weatherData={weatherData}
            colorCode={weatherTheme.colorCode}
            sunriseTime={sunriseTime}
            sunsetTime={sunsetTime}
          />
        </AccordionItem>
      </Accordion>
    </div>
  );
};
