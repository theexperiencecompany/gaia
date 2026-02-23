import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface DocumentData {
  title?: string;
  content?: string;
  type?: string;
}

export function DocumentCard({ data }: { data: DocumentData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">
          {data.type || "Document"}
        </Text>
        <Text className="text-foreground font-medium">
          {data.title || "Untitled Document"}
        </Text>
        {data.content && (
          <Text className="text-muted text-sm mt-1" numberOfLines={2}>
            {data.content}
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}
