import { Card, PressableFeedback } from "heroui-native";
import { useMemo, useState } from "react";
import { View } from "react-native";
import {
  type AnyIcon,
  AppIcon,
  CloudAngledRainIcon,
  CloudAngledZapIcon,
  CloudFastWindIcon,
  CloudIcon,
  CloudLittleRainIcon,
  CloudSnowIcon,
  DropletIcon,
  FastWindIcon,
  Location01Icon,
  Sun03Icon,
  SunriseIcon,
  SunsetIcon,
  Tornado02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface WeatherData {
  coord?: { lon: number; lat: number };
  weather?: Array<{
    id: number;
    main: string;
    description: string;
    icon: string;
  }>;
  main?: {
    temp: number;
    feels_like: number;
    temp_min?: number;
    temp_max?: number;
    pressure?: number;
    humidity: number;
  };
  visibility?: number;
  wind?: { speed: number; deg?: number; gust?: number };
  dt?: number;
  sys?: { country: string; sunrise: number; sunset: number };
  timezone?: number;
  name?: string;
  location?: {
    city: string;
    country: string | null;
    region: string | null;
  };
  forecast?: Array<{
    date: string;
    timestamp: number;
    temp_min: number;
    temp_max: number;
    humidity: number;
    weather: { main: string; description: string; icon: string };
  }>;
  // Simple flat fields (fallback for tool output)
  temperature?: number;
  condition?: string;
  humidity?: number;
  wind_speed?: number;
  unit?: string;
}

function celsiusToFahrenheit(c: number): number {
  return (c * 9) / 5 + 32;
}

function formatTime(timestamp: number, timezone: number): string {
  const date = new Date((timestamp + timezone) * 1000);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

type WeatherTheme = {
  name: string;
  iconName: AnyIcon;
  accentColor: string;
};

function getWeatherTheme(weatherId: number): WeatherTheme {
  if (weatherId >= 200 && weatherId < 300) {
    return {
      name: "Thunderstorm",
      iconName: CloudAngledZapIcon,
      accentColor: "#FCD34D",
    };
  }
  if (weatherId >= 300 && weatherId < 400) {
    return {
      name: "Drizzle",
      iconName: CloudLittleRainIcon,
      accentColor: "#93C5FD",
    };
  }
  if (weatherId >= 500 && weatherId < 600) {
    return {
      name: "Rain",
      iconName: CloudAngledRainIcon,
      accentColor: "#60A5FA",
    };
  }
  if (weatherId >= 600 && weatherId < 700) {
    return { name: "Snow", iconName: CloudSnowIcon, accentColor: "#E0F2FE" };
  }
  if (weatherId >= 700 && weatherId < 800) {
    return {
      name: "Atmosphere",
      iconName: CloudFastWindIcon,
      accentColor: "#D1D5DB",
    };
  }
  if (weatherId === 781) {
    return { name: "Tornado", iconName: Tornado02Icon, accentColor: "#CBD5E1" };
  }
  if (weatherId === 800) {
    return { name: "Clear", iconName: Sun03Icon, accentColor: "#FBBF24" };
  }
  return { name: "Cloudy", iconName: CloudIcon, accentColor: "#E5E7EB" };
}

function getWeatherIconForCondition(main: string): AnyIcon {
  switch (main.toLowerCase()) {
    case "thunderstorm":
      return CloudAngledZapIcon;
    case "drizzle":
      return CloudLittleRainIcon;
    case "rain":
      return CloudAngledRainIcon;
    case "snow":
      return CloudSnowIcon;
    case "clear":
      return Sun03Icon;
    case "tornado":
      return Tornado02Icon;
    default:
      return CloudIcon;
  }
}

function getDayOfWeek(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { weekday: "short" });
}

export function WeatherCard({ data }: { data: WeatherData }) {
  const [useFahrenheit, setUseFahrenheit] = useState(false);

  const hasRichData = !!(data.main && data.weather && data.weather.length > 0);

  const weatherId = hasRichData ? data.weather![0].id : undefined;
  const theme = useMemo(
    () => (weatherId !== undefined ? getWeatherTheme(weatherId) : null),
    [weatherId],
  );

  const rawTemp = hasRichData ? data.main!.temp : data.temperature;
  const feelsLike = hasRichData ? data.main!.feels_like : undefined;
  const humidity = hasRichData ? data.main!.humidity : data.humidity;
  const windSpeed = hasRichData ? data.wind?.speed : data.wind_speed;
  const description = hasRichData
    ? data.weather![0].description
    : data.condition;

  const displayTemp =
    rawTemp !== undefined
      ? useFahrenheit
        ? Math.round(celsiusToFahrenheit(rawTemp))
        : Math.round(rawTemp)
      : undefined;

  const displayFeelsLike =
    feelsLike !== undefined
      ? useFahrenheit
        ? Math.round(celsiusToFahrenheit(feelsLike))
        : Math.round(feelsLike)
      : undefined;

  const cityName = hasRichData
    ? (data.location?.city ?? data.name ?? "Unknown")
    : ((data.location as string | undefined) ?? "Unknown");

  const countryName = hasRichData
    ? (data.location?.country ?? data.sys?.country ?? "")
    : "";

  const accentColor = theme?.accentColor ?? "#FBBF24";
  const mainIconName = theme?.iconName ?? Sun03Icon;

  const sunriseStr =
    data.sys && data.timezone !== undefined
      ? formatTime(data.sys.sunrise, data.timezone)
      : undefined;
  const sunsetStr =
    data.sys && data.timezone !== undefined
      ? formatTime(data.sys.sunset, data.timezone)
      : undefined;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header: location + unit toggle */}
        <View className="flex-row items-start justify-between mb-3">
          <View className="flex-row items-start gap-1.5 flex-1">
            <AppIcon
              icon={Location01Icon}
              size={14}
              color="#8e8e93"
              style={{ marginTop: 2 }}
            />
            <View className="flex-1">
              <Text className="text-sm font-semibold text-foreground">
                {cityName}
                {countryName ? `, ${countryName}` : ""}
              </Text>
              {data.location?.region ? (
                <Text className="text-xs" style={{ color: accentColor }}>
                  {data.location.region}
                </Text>
              ) : null}
            </View>
          </View>
          {hasRichData && (
            <PressableFeedback
              onPress={() => setUseFahrenheit((p) => !p)}
              className="rounded-full bg-white/10 px-2.5 py-1"
            >
              <Text className="text-xs text-muted font-medium">
                °{useFahrenheit ? "C" : "F"}
              </Text>
            </PressableFeedback>
          )}
        </View>

        {/* Main weather display */}
        <View className="rounded-xl bg-white/5 border border-white/10 p-3 mb-3">
          <View className="flex-row items-center justify-between">
            <View className="items-center justify-center w-16 h-16">
              <AppIcon icon={mainIconName} size={52} color={accentColor} />
            </View>

            <View className="items-end flex-1">
              {displayTemp !== undefined ? (
                <View className="flex-row items-baseline">
                  <Text
                    className="font-bold text-foreground"
                    style={{ fontSize: 48, lineHeight: 52 }}
                  >
                    {displayTemp}
                  </Text>
                  <Text className="text-xl font-medium text-foreground/80 ml-0.5">
                    °{useFahrenheit ? "F" : (data.unit ?? "C")}
                  </Text>
                </View>
              ) : null}
              {description ? (
                <Text
                  className="text-sm font-medium capitalize mt-0.5"
                  style={{ color: accentColor }}
                >
                  {description}
                </Text>
              ) : null}
              {displayFeelsLike !== undefined ? (
                <Text className="text-xs text-muted mt-0.5">
                  Feels like {displayFeelsLike}°
                </Text>
              ) : null}
            </View>
          </View>
        </View>

        {/* Secondary stats row */}
        <View className="flex-row gap-2 mb-2">
          {humidity !== undefined && (
            <View className="flex-1 rounded-xl bg-white/5 border border-white/10 p-2.5 items-center gap-1">
              <AppIcon icon={DropletIcon} size={18} color={accentColor} />
              <Text className="text-[10px] text-muted">Humidity</Text>
              <Text className="text-sm font-semibold text-foreground">
                {humidity}%
              </Text>
            </View>
          )}
          {windSpeed !== undefined && (
            <View className="flex-1 rounded-xl bg-white/5 border border-white/10 p-2.5 items-center gap-1">
              <AppIcon icon={FastWindIcon} size={18} color={accentColor} />
              <Text className="text-[10px] text-muted">Wind</Text>
              <Text className="text-sm font-semibold text-foreground">
                {windSpeed} m/s
              </Text>
            </View>
          )}
          {data.main?.pressure !== undefined && (
            <View className="flex-1 rounded-xl bg-white/5 border border-white/10 p-2.5 items-center gap-1">
              <AppIcon icon={CloudIcon} size={18} color={accentColor} />
              <Text className="text-[10px] text-muted">Pressure</Text>
              <Text className="text-sm font-semibold text-foreground">
                {data.main.pressure}
              </Text>
            </View>
          )}
        </View>

        {/* Sunrise / Sunset */}
        {(sunriseStr || sunsetStr) && (
          <View className="flex-row gap-2 mb-2">
            {sunriseStr && (
              <View className="flex-1 rounded-xl bg-white/5 border border-white/10 p-2.5 flex-row items-center gap-2">
                <AppIcon icon={SunriseIcon} size={16} color={accentColor} />
                <View>
                  <Text className="text-[10px] text-muted">Sunrise</Text>
                  <Text className="text-xs font-semibold text-foreground">
                    {sunriseStr}
                  </Text>
                </View>
              </View>
            )}
            {sunsetStr && (
              <View className="flex-1 rounded-xl bg-white/5 border border-white/10 p-2.5 flex-row items-center gap-2">
                <AppIcon icon={SunsetIcon} size={16} color={accentColor} />
                <View>
                  <Text className="text-[10px] text-muted">Sunset</Text>
                  <Text className="text-xs font-semibold text-foreground">
                    {sunsetStr}
                  </Text>
                </View>
              </View>
            )}
          </View>
        )}

        {/* Weekly forecast */}
        {data.forecast && data.forecast.length > 0 && (
          <View className="rounded-xl bg-white/5 border border-white/10 overflow-hidden">
            <View className="px-3 py-2 border-b border-white/8">
              <Text className="text-xs text-muted font-medium">
                Weekly Forecast
              </Text>
            </View>
            {data.forecast.map((day) => {
              const dayTemp = useFahrenheit
                ? Math.round(celsiusToFahrenheit(day.temp_max))
                : Math.round(day.temp_max);
              const nightTemp = useFahrenheit
                ? Math.round(celsiusToFahrenheit(day.temp_min))
                : Math.round(day.temp_min);
              const dayIcon = getWeatherIconForCondition(day.weather.main);

              return (
                <View
                  key={`${day.date}-${dayTemp}`}
                  className="flex-row items-center px-3 py-2 border-b border-white/8"
                >
                  <AppIcon icon={dayIcon} size={20} color={accentColor} />
                  <Text className="text-xs font-semibold text-foreground ml-2 w-10">
                    {getDayOfWeek(day.date)}
                  </Text>
                  <Text
                    className="text-xs text-muted flex-1 capitalize"
                    numberOfLines={1}
                  >
                    {day.weather.description}
                  </Text>
                  <View className="flex-row items-center gap-3">
                    <View className="flex-row items-center gap-1">
                      <AppIcon icon={Sun03Icon} size={14} color="#FCD34D" />
                      <Text className="text-xs font-medium text-foreground">
                        {dayTemp}°
                      </Text>
                    </View>
                    <View className="flex-row items-center gap-1">
                      <AppIcon icon={CloudIcon} size={14} color="#93C5FD" />
                      <Text className="text-xs text-foreground/70">
                        {nightTemp}°
                      </Text>
                    </View>
                  </View>
                </View>
              );
            })}
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
