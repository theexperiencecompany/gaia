import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface WeatherData {
  location?: string;
  temperature?: number;
  condition?: string;
  humidity?: number;
  wind_speed?: number;
  unit?: string;
}

export function WeatherCard({ data }: { data: WeatherData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Weather</Text>
        <Text className="text-foreground font-medium text-lg">
          {data.location || "Unknown Location"}
        </Text>
        {data.temperature !== undefined && (
          <Text className="text-foreground text-2xl font-bold">
            {data.temperature}°{data.unit || "C"}
          </Text>
        )}
        {data.condition && (
          <Text className="text-muted text-sm">{data.condition}</Text>
        )}
        {data.humidity !== undefined && (
          <Text className="text-muted text-xs">Humidity: {data.humidity}%</Text>
        )}
      </Card.Body>
    </Card>
  );
}
