import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface DeepResearchResults {
  topic?: string;
  summary?: string;
  sources?: Array<{ title?: string; url?: string }>;
}

export function DeepResearchCard({ data }: { data: DeepResearchResults }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Deep Research</Text>
        {data.topic && (
          <Text className="text-foreground font-medium mb-1">{data.topic}</Text>
        )}
        {data.summary && (
          <Text className="text-muted text-sm" numberOfLines={3}>
            {data.summary}
          </Text>
        )}
        {data.sources && data.sources.length > 0 && (
          <Text className="text-muted text-xs mt-2">
            {data.sources.length} sources
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}
