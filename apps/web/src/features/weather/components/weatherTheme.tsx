import {
  CloudAngledRainIcon,
  CloudAngledZapIcon,
  CloudIcon,
  CloudLittleRainIcon,
  CloudSnowIcon,
  FastWindIcon,
  Sun03Icon,
  Tornado02Icon,
} from "@icons";
import type React from "react";
import { CloudFogIcon } from "@/components/shared/icons";
import type { WeatherData } from "@/types/features/convoTypes";

export interface WeatherTheme {
  name: string;
  icon: React.ReactNode;
  gradient: string;
  colorCode: string;
}

export function getWeatherIcon(
  main: string,
  className = "",
  fill = "",
): React.ReactNode {
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
}

export function getAtmosphereTheme(weatherId: number): WeatherTheme {
  if (weatherId === 701) {
    return {
      name: "Mist",
      icon: (
        <CloudFogIcon className="h-16 w-16" fill="#D1D5DB" color="#D1D5DB" />
      ),
      gradient: "bg-linear-to-br from-slate-400/80 to-slate-500/80",
      colorCode: "#D1D5DB",
    };
  }
  if (weatherId === 711) {
    return {
      name: "Smoke",
      icon: (
        <CloudFogIcon className="h-16 w-16" fill="#9CA3AF" color="#9CA3AF" />
      ),
      gradient: "bg-linear-to-br from-gray-500/80 to-gray-700/80",
      colorCode: "#9CA3AF",
    };
  }
  if (weatherId === 721) {
    return {
      name: "Haze",
      icon: <CloudIcon className="h-16 w-16" fill="#FDE68A" color="#FDE68A" />,
      gradient: "bg-linear-to-br from-amber-300/80 to-amber-500/80",
      colorCode: "#FDE68A",
    };
  }
  if (weatherId === 731 || weatherId === 761) {
    return {
      name: "Dust",
      icon: (
        <CloudFogIcon className="h-16 w-16" fill="#FEF08A" color="#FEF08A" />
      ),
      gradient: "bg-linear-to-br from-yellow-400/80 to-yellow-600/80",
      colorCode: "#FEF08A",
    };
  }
  if (weatherId === 741) {
    return {
      name: "Fog",
      icon: <CloudIcon className="h-16 w-16" fill="#D1D5DB" color="#D1D5DB" />,
      gradient: "bg-linear-to-br from-gray-400/80 to-gray-600/80",
      colorCode: "#D1D5DB",
    };
  }
  if (weatherId === 751) {
    return {
      name: "Sand",
      icon: (
        <CloudFogIcon className="h-16 w-16" fill="#FDBA74" color="#FDBA74" />
      ),
      gradient: "bg-linear-to-br from-orange-300/80 to-orange-500/80",
      colorCode: "#FDBA74",
    };
  }
  if (weatherId === 762) {
    return {
      name: "Volcanic Ash",
      icon: (
        <CloudFogIcon className="h-16 w-16" fill="#D4D4D8" color="#D4D4D8" />
      ),
      gradient: "bg-linear-to-br from-zinc-600/80 to-zinc-800/80",
      colorCode: "#D4D4D8",
    };
  }
  if (weatherId === 771) {
    return {
      name: "Squall",
      icon: (
        <FastWindIcon className="h-16 w-16" fill="#93C5FD" color="#93C5FD" />
      ),
      gradient: "bg-linear-to-br from-blue-500/80 to-blue-700/80",
      colorCode: "#93C5FD",
    };
  }
  if (weatherId === 781) {
    return {
      name: "Tornado",
      icon: (
        <Tornado02Icon className="h-16 w-16" fill="#CBD5E1" color="#CBD5E1" />
      ),
      gradient: "bg-linear-to-br from-slate-600/80 to-slate-900/80",
      colorCode: "#CBD5E1",
    };
  }
  return {
    name: "Atmosphere",
    icon: <CloudFogIcon className="h-16 w-16" fill="#D1D5DB" color="#D1D5DB" />,
    gradient: "bg-linear-to-br from-slate-400/80 to-slate-600/80",
    colorCode: "#D1D5DB",
  };
}

export function getWeatherTheme(weatherData: WeatherData): WeatherTheme | null {
  if (!weatherData?.weather?.[0]) return null;
  const weatherId = weatherData.weather[0].id;

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
      colorCode: "#FCD34D",
    };
  }
  if (weatherId >= 300 && weatherId < 400) {
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
      colorCode: "#93C5FD",
    };
  }
  if (weatherId >= 500 && weatherId < 600) {
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
      colorCode: "#60A5FA",
    };
  }
  if (weatherId >= 600 && weatherId < 700) {
    return {
      name: "Snow",
      icon: (
        <CloudSnowIcon className="h-16 w-16" fill="#E0F2FE" color="#E0F2FE" />
      ),
      gradient: "bg-linear-to-br from-blue-100/80 to-indigo-300/80",
      colorCode: "#E0F2FE",
    };
  }
  if (weatherId >= 700 && weatherId < 800) {
    return getAtmosphereTheme(weatherId);
  }
  if (weatherId === 800) {
    return {
      name: "Clear",
      icon: <Sun03Icon className="h-16 w-16" fill="#FBBF24" color="#FBBF24" />,
      gradient: "bg-linear-to-br from-yellow-500/80 to-orange-500/80",
      colorCode: "#FBBF24",
    };
  }
  if (weatherId >= 801 && weatherId <= 802) {
    return {
      name: "Partly Cloudy",
      icon: <CloudIcon className="h-16 w-16" fill="#E5E7EB" color="#E5E7EB" />,
      gradient: "bg-linear-to-br from-blue-400/80 to-blue-600/80",
      colorCode: "#E5E7EB",
    };
  }
  if (weatherId >= 803 && weatherId <= 804) {
    return {
      name: "Cloudy",
      icon: <CloudIcon className="h-16 w-16" fill="#E5E7EB" color="#E5E7EB" />,
      gradient: "bg-linear-to-br from-slate-500/80 to-slate-700/80",
      colorCode: "#E5E7EB",
    };
  }
  return {
    name: "Unknown",
    icon: <CloudIcon className="h-16 w-16" fill="#E5E7EB" color="#E5E7EB" />,
    gradient: "bg-linear-to-br from-slate-500/80 to-slate-700/80",
    colorCode: "#E5E7EB",
  };
}
