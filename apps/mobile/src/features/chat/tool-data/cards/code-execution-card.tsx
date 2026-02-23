import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface CodeData {
  language?: string;
  code?: string;
  output?: string;
  error?: string;
}

export function CodeExecutionCard({ data }: { data: CodeData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">
          Code {data.language ? `(${data.language})` : ""}
        </Text>
        {data.output && (
          <Text className="text-foreground text-sm font-mono" numberOfLines={5}>
            {data.output}
          </Text>
        )}
        {data.error && (
          <Text className="text-danger text-sm font-mono" numberOfLines={3}>
            {data.error}
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}
