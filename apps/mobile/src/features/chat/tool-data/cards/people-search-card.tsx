import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface PeopleSearchData {
  name?: string;
  email?: string;
  organization?: string;
}

export function PeopleSearchCard({ data }: { data: PeopleSearchData[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">
          People Search ({data.length})
        </Text>
        {data.slice(0, 3).map((person) => (
          <View key={person.email || person.name} className="mb-2 last:mb-0">
            <Text className="text-foreground text-sm">
              {person.name || "Unknown"}
            </Text>
            {person.organization && (
              <Text className="text-muted text-xs">{person.organization}</Text>
            )}
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}
