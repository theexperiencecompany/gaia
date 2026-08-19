import {
  CloudIcon,
  DropletIcon,
  FastWindIcon,
  SunriseIcon,
  SunsetIcon,
  VisionIcon,
} from "@icons";
import type { WeatherData } from "@/types/features/convoTypes";
import { WeatherDetailItem } from "./WeatherDetailItem";

interface WeatherDetailsGridProps {
  weatherData: WeatherData;
  colorCode: string;
  sunriseTime: string;
  sunsetTime: string;
}

export function WeatherDetailsGrid({
  weatherData,
  colorCode,
  sunriseTime,
  sunsetTime,
}: WeatherDetailsGridProps) {
  return (
    <div className="mt-2 grid grid-cols-3 gap-2">
      {[
        {
          icon: <FastWindIcon className="h-6 w-6" color={colorCode} />,
          label: "Wind",
          value: `${weatherData.wind.speed} m/s`,
          tooltipText: "Wind speed in meters per second",
        },
        {
          icon: <DropletIcon className="h-6 w-6" color={colorCode} />,
          label: "Humidity",
          value: `${weatherData.main?.humidity ?? 0}%`,
          tooltipText: "Amount of water vapor in the air",
        },
        ...(weatherData.visibility
          ? [
              {
                icon: <VisionIcon className="h-6 w-6" color={colorCode} />,
                label: "Visibility",
                value: `${(weatherData.visibility / 1000).toFixed(1)} km`,
                tooltipText: "Maximum visibility distance",
              },
            ]
          : []),
        {
          icon: <CloudIcon className="h-6 w-6" color={colorCode} />,
          label: "Pressure",
          value: `${weatherData.main?.pressure ?? 0} hPa`,
          tooltipText: "Atmospheric pressure in hectopascals",
        },
        {
          icon: <SunriseIcon className="h-6 w-6" color={colorCode} />,
          label: "Sunrise",
          value: sunriseTime,
          tooltipText: "Time when the sun rises above the horizon",
        },
        {
          icon: <SunsetIcon className="h-6 w-6" color={colorCode} />,
          label: "Sunset",
          value: sunsetTime,
          tooltipText: "Time when the sun disappears below the horizon",
        },
      ].map((detail) => (
        <WeatherDetailItem
          key={detail.value}
          icon={detail.icon}
          label={detail.label}
          value={detail.value}
          tooltipText={detail.tooltipText}
          highlight={colorCode}
        />
      ))}
    </div>
  );
}
