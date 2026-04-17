import type { WeatherData } from "@gaia/shared";
import { PressableFeedback } from "heroui-native";
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
import {
  SectionLabel,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

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
  if (weatherId >= 801 && weatherId <= 802) {
    return {
      name: "Partly Cloudy",
      iconName: CloudIcon,
      accentColor: "#E5E7EB",
    };
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
  return date.toLocaleDateString("en-US", { weekday: "long" });
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

  const regionName = hasRichData ? (data.location?.region ?? "") : "";

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

  const hasForecast = !!(data.forecast && data.forecast.length > 0);

  return (
    <ToolCardShell>
      {/* Hero zone */}
      <View className="flex-row items-start justify-between mb-3">
        <View className="flex-1 pr-3">
          <View className="flex-row items-center gap-1">
            <AppIcon icon={Location01Icon} size={14} color="#a1a1aa" />
            <Text className="text-zinc-400 text-sm font-medium flex-1">
              {cityName}
              {regionName ? `, ${regionName}` : ""}
            </Text>
          </View>
          {countryName ? (
            <Text className="text-xs ml-5" style={{ color: accentColor }}>
              {countryName}
            </Text>
          ) : null}
          {displayTemp !== undefined ? (
            <View className="flex-row items-baseline mt-1">
              <Text
                className="text-zinc-100"
                style={{ fontSize: 56, fontWeight: "300", lineHeight: 60 }}
              >
                {displayTemp}
              </Text>
              <Text className="text-zinc-400 text-2xl font-light ml-1">
                °{useFahrenheit ? "F" : (data.unit ?? "C")}
              </Text>
            </View>
          ) : null}
          {description ? (
            <Text className="text-zinc-100 text-base capitalize mt-1">
              {description}
            </Text>
          ) : null}
          {displayFeelsLike !== undefined ? (
            <Text className="text-zinc-500 text-xs mt-0.5">
              Feels like {displayFeelsLike}°
            </Text>
          ) : null}
        </View>

        <View className="items-end gap-3">
          {hasRichData && (
            <PressableFeedback
              onPress={() => setUseFahrenheit((p) => !p)}
              className="rounded-full bg-zinc-700 px-3 py-1"
            >
              <Text className="text-zinc-100 text-xs font-medium">
                °{useFahrenheit ? "C" : "F"}
              </Text>
            </PressableFeedback>
          )}
          <AppIcon icon={mainIconName} size={64} color={accentColor} />
        </View>
      </View>

      {/* Stats grid: wind, humidity, pressure — matches web order */}
      {(windSpeed !== undefined ||
        humidity !== undefined ||
        data.main?.pressure !== undefined) && (
        <View className="flex-row gap-2 mb-2">
          {windSpeed !== undefined && (
            <ToolCardInner dense className="flex-1 items-center">
              <AppIcon icon={FastWindIcon} size={18} color={accentColor} />
              <Text className="text-zinc-100 text-lg font-medium mt-1">
                {windSpeed}
                <Text className="text-zinc-400 text-xs"> m/s</Text>
              </Text>
              <SectionLabel>WIND</SectionLabel>
            </ToolCardInner>
          )}
          {humidity !== undefined && (
            <ToolCardInner dense className="flex-1 items-center">
              <AppIcon icon={DropletIcon} size={18} color={accentColor} />
              <Text className="text-zinc-100 text-lg font-medium mt-1">
                {humidity}%
              </Text>
              <SectionLabel>HUMIDITY</SectionLabel>
            </ToolCardInner>
          )}
          {data.main?.pressure !== undefined && (
            <ToolCardInner dense className="flex-1 items-center">
              <AppIcon icon={CloudIcon} size={18} color={accentColor} />
              <Text className="text-zinc-100 text-lg font-medium mt-1">
                {data.main.pressure}
                <Text className="text-zinc-400 text-xs"> hPa</Text>
              </Text>
              <SectionLabel>PRESSURE</SectionLabel>
            </ToolCardInner>
          )}
        </View>
      )}

      {/* Sunrise / Sunset */}
      {(sunriseStr || sunsetStr) && (
        <View className="flex-row gap-2 mb-2">
          {sunriseStr && (
            <ToolCardInner dense className="flex-1 flex-row items-center gap-2">
              <AppIcon icon={SunriseIcon} size={18} color={accentColor} />
              <View className="flex-1">
                <Text className="text-zinc-100 text-lg font-medium">
                  {sunriseStr}
                </Text>
                <SectionLabel>SUNRISE</SectionLabel>
              </View>
            </ToolCardInner>
          )}
          {sunsetStr && (
            <ToolCardInner dense className="flex-1 flex-row items-center gap-2">
              <AppIcon icon={SunsetIcon} size={18} color={accentColor} />
              <View className="flex-1">
                <Text className="text-zinc-100 text-lg font-medium">
                  {sunsetStr}
                </Text>
                <SectionLabel>SUNSET</SectionLabel>
              </View>
            </ToolCardInner>
          )}
        </View>
      )}

      {/* Weekly forecast — vertical list rows matching web layout */}
      {hasForecast && (
        <View className="gap-2 mt-1">
          <SectionLabel>FORECAST</SectionLabel>
          <View className="gap-2">
            {data.forecast!.map((day) => {
              const dayTemp = useFahrenheit
                ? Math.round(celsiusToFahrenheit(day.temp_max))
                : Math.round(day.temp_max);
              const nightTemp = useFahrenheit
                ? Math.round(celsiusToFahrenheit(day.temp_min))
                : Math.round(day.temp_min);
              const dayIcon = getWeatherIconForCondition(day.weather.main);

              return (
                <ToolCardInner
                  key={`${day.date}-${dayTemp}-${nightTemp}`}
                  dense
                  className="flex-row items-center"
                >
                  {/* Condition icon */}
                  <AppIcon icon={dayIcon} size={28} color={accentColor} />
                  {/* Day name */}
                  <Text className="text-zinc-100 font-semibold flex-1 ml-2">
                    {getDayOfWeek(day.date)}
                  </Text>
                  {/* High temp with sun icon */}
                  <View className="flex-row items-center mr-3">
                    <AppIcon icon={Sun03Icon} size={20} color="#FCD34D" />
                    <Text className="text-zinc-100 font-medium w-8 ml-1">
                      {dayTemp}°
                    </Text>
                  </View>
                  {/* Low temp */}
                  <Text className="text-zinc-400 w-8 text-right">
                    {nightTemp}°
                  </Text>
                </ToolCardInner>
              );
            })}
          </View>
        </View>
      )}
    </ToolCardShell>
  );
}
