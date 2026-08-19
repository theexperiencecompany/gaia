import { Moon02Icon, Sun03Icon } from "@icons";
import type { WeatherData } from "@/types/features/convoTypes";
import { getWeatherIcon } from "./weatherTheme";
import { celsiusToFahrenheit, getDayOfWeek } from "./weatherUtils";

interface WeatherForecastListProps {
  forecast: NonNullable<WeatherData["forecast"]>;
  useFahrenheit: boolean;
  colorCode: string;
}

export function WeatherForecastList({
  forecast,
  useFahrenheit,
  colorCode,
}: WeatherForecastListProps) {
  return (
    <div className="space-y-2 pb-2">
      {forecast.map((day) => {
        const dayTemp = useFahrenheit
          ? Math.round(celsiusToFahrenheit(day.temp_max))
          : Math.round(day.temp_max);
        const nightTemp = useFahrenheit
          ? Math.round(celsiusToFahrenheit(day.temp_min))
          : Math.round(day.temp_min);

        return (
          <div
            key={`${day.date}-${dayTemp}-${nightTemp}`}
            className="flex items-center justify-start rounded-xl bg-black/15 px-2 py-1 text-white"
          >
            <div className="flex w-full flex-1 items-center justify-start gap-2">
              <div className="flex items-center justify-center">
                {getWeatherIcon(day.weather.main, "h-7 w-7", colorCode)}
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
                  <span className="w-8 font-medium text-white">{dayTemp}°</span>
                </div>
                <div className="mt-1 flex items-center">
                  <Moon02Icon
                    className="mr-1.5 h-7 w-7"
                    color="#93C5FD"
                    fill="#93C5FD"
                  />
                  <span className="w-8 text-white/80">{nightTemp}°</span>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
