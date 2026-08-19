import { Switch } from "@heroui/switch";
import { Location01Icon, ThermometerWarmIcon } from "@icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { WeatherData } from "@/types/features/convoTypes";

interface WeatherHeaderProps {
  weatherData: WeatherData;
  colorCode: string;
  useFahrenheit: boolean;
  onToggleUnit: (value: boolean) => void;
}

export function WeatherHeader({
  weatherData,
  colorCode,
  useFahrenheit,
  onToggleUnit,
}: WeatherHeaderProps) {
  return (
    <div className="mb-3 flex items-start justify-between gap-10">
      <div className="flex items-start">
        <Location01Icon className="relative top-1 mr-2 h-5 w-5" color="white" />
        <div>
          <h2 className="flex items-center text-xl font-bold text-white">
            {weatherData.location.city}
            {weatherData.location.region
              ? `,${weatherData.location.region}`
              : ""}
          </h2>
          <p className="text-xs" style={{ color: colorCode }}>
            {weatherData.location.country}
          </p>
        </div>
      </div>

      <div className="flex items-center">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
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
                  onValueChange={onToggleUnit}
                  color="default"
                />
                <span className="text-sm">°C</span>
              </div>
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
