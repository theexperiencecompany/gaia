import {
  Card,
  Chip,
  ListGroup,
  PressableFeedback,
  Separator,
} from "heroui-native";
import { useEffect, useState } from "react";
import { Image, Linking, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
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
  /** Streaming status — present only during live updates */
  status?: "running" | "complete" | "error";
  progress?: string;

  web?: WebResult[];
  images?: string[];
  news?: NewsResult[];
  answer?: string;
  query?: string;
  response_time?: number;
  request_id?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getHostname(url?: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function FaviconImage({ url }: { url?: string }) {
  const [errored, setErrored] = useState(false);
  const hostname = getHostname(url);

  if (!hostname || errored) {
    return (
      <View className="w-4 h-4 rounded-full bg-white/10 items-center justify-center">
        <AppIcon icon={Globe02Icon} size={10} color="#8e8e93" />
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

function WebResultItem({ result }: { result: WebResult }) {
  const hostname = getHostname(result.url);
  const description = result.content || result.snippet;

  return (
    <PressableFeedback
      onPress={() => result.url && Linking.openURL(result.url)}
    >
      <ListGroup.Item>
        <ListGroup.ItemIcon>
          <FaviconImage url={result.url} />
        </ListGroup.ItemIcon>
        <View className="flex-1 gap-0.5">
          <ListGroup.ItemText numberOfLines={2}>
            {result.title || hostname || "Untitled"}
          </ListGroup.ItemText>
          {!!description && (
            <ListGroup.ItemDescription numberOfLines={2}>
              {description}
            </ListGroup.ItemDescription>
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
      </ListGroup.Item>
    </PressableFeedback>
  );
}

function NewsResultItem({ article }: { article: NewsResult }) {
  const hostname = getHostname(article.url);
  const description = article.content;

  return (
    <PressableFeedback
      onPress={() => article.url && Linking.openURL(article.url)}
    >
      <ListGroup.Item>
        <ListGroup.ItemIcon>
          <FaviconImage url={article.url} />
        </ListGroup.ItemIcon>
        <View className="flex-1 gap-0.5">
          <ListGroup.ItemText numberOfLines={2}>
            {article.title || "Untitled"}
          </ListGroup.ItemText>
          {!!description && (
            <ListGroup.ItemDescription numberOfLines={2}>
              {description}
            </ListGroup.ItemDescription>
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
      </ListGroup.Item>
    </PressableFeedback>
  );
}

// ---------------------------------------------------------------------------
// Running / streaming state
// ---------------------------------------------------------------------------

function PulsingDot() {
  const opacity = useSharedValue(1);

  useEffect(() => {
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.25, { duration: 600 }),
        withTiming(1, { duration: 600 }),
      ),
      -1,
      false,
    );
  }, [opacity]);

  const animatedStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <Animated.View
      style={[
        animatedStyle,
        { width: 6, height: 6, borderRadius: 3, backgroundColor: "#00bbff" },
      ]}
    />
  );
}

function SearchRunningCard({ data }: { data: SearchResults }) {
  const queryText = data.query;
  const progressText = data.progress ?? "Searching the web...";

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center gap-2 mb-3">
          <View className="w-5 h-5 rounded-md bg-[#00bbff]/15 items-center justify-center">
            <AppIcon icon={Search01Icon} size={12} color="#00bbff" />
          </View>
          <Text className="text-xs font-medium text-[#00bbff]">Web Search</Text>
          <View className="ml-auto">
            <PulsingDot />
          </View>
        </View>

        {/* Query */}
        {!!queryText && (
          <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-2 mb-3">
            <Text className="text-xs text-muted mb-0.5">Query</Text>
            <Text className="text-sm text-foreground font-medium">
              "{queryText}"
            </Text>
          </View>
        )}

        {/* Progress */}
        <Text className="text-xs text-muted">{progressText}</Text>
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Complete state
// ---------------------------------------------------------------------------

function SearchCompleteCard({ data }: { data: SearchResults }) {
  const [expanded, setExpanded] = useState(false);
  const webResults = data.web ?? [];
  const newsResults = data.news ?? [];
  const totalResults = webResults.length + newsResults.length;

  // Show up to 5 web results before collapsing
  const MAX_VISIBLE = 5;
  const visibleWebResults = expanded
    ? webResults
    : webResults.slice(0, MAX_VISIBLE);
  const hasMore = webResults.length > MAX_VISIBLE || newsResults.length > 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Search01Icon} size={14} color="#8e8e93" />
            <Text className="text-xs text-muted">Search Results</Text>
          </View>
          <View className="flex-row items-center gap-2">
            {totalResults > 0 && (
              <Chip
                size="sm"
                variant="secondary"
                color="default"
                animation="disable-all"
              >
                <Chip.Label>
                  {totalResults} result{totalResults !== 1 ? "s" : ""}
                </Chip.Label>
              </Chip>
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
        {visibleWebResults.length > 0 && (
          <ListGroup className="rounded-xl bg-white/5 border border-white/8 overflow-hidden">
            {visibleWebResults.map((result, index) => (
              <View key={result.url || result.title || String(index)}>
                {index > 0 && <Separator />}
                <WebResultItem result={result} />
              </View>
            ))}
          </ListGroup>
        )}

        {/* News results (only when expanded) */}
        {expanded && newsResults.length > 0 && (
          <ListGroup className="rounded-xl bg-white/5 border border-white/8 overflow-hidden mt-2">
            <View className="flex-row items-center gap-1.5 py-2 px-3 border-b border-white/8">
              <AppIcon icon={News01Icon} size={12} color="#8e8e93" />
              <Text className="text-[11px] text-muted font-medium">News</Text>
            </View>
            {newsResults.map((article, index) => (
              <View key={article.url || article.title || String(index)}>
                {index > 0 && <Separator />}
                <NewsResultItem article={article} />
              </View>
            ))}
          </ListGroup>
        )}

        {/* Expand / collapse */}
        {hasMore && (
          <PressableFeedback
            onPress={() => setExpanded((prev) => !prev)}
            className="mt-2.5 py-1.5 items-center"
          >
            <Text className="text-xs text-[#00bbff] font-medium">
              {expanded
                ? "Show less"
                : `Show all ${totalResults} result${totalResults !== 1 ? "s" : ""}`}
            </Text>
          </PressableFeedback>
        )}
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main export — routes to running or complete sub-component
// ---------------------------------------------------------------------------

export function SearchResultsCard({ data }: { data: SearchResults }) {
  if (data.status === "running") {
    return <SearchRunningCard data={data} />;
  }
  return <SearchCompleteCard data={data} />;
}
