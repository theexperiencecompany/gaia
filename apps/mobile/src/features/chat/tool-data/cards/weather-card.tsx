import type { WeatherData } from "@gaia/shared";
import { LinearGradient } from "expo-linear-gradient";
import { PressableFeedback } from "heroui-native";
import { useMemo, useState } from "react";
import { Pressable, View } from "react-native";
import {
  type AnyIcon,
  AppIcon,
  ArrowDown02Icon,
  CloudAngledRainIcon,
  CloudAngledZapIcon,
  CloudFastWindIcon,
  CloudIcon,
  CloudLittleRainIcon,
  CloudSnowIcon,
  DropletIcon,
  FastWindIcon,
  Location01Icon,
  Moon02Icon,
  Sun03Icon,
  SunriseIcon,
  SunsetIcon,
  Tornado02Icon,
  VisionIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

function celsiusToFahrenheit(c: number): number {
  return (c * 9) / 5 + 32;
}

function formatTime(timestamp: number, timezone: number): string {
  const date = new Date((timestamp + timezone) * 1000);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function getDayOfWeek(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { weekday: "long" });
}

type WeatherTheme = {
  name: string;
  iconName: AnyIcon;
  /** Two-stop linear gradient (top-left → bottom-right) — matches web /80 alpha. */
  gradient: readonly [string, string];
  /** Accent color, used for "feels like", icons in stat cards, and forecast condition icons. */
  accentColor: string;
};

/**
 * Weather theme map — ported 1:1 from
 * `apps/web/src/features/weather/components/WeatherCard.tsx`.
 *
 * The web uses Tailwind `bg-linear-to-br from-X/80 to-Y/80`; we approximate by
 * baking the /80 (0.8 alpha) into the rgba color stops below.
 */
function getWeatherTheme(weatherId: number): WeatherTheme {
  // Thunderstorm
  if (weatherId >= 200 && weatherId < 300) {
    return {
      name: "Thunderstorm",
      iconName: CloudAngledZapIcon,
      gradient: ["rgba(30,41,59,0.8)", "rgba(88,28,135,0.8)"], // slate-800 → purple-900
      accentColor: "#FCD34D",
    };
  }
  // Drizzle
  if (weatherId >= 300 && weatherId < 400) {
    return {
      name: "Drizzle",
      iconName: CloudLittleRainIcon,
      gradient: ["rgba(51,65,85,0.8)", "rgba(30,64,175,0.8)"], // slate-700 → blue-800
      accentColor: "#93C5FD",
    };
  }
  // Rain
  if (weatherId >= 500 && weatherId < 600) {
    return {
      name: "Rain",
      iconName: CloudAngledRainIcon,
      gradient: ["rgba(30,41,59,0.8)", "rgba(30,58,138,0.8)"], // slate-800 → blue-900
      accentColor: "#60A5FA",
    };
  }
  // Snow
  if (weatherId >= 600 && weatherId < 700) {
    return {
      name: "Snow",
      iconName: CloudSnowIcon,
      gradient: ["rgba(219,234,254,0.8)", "rgba(165,180,252,0.8)"], // blue-100 → indigo-300
      accentColor: "#E0F2FE",
    };
  }
  // Atmosphere
  if (weatherId >= 700 && weatherId < 800) {
    if (weatherId === 781) {
      return {
        name: "Tornado",
        iconName: Tornado02Icon,
        gradient: ["rgba(71,85,105,0.8)", "rgba(15,23,42,0.8)"], // slate-600 → slate-900
        accentColor: "#CBD5E1",
      };
    }
    if (weatherId === 771) {
      return {
        name: "Squall",
        iconName: FastWindIcon,
        gradient: ["rgba(59,130,246,0.8)", "rgba(29,78,216,0.8)"], // blue-500 → blue-700
        accentColor: "#93C5FD",
      };
    }
    if (weatherId === 762) {
      return {
        name: "Volcanic Ash",
        iconName: CloudFastWindIcon,
        gradient: ["rgba(82,82,91,0.8)", "rgba(39,39,42,0.8)"], // zinc-600 → zinc-800
        accentColor: "#D4D4D8",
      };
    }
    if (weatherId === 751) {
      return {
        name: "Sand",
        iconName: CloudFastWindIcon,
        gradient: ["rgba(253,186,116,0.8)", "rgba(249,115,22,0.8)"], // orange-300 → orange-500
        accentColor: "#FDBA74",
      };
    }
    if (weatherId === 741) {
      return {
        name: "Fog",
        iconName: CloudIcon,
        gradient: ["rgba(156,163,175,0.8)", "rgba(75,85,99,0.8)"], // gray-400 → gray-600
        accentColor: "#D1D5DB",
      };
    }
    if (weatherId === 731 || weatherId === 761) {
      return {
        name: "Dust",
        iconName: CloudFastWindIcon,
        gradient: ["rgba(250,204,21,0.8)", "rgba(202,138,4,0.8)"], // yellow-400 → yellow-600
        accentColor: "#FEF08A",
      };
    }
    if (weatherId === 721) {
      return {
        name: "Haze",
        iconName: CloudIcon,
        gradient: ["rgba(252,211,77,0.8)", "rgba(245,158,11,0.8)"], // amber-300 → amber-500
        accentColor: "#FDE68A",
      };
    }
    if (weatherId === 711) {
      return {
        name: "Smoke",
        iconName: CloudFastWindIcon,
        gradient: ["rgba(107,114,128,0.8)", "rgba(55,65,81,0.8)"], // gray-500 → gray-700
        accentColor: "#9CA3AF",
      };
    }
    if (weatherId === 701) {
      return {
        name: "Mist",
        iconName: CloudFastWindIcon,
        gradient: ["rgba(148,163,184,0.8)", "rgba(100,116,139,0.8)"], // slate-400 → slate-500
        accentColor: "#D1D5DB",
      };
    }
    return {
      name: "Atmosphere",
      iconName: CloudFastWindIcon,
      gradient: ["rgba(148,163,184,0.8)", "rgba(71,85,105,0.8)"], // slate-400 → slate-600
      accentColor: "#D1D5DB",
    };
  }
  // Clear
  if (weatherId === 800) {
    return {
      name: "Clear",
      iconName: Sun03Icon,
      gradient: ["rgba(234,179,8,0.8)", "rgba(249,115,22,0.8)"], // yellow-500 → orange-500
      accentColor: "#FBBF24",
    };
  }
  // Partly cloudy (few/scattered)
  if (weatherId >= 801 && weatherId <= 802) {
    return {
      name: "Partly Cloudy",
      iconName: CloudIcon,
      gradient: ["rgba(96,165,250,0.8)", "rgba(37,99,235,0.8)"], // blue-400 → blue-600
      accentColor: "#E5E7EB",
    };
  }
  // Cloudy (broken/overcast) and fallback
  return {
    name: "Cloudy",
    iconName: CloudIcon,
    gradient: ["rgba(100,116,139,0.8)", "rgba(51,65,85,0.8)"], // slate-500 → slate-700
    accentColor: "#E5E7EB",
  };
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

interface SectionToggleProps {
  title: string;
  open: boolean;
  onToggle: () => void;
}

function SectionToggle({ title, open, onToggle }: SectionToggleProps) {
  return (
    <Pressable
      onPress={onToggle}
      hitSlop={8}
      className="flex-row items-center justify-between py-2"
    >
      <Text className="text-sm font-normal text-white">{title}</Text>
      <View style={{ transform: [{ rotate: open ? "0deg" : "-90deg" }] }}>
        <AppIcon icon={ArrowDown02Icon} size={14} color="#ffffff" />
      </View>
    </Pressable>
  );
}

interface DetailItemProps {
  icon: AnyIcon;
  label: string;
  value: string;
  highlight: string;
}

function DetailItem({ icon, label, value, highlight }: DetailItemProps) {
  return (
    <View
      style={{
        backgroundColor: "rgba(0,0,0,0.15)",
        borderRadius: 12,
        paddingHorizontal: 12,
        paddingVertical: 8,
        flexBasis: "32%",
        flexGrow: 1,
      }}
    >
      <View className="flex-row items-start justify-between">
        <View className="flex-1">
          <Text className="text-sm text-white/70">{label}</Text>
          <Text className="font-medium text-white">{value}</Text>
        </View>
        <AppIcon icon={icon} size={20} color={highlight} />
      </View>
    </View>
  );
}

export function WeatherCard({ data }: { data: WeatherData }) {
  const [useFahrenheit, setUseFahrenheit] = useState(false);
  const [forecastOpen, setForecastOpen] = useState(true);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const hasRichData = !!(data.main && data.weather && data.weather.length > 0);
  const weatherId = hasRichData ? data.weather![0].id : undefined;
  const theme = useMemo(
    () =>
      weatherId !== undefined
        ? getWeatherTheme(weatherId)
        : getWeatherTheme(800),
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

  const sunriseStr =
    data.sys && data.timezone !== undefined
      ? formatTime(data.sys.sunrise, data.timezone)
      : undefined;
  const sunsetStr =
    data.sys && data.timezone !== undefined
      ? formatTime(data.sys.sunset, data.timezone)
      : undefined;

  const hasForecast = !!(data.forecast && data.forecast.length > 0);
  const accentColor = theme.accentColor;

  return (
    <View
      style={{
        marginHorizontal: 16,
        marginVertical: 4,
        borderRadius: 24,
        overflow: "hidden",
      }}
    >
      <LinearGradient
        colors={theme.gradient}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={{ padding: 24 }}
      >
        {/* Location row */}
        <View className="mb-3 flex-row items-start justify-between">
          <View className="flex-row items-start flex-1">
            <View style={{ marginTop: 2, marginRight: 8 }}>
              <AppIcon icon={Location01Icon} size={18} color="#ffffff" />
            </View>
            <View className="flex-1">
              <Text className="text-xl font-bold text-white">
                {cityName}
                {regionName ? `, ${regionName}` : ""}
              </Text>
              {countryName ? (
                <Text className="text-xs" style={{ color: accentColor }}>
                  {countryName}
                </Text>
              ) : null}
            </View>
          </View>

          {hasRichData && (
            <PressableFeedback
              onPress={() => setUseFahrenheit((p) => !p)}
              style={{
                height: 32,
                width: 32,
                borderRadius: 9999,
                backgroundColor: "rgba(255,255,255,0.1)",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Text className="text-xs font-medium text-white">
                °{useFahrenheit ? "C" : "F"}
              </Text>
            </PressableFeedback>
          )}
        </View>

        {/* Hero zone — 3 columns: icon | temp+feels-like | description */}
        <View className="mb-2 flex-row items-center justify-between">
          <View className="items-center justify-center">
            <AppIcon icon={theme.iconName} size={64} color={accentColor} />
          </View>

          <View>
            <View className="flex-row items-baseline">
              <Text
                style={{
                  color: "#ffffff",
                  fontSize: 36,
                  fontWeight: "700",
                  lineHeight: 40,
                }}
              >
                {displayTemp !== undefined ? `${displayTemp}°` : "--"}
              </Text>
              <Text
                style={{
                  color: "rgba(255,255,255,0.8)",
                  fontSize: 14,
                  fontWeight: "500",
                  marginLeft: 4,
                }}
              >
                {useFahrenheit ? "F" : (data.unit ?? "C")}
              </Text>
            </View>
            {displayFeelsLike !== undefined ? (
              <Text className="text-xs" style={{ color: accentColor }}>
                Feels like: {displayFeelsLike}°
              </Text>
            ) : null}
          </View>

          {description ? (
            <Text
              className="font-medium text-white capitalize flex-shrink"
              style={{ maxWidth: 110, textAlign: "right" }}
            >
              {description}
            </Text>
          ) : null}
        </View>

        {/* Weekly forecast — collapsible (default open) */}
        {hasForecast && (
          <View>
            <SectionToggle
              title="Weekly Forecast"
              open={forecastOpen}
              onToggle={() => setForecastOpen((p) => !p)}
            />
            {forecastOpen && (
              <View className="gap-2 pb-2">
                {data.forecast!.map((day) => {
                  const dayTemp = useFahrenheit
                    ? Math.round(celsiusToFahrenheit(day.temp_max))
                    : Math.round(day.temp_max);
                  const nightTemp = useFahrenheit
                    ? Math.round(celsiusToFahrenheit(day.temp_min))
                    : Math.round(day.temp_min);
                  const dayIcon = getWeatherIconForCondition(day.weather.main);

                  return (
                    <View
                      key={`${day.date}-${dayTemp}-${nightTemp}`}
                      style={{
                        flexDirection: "row",
                        alignItems: "center",
                        backgroundColor: "rgba(0,0,0,0.15)",
                        borderRadius: 12,
                        paddingHorizontal: 8,
                        paddingVertical: 6,
                      }}
                    >
                      <View className="flex-row items-center flex-1 gap-2">
                        <AppIcon icon={dayIcon} size={28} color={accentColor} />
                        <Text
                          className="font-semibold text-white"
                          style={{ width: 96 }}
                        >
                          {getDayOfWeek(day.date)}
                        </Text>
                      </View>

                      <View
                        className="flex-row items-center justify-end"
                        style={{ width: 140 }}
                      >
                        <View className="flex-row items-center mr-2">
                          <AppIcon icon={Sun03Icon} size={20} color="#FCD34D" />
                          <Text
                            className="font-medium text-white ml-1"
                            style={{ width: 32 }}
                          >
                            {dayTemp}°
                          </Text>
                        </View>
                        <View className="flex-row items-center">
                          <AppIcon
                            icon={Moon02Icon}
                            size={20}
                            color="#93C5FD"
                          />
                          <Text
                            className="ml-1"
                            style={{
                              color: "rgba(255,255,255,0.8)",
                              width: 32,
                            }}
                          >
                            {nightTemp}°
                          </Text>
                        </View>
                      </View>
                    </View>
                  );
                })}
              </View>
            )}
          </View>
        )}

        {/* Additional information — collapsible (default closed, matches web Accordion behavior) */}
        <SectionToggle
          title="Additional Information"
          open={detailsOpen}
          onToggle={() => setDetailsOpen((p) => !p)}
        />
        {detailsOpen && (
          <View
            style={{
              flexDirection: "row",
              flexWrap: "wrap",
              gap: 8,
              marginTop: 8,
            }}
          >
            {windSpeed !== undefined && (
              <DetailItem
                icon={FastWindIcon}
                label="Wind"
                value={`${windSpeed} m/s`}
                highlight={accentColor}
              />
            )}
            {humidity !== undefined && (
              <DetailItem
                icon={DropletIcon}
                label="Humidity"
                value={`${humidity}%`}
                highlight={accentColor}
              />
            )}
            {data.visibility !== undefined && (
              <DetailItem
                icon={VisionIcon}
                label="Visibility"
                value={`${(data.visibility / 1000).toFixed(1)} km`}
                highlight={accentColor}
              />
            )}
            {data.main?.pressure !== undefined && (
              <DetailItem
                icon={CloudIcon}
                label="Pressure"
                value={`${data.main.pressure} hPa`}
                highlight={accentColor}
              />
            )}
            {sunriseStr && (
              <DetailItem
                icon={SunriseIcon}
                label="Sunrise"
                value={sunriseStr}
                highlight={accentColor}
              />
            )}
            {sunsetStr && (
              <DetailItem
                icon={SunsetIcon}
                label="Sunset"
                value={sunsetStr}
                highlight={accentColor}
              />
            )}
          </View>
        )}
      </LinearGradient>
    </View>
  );
}
