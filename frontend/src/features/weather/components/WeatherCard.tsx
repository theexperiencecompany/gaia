import { Accordion, AccordionItem } from "@heroui/accordion";
import { Switch } from "@heroui/switch";
import React, { useMemo, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/shadcn/dropdown-menu";
import {
  CloudAngledRainIcon,
  CloudAngledZapIcon,
  CloudFogIcon,
  CloudIcon,
  CloudLittleRainIcon,
  CloudSnowIcon,
  DropletIcon,
  FastWindIcon,
  Moon02Icon,
  PinIcon,
  Sun03Icon,
  SunriseIcon,
  SunsetIcon,
  ThermometerWarmIcon,
  Tornado02Icon,
  VisionIcon,
} from "@/icons";
import { WeatherData } from "@/types/features/convoTypes";

import { WeatherDetailItem } from "./WeatherDetailItem";

interface WeatherCardProps {
  weatherData: WeatherData;
}

// Helper function to convert timestamp to readable time, taking into account timezone
const formatTime = (timestamp: number, timezone: number): string => {
  const date = new Date((timestamp + timezone) * 1000);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

// Helper function to convert celsius to fahrenheit
const celsiusToFahrenheit = (celsius: number): number => {
  return (celsius * 9) / 5 + 32;
};

// Helper function to get day of week from date string
const getDayOfWeek = (dateStr: string): string => {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { weekday: "long" });
};

// Helper function to get weather icon component based on weather condition
const getWeatherIcon = (main: string, className: string = "", fill = "") => {
  switch (main.toLowerCase()) {
    case "thunderstorm":
      return <CloudAngledZapIcon className={className} color={fill} />;
    case "drizzle":
      return <CloudLittleRainIcon className={className} color={fill} />;
    case "rain":
      return <CloudAngledRainIcon className={className} color={fill} />;
    case "snow":
      return <CloudSnowIcon className={className} color={fill} />;
    case "haze":
      return <CloudIcon className={className} color={fill} />;
    case "mist":
    case "smoke":
    case "dust":
    case "sand":
    case "ash":
    case "squall":
      return <CloudFogIcon className={className} color={fill} />;
    case "fog":
      return <CloudIcon className={className} color={fill} />;
    case "tornado":
      return <Tornado02Icon className={className} color={fill} />;
    case "clear":
      return <Sun03Icon className={className} fill={fill} color={fill} />;
    case "clouds":
      return <CloudIcon className={className} color={"#E5E7EB"} />;
    default:
      return <CloudIcon className={className} color={"#E5E7EB"} />;
  }
};

export const WeatherCard: React.FC<WeatherCardProps> = ({ weatherData }) => {
  const [useFahrenheit, setUseFahrenheit] = useState(false);

  const temp = weatherData.main.temp;
  const feelsLike = weatherData.main.feels_like;
  const weatherId = weatherData.weather[0].id;
  const sunriseTime = formatTime(weatherData.sys.sunrise, weatherData.timezone);
  const sunsetTime = formatTime(weatherData.sys.sunset, weatherData.timezone);

  // Convert temperature based on selected unit
  const displayTemp = useFahrenheit
    ? Math.round(celsiusToFahrenheit(temp))
    : Math.round(temp);

  const displayFeelsLike = useFahrenheit
    ? Math.round(celsiusToFahrenheit(feelsLike))
    : Math.round(feelsLike);

  // Determine the weather theme based on weather conditions
  const weatherTheme = useMemo(() => {
    // weather condition codes: https://openweathermap.org/weather-conditions
    if (weatherId >= 200 && weatherId < 300) {
      return {
        name: "Thunderstorm",
        icon: (
          <CloudAngledZapIcon
            className="h-16 w-16"
            fill="#FCD34D"
            color="#FCD34D"
          />
        ),
        gradient: "bg-linear-to-br from-slate-800/80 to-purple-900/80",
        colorCode: "#FCD34D", // yellow-300
      };
    } else if (weatherId >= 300 && weatherId < 400) {
      return {
        name: "Drizzle",
        icon: (
          <CloudLittleRainIcon
            className="h-16 w-16"
            fill="#93C5FD"
            color="#93C5FD"
          />
        ),
        gradient: "bg-linear-to-br from-slate-700/80 to-blue-800/80",
        colorCode: "#93C5FD", // blue-300
      };
    } else if (weatherId >= 500 && weatherId < 600) {
      return {
        name: "Rain",
        icon: (
          <CloudAngledRainIcon
            className="h-16 w-16"
            fill="#60A5FA"
            color="#60A5FA"
          />
        ),
        gradient: "bg-linear-to-br from-slate-800/80 to-blue-900/80",
        colorCode: "#60A5FA", // blue-400
      };
    } else if (weatherId >= 600 && weatherId < 700) {
      return {
        name: "Snow",
        icon: (
          <CloudSnowIcon className="h-16 w-16" fill="#E0F2FE" color="#E0F2FE" />
        ),
        gradient: "bg-linear-to-br from-blue-100/80 to-indigo-300/80",
        colorCode: "#E0F2FE", // blue-100
      };
    } else if (weatherId >= 700 && weatherId < 800) {
      // More specific handling for atmospheric conditions
      if (weatherId === 701) {
        // Mist
        return {
          name: "Mist",
          icon: (
            <CloudFogIcon
              className="h-16 w-16"
              fill="#D1D5DB"
              color="#D1D5DB"
            />
          ),
          gradient: "bg-linear-to-br from-slate-400/80 to-slate-500/80",
          colorCode: "#D1D5DB", // gray-300
        };
      } else if (weatherId === 711) {
        // Smoke
        return {
          name: "Smoke",
          icon: (
            <CloudFogIcon
              className="h-16 w-16"
              fill="#9CA3AF"
              color="#9CA3AF"
            />
          ),
          gradient: "bg-linear-to-br from-gray-500/80 to-gray-700/80",
          colorCode: "#9CA3AF", // gray-400
        };
      } else if (weatherId === 721) {
        // Haze
        return {
          name: "Haze",
          icon: (
            <CloudIcon className="h-16 w-16" fill="#FDE68A" color="#FDE68A" />
          ),
          gradient: "bg-linear-to-br from-amber-300/80 to-amber-500/80",
          colorCode: "#FDE68A", // amber-200
        };
      } else if (weatherId === 731 || weatherId === 761) {
        // Dust/Sand
        return {
          name: "Dust",
          icon: (
            <CloudFogIcon
              className="h-16 w-16"
              fill="#FEF08A"
              color="#FEF08A"
            />
          ),
          gradient: "bg-linear-to-br from-yellow-400/80 to-yellow-600/80",
          colorCode: "#FEF08A", // yellow-200
        };
      } else if (weatherId === 741) {
        // Fog
        return {
          name: "Fog",
          icon: (
            <CloudIcon className="h-16 w-16" fill="#D1D5DB" color="#D1D5DB" />
          ),
          gradient: "bg-linear-to-br from-gray-400/80 to-gray-600/80",
          colorCode: "#D1D5DB", // gray-300
        };
      } else if (weatherId === 751) {
        // Sand
        return {
          name: "Sand",
          icon: (
            <CloudFogIcon
              className="h-16 w-16"
              fill="#FDBA74"
              color="#FDBA74"
            />
          ),
          gradient: "bg-linear-to-br from-orange-300/80 to-orange-500/80",
          colorCode: "#FDBA74", // orange-300
        };
      } else if (weatherId === 762) {
        // Volcanic Ash
        return {
          name: "Volcanic Ash",
          icon: (
            <CloudFogIcon
              className="h-16 w-16"
              fill="#D4D4D8"
              color="#D4D4D8"
            />
          ),
          gradient: "bg-linear-to-br from-zinc-600/80 to-zinc-800/80",
          colorCode: "#D4D4D8", // zinc-300
        };
      } else if (weatherId === 771) {
        // Squall
        return {
          name: "Squall",
          icon: (
            <FastWindIcon
              className="h-16 w-16"
              fill="#93C5FD"
              color="#93C5FD"
            />
          ),
          gradient: "bg-linear-to-br from-blue-500/80 to-blue-700/80",
          colorCode: "#93C5FD", // blue-300
        };
      } else if (weatherId === 781) {
        // Tornado
        return {
          name: "Tornado",
          icon: (
            <Tornado02Icon
              className="h-16 w-16"
              fill="#CBD5E1"
              color="#CBD5E1"
            />
          ),
          gradient: "bg-linear-to-br from-slate-600/80 to-slate-900/80",
          colorCode: "#CBD5E1", // slate-300
        };
      } else {
        return {
          name: "Atmosphere",
          icon: (
            <CloudFogIcon
              className="h-16 w-16"
              fill="#D1D5DB"
              color="#D1D5DB"
            />
          ),
          gradient: "bg-linear-to-br from-slate-400/80 to-slate-600/80",
          colorCode: "#D1D5DB", // gray-300
        };
      }
    } else if (weatherId === 800) {
      return {
        name: "Clear",
        icon: (
          <Sun03Icon className="h-16 w-16" fill="#FBBF24" color="#FBBF24" />
        ),
        gradient: "bg-linear-to-br from-yellow-500/80 to-orange-500/80",
        colorCode: "#FBBF24", // yellow-400
      };
    } else if (weatherId >= 801 && weatherId <= 802) {
      // Few/Scattered clouds
      return {
        name: "Partly Cloudy",
        icon: (
          <CloudIcon className="h-16 w-16" fill="#E5E7EB" color="#E5E7EB" />
        ),
        gradient: "bg-linear-to-br from-blue-400/80 to-blue-600/80",
        colorCode: "#E5E7EB", // gray-200
      };
    } else if (weatherId >= 803 && weatherId <= 804) {
      // Broken/Overcast clouds
      return {
        name: "Cloudy",
        icon: (
          <CloudIcon className="h-16 w-16" fill="#E5E7EB" color="#E5E7EB" />
        ),
        gradient: "bg-linear-to-br from-slate-500/80 to-slate-700/80",
        colorCode: "#E5E7EB", // gray-200
      };
    } else {
      return {
        name: "Unknown",
        icon: (
          <CloudIcon className="h-16 w-16" fill="#E5E7EB" color="#E5E7EB" />
        ),
        gradient: "bg-linear-to-br from-slate-500/80 to-slate-700/80",
        colorCode: "#E5E7EB", // gray-200
      };
    }
  }, [weatherId]);

  return (
    <div
      className={`w-full rounded-3xl sm:w-screen sm:max-w-md ${weatherTheme.gradient} relative overflow-hidden p-6 shadow-lg backdrop-blur-xs`}
    >
      {/* Location Info */}
      <div className="mb-3 flex items-start justify-between gap-10">
        <div className="flex items-start">
          <PinIcon className="relative top-1 mr-2 h-5 w-5" color={"white"} />
          <div>
            <h2 className="flex items-center text-xl font-bold text-white">
              {weatherData.location.city}
              {weatherData.location.region
                ? `,${weatherData.location.region}`
                : ""}
            </h2>
            <p className="text-xs" style={{ color: weatherTheme.colorCode }}>
              {weatherData.location.country}
            </p>
          </div>
        </div>

        <div className="flex items-center">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 p-1 text-white hover:bg-white/20"
                aria-label="Temperature settings"
              >
                <ThermometerWarmIcon className="h-5 w-5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-40 border-zinc-700 bg-zinc-800 text-white"
            >
              <DropdownMenuLabel>Temperature Unit</DropdownMenuLabel>
              <DropdownMenuSeparator className="bg-zinc-700" />
              <div className="px-2 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm">°F</span>
                  <Switch
                    checked={useFahrenheit}
                    onValueChange={setUseFahrenheit}
                    color="default"
                  />
                  <span className="text-sm">°C</span>
                </div>
              </div>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Main weather Display */}
      <div className="mb-2 flex items-center justify-between gap-5">
        <div className="flex items-center justify-center">
          {weatherTheme.icon}
        </div>

        <div>
          <div className="flex items-baseline">
            <span className="text-4xl font-bold text-white">
              {displayTemp}°
            </span>
            <span className="ml-1 text-sm font-medium text-white/80">
              {useFahrenheit ? "F" : "C"}
            </span>
          </div>
          <p
            className="text-xs"
            style={{
              color: weatherTheme.colorCode,
              filter: "brightness(1.3)",
            }}
          >
            Feels like: {displayFeelsLike}°
          </p>
        </div>

        <p className="font-medium text-white capitalize">
          {weatherData.weather[0].description}
        </p>
      </div>

      {/* weather Details Accordion */}
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
            <div className="space-y-2 pb-2">
              {weatherData.forecast.map((day, idx) => {
                const dayTemp = useFahrenheit
                  ? Math.round(celsiusToFahrenheit(day.temp_max))
                  : Math.round(day.temp_max);
                const nightTemp = useFahrenheit
                  ? Math.round(celsiusToFahrenheit(day.temp_min))
                  : Math.round(day.temp_min);

                return (
                  <div
                    key={idx}
                    className="flex items-center justify-start rounded-2xl bg-black/10 px-2 py-1 text-white"
                  >
                    <div className="flex w-full flex-1 items-center justify-start gap-2">
                      <div className="flex items-center justify-center">
                        {getWeatherIcon(
                          day.weather.main,
                          "h-7 w-7",
                          weatherTheme.colorCode,
                        )}
                      </div>
                      <div className="w-24">
                        <span className="font-semibold text-white">
                          {getDayOfWeek(day.date)}
                        </span>
                      </div>
                    </div>

                    <div className="flex w-24 justify-end">
                      <div className="flex flex-row items-end gap-2">
                        <div className="flex items-center">
                          <Sun03Icon
                            className="mr-1.5 h-7 w-7"
                            color="#FCD34D"
                            fill="#FCD34D"
                          />
                          <span className="w-8 font-medium text-white">
                            {dayTemp}°
                          </span>
                        </div>
                        <div className="mt-1 flex items-center">
                          <Moon02Icon
                            className="mr-1.5 h-7 w-7"
                            color="#93C5FD"
                            fill="#93C5FD"
                          />
                          <span className="w-8 text-white/80">
                            {nightTemp}°
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
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
          <div className="mt-2 grid grid-cols-3 gap-2">
            {[
              {
                icon: (
                  <FastWindIcon
                    className="h-6 w-6"
                    color={weatherTheme.colorCode}
                  />
                ),
                label: "Wind",
                value: `${weatherData.wind.speed} m/s`,
                tooltipText: "Wind speed in meters per second",
              },
              {
                icon: (
                  <DropletIcon
                    className="h-6 w-6"
                    color={weatherTheme.colorCode}
                  />
                ),
                label: "Humidity",
                value: `${weatherData.main.humidity}%`,
                tooltipText: "Amount of water vapor in the air",
              },
              ...(weatherData.visibility
                ? [
                    {
                      icon: (
                        <VisionIcon
                          className="h-6 w-6"
                          color={weatherTheme.colorCode}
                        />
                      ),
                      label: "Visibility",
                      value: `${(weatherData.visibility / 1000).toFixed(1)} km`,
                      tooltipText: "Maximum visibility distance",
                    },
                  ]
                : []),
              {
                icon: (
                  <CloudIcon
                    className="h-6 w-6"
                    color={weatherTheme.colorCode}
                  />
                ),
                label: "Pressure",
                value: `${weatherData.main.pressure} hPa`,
                tooltipText: "Atmospheric pressure in hectopascals",
              },
              {
                icon: (
                  <SunriseIcon
                    className="h-6 w-6"
                    color={weatherTheme.colorCode}
                  />
                ),
                label: "Sunrise",
                value: sunriseTime,
                tooltipText: "Time when the sun rises above the horizon",
              },
              {
                icon: (
                  <SunsetIcon
                    className="h-6 w-6"
                    color={weatherTheme.colorCode}
                  />
                ),
                label: "Sunset",
                value: sunsetTime,
                tooltipText: "Time when the sun disappears below the horizon",
              },
            ].map((detail, index) => (
              <WeatherDetailItem
                key={index}
                icon={detail.icon}
                label={detail.label}
                value={detail.value}
                tooltipText={detail.tooltipText}
                highlight={weatherTheme.colorCode}
              />
            ))}
          </div>
        </AccordionItem>
      </Accordion>
      {/*
      <div className="mt-2 flex items-center justify-between border-t border-white/10 pt-2 text-[10px] text-white/80">
        <div>
          <span>Data sources: </span>
          <a
            href="https://openweathermap.org/"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center transition-colors hover:text-white/80"
          >
            OpenWeatherMap
            <ExternalLinkIcon
              className="ml-0.5 h-2.5 w-2.5"
              color={weatherTheme.colorCode}
            />
          </a>
          <span>, </span>
          <a
            href="https://nominatim.openstreetmap.org/"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center transition-colors hover:text-white/80"
          >
            OpenStreetMap
            <ExternalLinkIcon
              className="ml-0.5 h-2.5 w-2.5"
              color={weatherTheme.colorCode}
            />
          </a>
          <span> & </span>
          <a
            href="https://ip-api.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center transition-colors hover:text-white/80"
          >
            IP-API
            <ExternalLinkIcon
              className="ml-0.5 h-2.5 w-2.5"
              color={weatherTheme.colorCode}
            />
          </a>
        </div>
      </div> */}
    </div>
  );
};
