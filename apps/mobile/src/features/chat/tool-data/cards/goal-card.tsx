import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface GoalData {
  goals?: Array<{
    title?: string;
    status?: string;
    progress?: number;
  }>;
  action?: string;
  message?: string;
}

export function GoalCard({ data }: { data: GoalData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Goals</Text>
        {data.message && (
          <Text className="text-foreground text-sm mb-1">{data.message}</Text>
        )}
        {data.goals?.slice(0, 2).map((goal) => (
          <View key={goal.title} className="mb-1">
            <Text className="text-foreground text-sm">{goal.title}</Text>
            {goal.progress !== undefined && (
              <Text className="text-muted text-xs">{goal.progress}%</Text>
            )}
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}
