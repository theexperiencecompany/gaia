import { Card } from "heroui-native";
import { Linking, Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";

export interface WebResult {
  title?: string;
  url?: string;
  snippet?: string;
}

export interface SearchResults {
  web?: WebResult[];
  images?: Array<{ url?: string }>;
  news?: Array<{ title?: string }>;
  query?: string;
}

export function SearchResultsCard({ data }: { data: SearchResults }) {
  const webCount = data.web?.length || 0;
  const imageCount = data.images?.length || 0;
  const newsCount = data.news?.length || 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Search Results</Text>
        {data.query && (
          <Text className="text-foreground font-medium mb-2">
            "{data.query}"
          </Text>
        )}
        <View className="flex-row gap-3">
          {webCount > 0 && (
            <Text className="text-muted text-sm">{webCount} web</Text>
          )}
          {imageCount > 0 && (
            <Text className="text-muted text-sm">{imageCount} images</Text>
          )}
          {newsCount > 0 && (
            <Text className="text-muted text-sm">{newsCount} news</Text>
          )}
        </View>
        {data.web && data.web.length > 0 && (
          <View className="mt-2">
            {data.web.slice(0, 2).map((result) => (
              <Pressable
                key={result.url || result.title}
                onPress={() => result.url && Linking.openURL(result.url)}
                className="mb-2"
              >
                <Text className="text-primary text-sm" numberOfLines={1}>
                  {result.title}
                </Text>
              </Pressable>
            ))}
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
