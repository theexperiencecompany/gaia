import type { WeatherData } from "@/types/features/convoTypes";

interface WeatherMainDisplayProps {
  weatherData: WeatherData;
  icon: React.ReactNode;
  displayTemp: number;
  displayFeelsLike: number;
  useFahrenheit: boolean;
  colorCode: string;
}

export function WeatherMainDisplay({
  weatherData,
  icon,
  displayTemp,
  displayFeelsLike,
  useFahrenheit,
  colorCode,
}: WeatherMainDisplayProps) {
  return (
    <div className="mb-2 flex items-center justify-between gap-5">
      <div className="flex items-center justify-center">{icon}</div>

      <div>
        <div className="flex items-baseline">
          <span className="text-4xl font-bold text-white">{displayTemp}°</span>
          <span className="ml-1 text-sm font-medium text-white/80">
            {useFahrenheit ? "F" : "C"}
          </span>
        </div>
        <p
          className="text-xs"
          style={{
            color: colorCode,
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
  );
}
