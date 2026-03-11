import { useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  Cancel01Icon,
  Clock01Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type {
  SearchConversationResult,
  SearchMessageResult,
} from "../api/search-api";
import { useSearch } from "../hooks/use-search";
import { SearchResultItem } from "./SearchResultItem";

const RECENT_SEARCHES_KEY = "gaia_recent_searches";
const MAX_RECENT_SEARCHES = 8;

async function loadRecentSearches(): Promise<string[]> {
  try {
    const stored = await SecureStore.getItemAsync(RECENT_SEARCHES_KEY);
    if (!stored) return [];
    return JSON.parse(stored) as string[];
  } catch {
    return [];
  }
}

async function saveRecentSearches(searches: string[]): Promise<void> {
  try {
    await SecureStore.setItemAsync(
      RECENT_SEARCHES_KEY,
      JSON.stringify(searches),
    );
  } catch {
    // silently fail
  }
}

async function addRecentSearch(
  query: string,
  current: string[],
): Promise<string[]> {
  const trimmed = query.trim();
  if (!trimmed) return current;
  const filtered = current.filter((s) => s !== trimmed);
  const next = [trimmed, ...filtered].slice(0, MAX_RECENT_SEARCHES);
  await saveRecentSearches(next);
  return next;
}

type SearchSection = "conversations" | "messages";

interface SectionHeaderProps {
  title: string;
  count: number;
}

function SectionHeader({ title, count }: SectionHeaderProps) {
  const { spacing, fontSize } = useResponsive();
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.md,
        paddingTop: spacing.md,
        paddingBottom: spacing.sm,
        gap: spacing.xs,
      }}
    >
      <Text
        style={{
          fontSize: fontSize.xs,
          fontWeight: "700",
          color: "#52525b",
          textTransform: "uppercase",
          letterSpacing: 0.8,
        }}
      >
        {title}
      </Text>
      <View
        style={{
          backgroundColor: "rgba(255,255,255,0.08)",
          borderRadius: 999,
          paddingHorizontal: 6,
          paddingVertical: 1,
        }}
      >
        <Text
          style={{
            fontSize: fontSize.xs - 1,
            color: "#71717a",
            fontWeight: "600",
          }}
        >
          {count}
        </Text>
      </View>
    </View>
  );
}

function LoadingSkeleton() {
  const { spacing } = useResponsive();
  return (
    <View style={{ paddingTop: spacing.sm }}>
      {[1, 2, 3, 4].map((i) => (
        <View
          key={i}
          style={{
            flexDirection: "row",
            alignItems: "flex-start",
            gap: spacing.sm,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm + 2,
          }}
        >
          <View
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              backgroundColor: "rgba(255,255,255,0.06)",
            }}
          />
          <View style={{ flex: 1, gap: 8 }}>
            <View
              style={{
                height: 14,
                borderRadius: 4,
                backgroundColor: "rgba(255,255,255,0.06)",
                width: `${60 + (i % 3) * 15}%`,
              }}
            />
            <View
              style={{
                height: 12,
                borderRadius: 4,
                backgroundColor: "rgba(255,255,255,0.04)",
                width: `${80 + (i % 2) * 10}%`,
              }}
            />
          </View>
        </View>
      ))}
    </View>
  );
}

