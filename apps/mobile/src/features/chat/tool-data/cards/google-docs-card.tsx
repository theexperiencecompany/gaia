import { Card } from "heroui-native";
import { Linking, Pressable } from "react-native";
import { Text } from "@/components/ui/text";

export interface GoogleDocsData {
  documentId?: string;
  title?: string;
  url?: string;
}

export function GoogleDocsCard({ data }: { data: GoogleDocsData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Google Doc</Text>
        <Text className="text-foreground font-medium">
          {data.title || "Untitled Document"}
        </Text>
        {data.url && (
          <Pressable onPress={() => Linking.openURL(data.url!)}>
            <Text className="text-primary text-sm mt-1">Open in Browser</Text>
          </Pressable>
        )}
      </Card.Body>
    </Card>
  );
}
