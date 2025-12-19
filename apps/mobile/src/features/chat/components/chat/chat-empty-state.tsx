import { Image, ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import type { Suggestion } from "../../types";
import { SuggestionCard } from "./suggestion-card";

interface ChatEmptyStateProps {
  suggestions: Suggestion[];
  onSuggestionPress: (text: string) => void;
}

export function ChatEmptyState({
  suggestions,
  onSuggestionPress,
}: ChatEmptyStateProps) {
  return (
    <ScrollView
      className="flex-1"
      contentContainerStyle={{
        flexGrow: 1,
        paddingHorizontal: 24,
        paddingTop: 64,
        paddingBottom: 32,
      }}
      showsVerticalScrollIndicator={false}
    >
      <View className="items-center mb-12">
        <View className="mb-8">
          <Image
            source={require("@/assets/logo/logo.webp")}
            className="w-16 h-16 opacity-90"
            resizeMode="contain"
          />
        </View>
        <Text className="text-3xl font-bold tracking-tight text-foreground text-center mb-2 px-6">
          Hello there! How can I support you today?
        </Text>
        <Text className="text-base text-muted-foreground/60 text-center px-10">
          Your space for clarity. What's on your mind?
        </Text>
      </View>

      <View className="w-full">
        <Text className="text-base font-medium text-muted-foreground mb-4">
          Suggestions
        </Text>
        <View className="flex-row flex-wrap gap-2 justify-between">
          {suggestions.map((suggestion, index) => (
            <SuggestionCard
              key={suggestion.id}
              suggestion={suggestion}
              index={index}
              onPress={onSuggestionPress}
            />
          ))}
        </View>
      </View>
    </ScrollView>
  );
}