export function SearchScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize, iconSize } = useResponsive();
  const inputRef = useRef<TextInput>(null);

  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [activeSection, setActiveSection] = useState<SearchSection | null>(
    null,
  );

  const { query, setQuery, debouncedQuery, results, isLoading, isDebouncing } =
    useSearch();

  useEffect(() => {
    void loadRecentSearches().then(setRecentSearches);
    // Focus the input on mount
    const timer = setTimeout(() => {
      inputRef.current?.focus();
    }, 100);
    return () => clearTimeout(timer);
  }, []);

  const handleResultPress = useCallback(
    async (conversationId: string) => {
      if (query.trim()) {
        const updated = await addRecentSearch(query, recentSearches);
        setRecentSearches(updated);
      }
      router.push(`/c/${conversationId}`);
    },
    [query, recentSearches, router],
  );

  const handleRecentSearchPress = useCallback(
    (recentQuery: string) => {
      setQuery(recentQuery);
    },
    [setQuery],
  );

  const handleRemoveRecentSearch = useCallback(
    async (searchToRemove: string) => {
      const next = recentSearches.filter((s) => s !== searchToRemove);
      setRecentSearches(next);
      await saveRecentSearches(next);
    },
    [recentSearches],
  );

  const handleClearAll = useCallback(async () => {
    setRecentSearches([]);
    await saveRecentSearches([]);
  }, []);

  const conversations: SearchConversationResult[] =
    results?.conversations ?? [];
  const messages: SearchMessageResult[] = results?.messages ?? [];
  const hasResults = conversations.length > 0 || messages.length > 0;
  const showEmptyState =
    debouncedQuery.length >= 2 && !isLoading && !isDebouncing && !hasResults;
  const showRecentSearches = !query && recentSearches.length > 0;
  const showSearchTips = !query && recentSearches.length === 0;

  const filteredConversations =
    activeSection === "messages" ? [] : conversations;
  const filteredMessages = activeSection === "conversations" ? [] : messages;

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: "#131416",
        paddingTop: insets.top,
      }}
    >
      {/* Search bar header */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.07)",
        }}
      >
        {/* Back button */}
        <Pressable
          onPress={() => router.back()}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
            flexShrink: 0,
          }}
          hitSlop={8}
        >
          <AppIcon icon={ArrowLeft01Icon} size={iconSize.sm} color="#fff" />
        </Pressable>

        {/* Input container */}
        <View
          style={{
            flex: 1,
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            backgroundColor: "#18181b",
            borderRadius: 12,
            paddingHorizontal: spacing.sm,
            paddingVertical: 10,
            borderWidth: 1,
            borderColor: query ? "rgba(0,187,255,0.3)" : "#27272a",
          }}
        >
          <AppIcon icon={Search01Icon} size={16} color="#52525b" />
          <TextInput
            ref={inputRef}
            value={query}
            onChangeText={setQuery}
            placeholder="Search conversations and messages..."
            placeholderTextColor="#52525b"
            style={{
              flex: 1,
              fontSize: fontSize.sm,
              color: "#f4f4f5",
              padding: 0,
            }}
            returnKeyType="search"
            autoCapitalize="none"
            autoCorrect={false}
            onSubmitEditing={async () => {
              if (query.trim() && debouncedQuery) {
                const updated = await addRecentSearch(query, recentSearches);
                setRecentSearches(updated);
              }
            }}
          />
          {query ? (
            <Pressable onPress={() => setQuery("")} hitSlop={8}>
              <AppIcon icon={Cancel01Icon} size={14} color="#52525b" />
            </Pressable>
          ) : null}
        </View>

        {/* Loading indicator */}
        {(isLoading || isDebouncing) && query ? (
          <ActivityIndicator size="small" color="#00bbff" />
        ) : null}
      </View>

      {/* Section filter pills - shown when there are results */}
      {hasResults && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{
            flexDirection: "row",
            gap: spacing.xs,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm,
          }}
        >
          {(
            [
              { key: null, label: "All" },
              { key: "conversations" as SearchSection, label: "Conversations" },
              { key: "messages" as SearchSection, label: "Messages" },
            ] as Array<{ key: SearchSection | null; label: string }>
          ).map(({ key, label }) => (
            <Pressable
              key={label}
              onPress={() => setActiveSection(key)}
              style={{
                paddingHorizontal: spacing.sm,
                paddingVertical: 5,
                borderRadius: 999,
                backgroundColor:
                  activeSection === key
                    ? "rgba(0,187,255,0.15)"
                    : "rgba(255,255,255,0.06)",
                borderWidth: 1,
                borderColor:
                  activeSection === key ? "rgba(0,187,255,0.4)" : "transparent",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs + 1,
                  fontWeight: "500",
                  color: activeSection === key ? "#00bbff" : "#8e8e93",
                }}
              >
                {label}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
      )}

      {/* Content */}
      {isLoading && !results ? (
        <LoadingSkeleton />
      ) : (
        <FlatList
          data={[]}
          renderItem={null}
          keyboardShouldPersistTaps="handled"
          ListHeaderComponent={
            <>
              {/* Recent searches */}
              {showRecentSearches && (
                <View>
                  <View
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      justifyContent: "space-between",
                      paddingHorizontal: spacing.md,
                      paddingTop: spacing.md,
                      paddingBottom: spacing.sm,
                    }}
                  >
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        fontWeight: "700",
                        color: "#52525b",
                        textTransform: "uppercase",
                        letterSpacing: 0.8,
                      }}
                    >
                      Recent
                    </Text>
                    <Pressable onPress={() => void handleClearAll()}>
                      <Text style={{ fontSize: fontSize.xs, color: "#00bbff" }}>
                        Clear all
                      </Text>
                    </Pressable>
                  </View>
                  {recentSearches.map((recentSearch) => (
                    <Pressable
                      key={recentSearch}
                      onPress={() => handleRecentSearchPress(recentSearch)}
                      style={({ pressed }) => ({
                        flexDirection: "row",
                        alignItems: "center",
                        gap: spacing.sm,
                        paddingHorizontal: spacing.md,
                        paddingVertical: spacing.sm,
                        backgroundColor: pressed
                          ? "rgba(255,255,255,0.04)"
                          : "transparent",
                      })}
                    >
                      <AppIcon
                        icon={Clock01Icon}
                        size={iconSize.sm}
                        color="#3f3f46"
                      />
                      <Text
                        style={{
                          flex: 1,
                          fontSize: fontSize.sm,
                          color: "#a1a1aa",
                        }}
                      >
                        {recentSearch}
                      </Text>
                      <Pressable
                        onPress={() =>
                          void handleRemoveRecentSearch(recentSearch)
                        }
                        hitSlop={8}
                      >
                        <AppIcon
                          icon={Cancel01Icon}
                          size={14}
                          color="#3f3f46"
                        />
                      </Pressable>
                    </Pressable>
                  ))}
                </View>
              )}

              {/* Search tips (no query, no recent) */}
              {showSearchTips && (
                <View
                  style={{
                    paddingTop: spacing.xl * 2,
                    paddingHorizontal: spacing.xl,
                    alignItems: "center",
                    gap: spacing.md,
                  }}
                >
                  <View
                    style={{
                      width: 64,
                      height: 64,
                      borderRadius: 999,
                      backgroundColor: "rgba(0,187,255,0.08)",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <AppIcon
                      icon={Search01Icon}
                      size={iconSize.lg}
                      color="#00bbff"
                    />
                  </View>
                  <Text
                    style={{
                      fontSize: fontSize.base,
                      fontWeight: "600",
                      color: "#f4f4f5",
                      textAlign: "center",
                    }}
                  >
                    Search your conversations
                  </Text>
                  <View style={{ gap: spacing.xs }}>
                    {[
                      "Search by keyword or phrase",
                      "Find specific messages in any chat",
                      "Browse conversations by topic",
                    ].map((tip) => (
                      <Text
                        key={tip}
                        style={{
                          fontSize: fontSize.sm,
                          color: "#52525b",
                          textAlign: "center",
                        }}
                      >
                        {tip}
                      </Text>
                    ))}
                  </View>
                </View>
              )}

              {/* Conversation results */}
              {filteredConversations.length > 0 && (
                <>
                  <SectionHeader
                    title="Conversations"
                    count={filteredConversations.length}
                  />
                  {filteredConversations.map((conv) => (
                    <SearchResultItem
                      key={conv.conversation_id}
                      conversationId={conv.conversation_id}
                      title={conv.description || "Untitled conversation"}
                      snippet=""
                      query={debouncedQuery}
                      type="conversation"
                      onPress={(id) => void handleResultPress(id)}
                    />
                  ))}
                </>
              )}

              {/* Message results */}
              {filteredMessages.length > 0 && (
                <>
                  <SectionHeader
                    title="Messages"
                    count={filteredMessages.length}
                  />
                  {filteredMessages.map((msg) => (
                    <SearchResultItem
                      key={msg.message.message_id}
                      conversationId={msg.conversation_id}
                      title={msg.conversation_id}
                      snippet={msg.snippet}
                      query={debouncedQuery}
                      type="message"
                      timestamp={msg.message.date}
                      onPress={(id) => void handleResultPress(id)}
                    />
                  ))}
                </>
              )}

              {/* Empty state */}
              {showEmptyState && (
                <View
                  style={{
                    paddingTop: spacing.xl * 2,
                    paddingHorizontal: spacing.xl,
                    alignItems: "center",
                    gap: spacing.md,
                  }}
                >
                  <View
                    style={{
                      width: 64,
                      height: 64,
                      borderRadius: 999,
                      backgroundColor: "rgba(255,255,255,0.04)",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <AppIcon
                      icon={Search01Icon}
                      size={iconSize.lg}
                      color="#3f3f46"
                    />
                  </View>
                  <Text
                    style={{
                      fontSize: fontSize.base,
                      fontWeight: "600",
                      color: "#71717a",
                      textAlign: "center",
                    }}
                  >
                    No results for &quot;{debouncedQuery}&quot;
                  </Text>
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      color: "#52525b",
                      textAlign: "center",
                    }}
                  >
                    Try a different keyword or check your spelling
                  </Text>
                </View>
              )}
            </>
          }
        />
      )}
    </View>
  );
}
