import type {
  ImageResult,
  NewsResult,
  SearchResults,
  WebResult,
} from "@gaia/shared";
import { useEffect, useState } from "react";
import { Image, Linking, Pressable, ScrollView, View } from "react-native";
import Animated, {
  FadeInRight,
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
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

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

type Tab = "web" | "images" | "news";

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function FaviconImage({ url }: { url?: string }) {
  const [errored, setErrored] = useState(false);
  const hostname = getHostname(url);

  if (!hostname || errored) {
    return (
      <View className="w-4 h-4 rounded-full bg-zinc-700 items-center justify-center">
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

function WebResultRow({ result }: { result: WebResult }) {
  const hostname = getHostname(result.url);
  const description = result.content || result.snippet;

  return (
    <ToolCardInner
      dense
      onPress={() => result.url && Linking.openURL(result.url)}
    >
      <View className="flex-row items-start gap-2.5">
        <View style={{ marginTop: 2 }}>
          <FaviconImage url={result.url} />
        </View>
        <View className="flex-1 gap-0.5">
          {!!hostname && (
            <Text className="text-zinc-500 text-xs" numberOfLines={1}>
              {hostname}
            </Text>
          )}
          <Text className="text-primary text-sm font-medium" numberOfLines={2}>
            {result.title || hostname || "Untitled"}
          </Text>
          {!!description && (
            <Text className="text-zinc-400 text-xs" numberOfLines={3}>
              {description}
            </Text>
          )}
        </View>
      </View>
    </ToolCardInner>
  );
}

function NewsResultRow({ article }: { article: NewsResult }) {
  const description = article.content;

  return (
    <ToolCardInner
      dense
      onPress={() => article.url && Linking.openURL(article.url)}
    >
      <View className="flex-row items-start gap-2.5">
        <View
          className="w-4 h-4 rounded-full bg-zinc-700 items-center justify-center"
          style={{ marginTop: 2 }}
        >
          <AppIcon icon={News01Icon} size={10} color="#8e8e93" />
        </View>
        <View className="flex-1 gap-0.5">
          {!!article.published_date && (
            <Text className="text-zinc-500 text-xs" numberOfLines={1}>
              {article.published_date}
            </Text>
          )}
          <Text className="text-primary text-sm font-medium" numberOfLines={2}>
            {article.title || "Untitled"}
          </Text>
          {!!description && (
            <Text className="text-zinc-400 text-xs" numberOfLines={3}>
              {description}
            </Text>
          )}
        </View>
      </View>
    </ToolCardInner>
  );
}

function ImageTile({ image, index }: { image: ImageResult; index: number }) {
  const url = typeof image === "string" ? image : undefined;

  if (!url) return null;

  return (
    <Animated.View entering={FadeInRight.delay(index * 40).duration(280)}>
      <Pressable onPress={() => Linking.openURL(url)}>
        <Image
          source={{ uri: url }}
          style={{ width: 128, height: 96, borderRadius: 12 }}
          resizeMode="cover"
        />
      </Pressable>
    </Animated.View>
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
    <ToolCardShell>
      <ToolCardHeader
        icon={Search01Icon}
        title="Web Search"
        trailing={<PulsingDot />}
      />
      {!!queryText && (
        <ToolCardInner dense className="mb-2">
          <Text className="text-zinc-500 text-xs mb-0.5">Query</Text>
          <Text className="text-zinc-100 text-sm font-medium">
            &quot;{queryText}&quot;
          </Text>
        </ToolCardInner>
      )}
      <Text className="text-zinc-400 text-xs">{progressText}</Text>
    </ToolCardShell>
  );
}

// ---------------------------------------------------------------------------
// Tab chips
// ---------------------------------------------------------------------------

function TabChips({
  tabs,
  active,
  onSelect,
}: {
  tabs: Tab[];
  active: Tab;
  onSelect: (tab: Tab) => void;
}) {
  return (
    <View className="flex-row gap-2 mb-3">
      {tabs.map((tab) => {
        const isActive = tab === active;
        return (
          <Pressable
            key={tab}
            onPress={() => onSelect(tab)}
            className={`px-3 py-1.5 rounded-full ${
              isActive ? "bg-primary" : "bg-zinc-700"
            }`}
          >
            <Text
              className={`text-xs font-medium ${
                isActive ? "text-black" : "text-zinc-300"
              }`}
            >
              {capitalize(tab)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Complete state
// ---------------------------------------------------------------------------

function SearchCompleteCard({ data }: { data: SearchResults }) {
  const webResults = data.web ?? [];
  const imageResults = data.images ?? [];
  const newsResults = data.news ?? [];

  const hasImages = imageResults.length > 0;
  const hasNews = newsResults.length > 0;

  const tabs: Tab[] = [
    "web",
    ...(hasImages ? (["images"] as Tab[]) : []),
    ...(hasNews ? (["news"] as Tab[]) : []),
  ];

  const [active, setActive] = useState<Tab>("web");

  const totalResults =
    webResults.length + imageResults.length + newsResults.length;

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Search01Icon}
        title="Search Results"
        count={totalResults > 0 ? totalResults : undefined}
      />

      {!!data.query && (
        <ToolCardInner dense className="mb-3">
          <Text className="text-zinc-500 text-xs mb-0.5">Query</Text>
          <Text className="text-zinc-100 text-sm font-medium">
            &quot;{data.query}&quot;
          </Text>
        </ToolCardInner>
      )}

      {!!data.answer && (
        <ToolCardInner dense className="mb-3">
          <Text className="text-zinc-500 text-xs mb-0.5">Answer</Text>
          <Text className="text-zinc-100 text-sm" numberOfLines={4}>
            {data.answer}
          </Text>
        </ToolCardInner>
      )}

      {tabs.length > 1 && (
        <TabChips tabs={tabs} active={active} onSelect={setActive} />
      )}

      {active === "web" && webResults.length > 0 && (
        <View className="gap-1.5">
          {webResults.map((result, index) => (
            <WebResultRow
              key={result.url || result.title || String(index)}
              result={result}
            />
          ))}
        </View>
      )}

      {active === "images" && hasImages && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: 8, paddingVertical: 4 }}
        >
          {imageResults.map((img, index) => (
            <ImageTile
              key={typeof img === "string" ? img : String(index)}
              image={img}
              index={index}
            />
          ))}
        </ScrollView>
      )}

      {active === "news" && hasNews && (
        <View className="gap-1.5">
          {newsResults.map((article, index) => (
            <NewsResultRow
              key={article.url || article.title || String(index)}
              article={article}
            />
          ))}
        </View>
      )}
    </ToolCardShell>
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
