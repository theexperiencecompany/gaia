import { Card } from "heroui-native";
import { useState } from "react";
import { Image, Linking, Pressable, View } from "react-native";
import {
  AppIcon,
  Globe02Icon,
  News01Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface WebResult {
  title?: string;
  url?: string;
  content?: string;
  snippet?: string;
  score?: number;
}

export interface NewsResult {
  title?: string;
  url?: string;
  content?: string;
  score?: number;
}

export interface SearchResults {
  web?: WebResult[];
  images?: string[];
  news?: NewsResult[];
  answer?: string;
  query?: string;
  response_time?: number;
  request_id?: string;
}

function getHostname(url?: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function FaviconImage({ url }: { url?: string }) {
  const [errored, setErrored] = useState(false);
  const hostname = getHostname(url);

  if (!hostname || errored) {
    return (
      <View className="w-4 h-4 rounded-full bg-white/10 items-center justify-center">
        <HugeiconsIcon icon={Globe02Icon} size={10} color="#8e8e93" />
      </View>
    );
  }

  return (
    <Image
      source={{
        uri: `https://www.google.com/s2/favicons?domain=${hostname}&sz=64`,
      }}
      style={{ width: 14, height: 14, borderRadius: 7 }}
      onError={() => setErrored(true)}
    />
  );
}

function WebResultRow({ result }: { result: WebResult }) {
  const hostname = getHostname(result.url);
  const description = result.content || result.snippet;

  return (
    <Pressable
      onPress={() => result.url && Linking.openURL(result.url)}
      className="py-3 border-b border-white/8 active:opacity-70"
    >
      <View className="flex-row items-start gap-2.5">
        <View className="mt-0.5">
          <FaviconImage url={result.url} />
        </View>
        <View className="flex-1 gap-0.5">
          <Text
            className="text-sm font-medium text-foreground"
            numberOfLines={2}
          >
            {result.title || hostname || "Untitled"}
          </Text>
          {!!description && (
            <Text className="text-xs text-muted leading-4" numberOfLines={2}>
              {description}
            </Text>
          )}
          {!!hostname && (
            <Text
              className="text-[11px] text-[#00bbff] mt-0.5"
              numberOfLines={1}
            >
              {hostname}
            </Text>
          )}
        </View>
      </View>
    </Pressable>
  );
}

function NewsResultRow({ article }: { article: NewsResult }) {
  const hostname = getHostname(article.url);
  const description = article.content;

  return (
    <Pressable
      onPress={() => article.url && Linking.openURL(article.url)}
      className="py-3 border-b border-white/8 active:opacity-70"
    >
      <View className="flex-row items-start gap-2.5">
        <View className="mt-0.5">
          <FaviconImage url={article.url} />
        </View>
        <View className="flex-1 gap-0.5">
          <Text
            className="text-sm font-medium text-foreground"
            numberOfLines={2}
          >
            {article.title || "Untitled"}
          </Text>
          {!!description && (
            <Text className="text-xs text-muted leading-4" numberOfLines={2}>
              {description}
            </Text>
          )}
          {!!hostname && (
            <Text
              className="text-[11px] text-[#00bbff] mt-0.5"
              numberOfLines={1}
            >
              {hostname}
            </Text>
          )}
        </View>
      </View>
    </Pressable>
  );
}

export function SearchResultsCard({ data }: { data: SearchResults }) {
  const [expanded, setExpanded] = useState(false);
  const webResults = data.web ?? [];
  const newsResults = data.news ?? [];
  const totalResults = webResults.length + newsResults.length;
  const previewResults = webResults.slice(0, 3);
  const allWebResults = expanded ? webResults : previewResults;
  const hasMore = webResults.length > 3 || newsResults.length > 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center gap-2">
            <HugeiconsIcon icon={Search01Icon} size={14} color="#8e8e93" />
            <Text className="text-xs text-muted">Search Results</Text>
          </View>
          <View className="flex-row items-center gap-2">
            {totalResults > 0 && (
              <View className="rounded-full bg-white/10 px-2 py-0.5">
                <Text className="text-[10px] text-muted">
                  {totalResults} result{totalResults !== 1 ? "s" : ""}
                </Text>
              </View>
            )}
          </View>
        </View>

        {/* Query */}
        {!!data.query && (
          <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-2 mb-3">
            <Text className="text-xs text-muted mb-0.5">Query</Text>
            <Text className="text-sm text-foreground font-medium">
              "{data.query}"
            </Text>
          </View>
        )}

        {/* Answer snippet */}
        {!!data.answer && (
          <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-2 mb-3">
            <Text className="text-xs text-muted mb-0.5">Answer</Text>
            <Text className="text-sm text-foreground" numberOfLines={4}>
              {data.answer}
            </Text>
          </View>
        )}

        {/* Web results */}
        {allWebResults.length > 0 && (
          <View className="rounded-xl bg-white/5 border border-white/8 px-3 overflow-hidden">
            {allWebResults.map((result, index) => (
              <View
                key={result.url || result.title || String(index)}
                className={
                  index === allWebResults.length - 1 ? "border-b-0" : ""
                }
              >
                <WebResultRow result={result} />
              </View>
            ))}
          </View>
        )}

        {/* News results (only when expanded) */}
        {expanded && newsResults.length > 0 && (
          <View className="rounded-xl bg-white/5 border border-white/8 px-3 overflow-hidden mt-2">
            <View className="flex-row items-center gap-1.5 py-2 border-b border-white/8">
              <HugeiconsIcon icon={News01Icon} size={12} color="#8e8e93" />
              <Text className="text-[11px] text-muted font-medium">News</Text>
            </View>
            {newsResults.map((article, index) => (
              <View
                key={article.url || article.title || String(index)}
                className={index === newsResults.length - 1 ? "border-b-0" : ""}
              >
                <NewsResultRow article={article} />
              </View>
            ))}
          </View>
        )}

        {/* Expand / collapse */}
        {hasMore && (
          <Pressable
            onPress={() => setExpanded((prev) => !prev)}
            className="mt-2.5 py-1.5 items-center active:opacity-70"
          >
            <Text className="text-xs text-[#00bbff] font-medium">
              {expanded
                ? "Show less"
                : `Show all ${totalResults} result${totalResults !== 1 ? "s" : ""}`}
            </Text>
          </Pressable>
        )}
      </Card.Body>
    </Card>
  );
}
