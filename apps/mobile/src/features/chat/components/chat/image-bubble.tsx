import { Image } from "expo-image";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { ImageData } from "../../api/chat-api";
import { ImageViewerModal } from "./image-viewer-modal";

interface ImageBubbleProps {
  imageData: ImageData;
  isGenerating?: boolean;
  caption?: string;
}

function ShimmerPlaceholder({ width }: { width: number }) {
  const opacity = useSharedValue(0.3);

  opacity.value = withRepeat(
    withSequence(
      withTiming(0.8, { duration: 900 }),
      withTiming(0.3, { duration: 900 }),
    ),
    -1,
    false,
  );

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <Animated.View
      style={[
        {
          width,
          aspectRatio: 1,
          borderRadius: 20,
          backgroundColor: "#27272a",
        },
        animatedStyle,
      ]}
    />
  );
}

export function ImageBubble({
  imageData,
  isGenerating = false,
  caption,
}: ImageBubbleProps) {
  const [viewerVisible, setViewerVisible] = useState(false);
  const { width, spacing, moderateScale, fontSize } = useResponsive();

  const cardWidth = Math.min(width * 0.78, 360);
  const isLoading = isGenerating || !imageData.url;

  const handlePress = useCallback(() => {
    if (imageData.url) {
      setViewerVisible(true);
    }
  }, [imageData.url]);

  if (!imageData.url && !isGenerating) return null;

  const prompt = imageData.prompt?.trim();
  const improvedPrompt = imageData.improvedPrompt?.trim();

  return (
    <>
      <View
        style={{
          backgroundColor: "#18181b",
          borderRadius: moderateScale(20, 0.5),
          borderWidth: 1,
          borderColor: "rgba(255,255,255,0.07)",
          overflow: "hidden",
          width: cardWidth,
        }}
      >
        {/* Image / shimmer area */}
        {isLoading ? (
          <View style={{ padding: spacing.sm }}>
            <ShimmerPlaceholder width={cardWidth - spacing.sm * 2} />
          </View>
        ) : (
          <Pressable onPress={handlePress}>
            <Image
              source={{ uri: imageData.url }}
              style={{
                width: cardWidth,
                aspectRatio: 1,
              }}
              contentFit="cover"
              transition={400}
            />
          </Pressable>
        )}

        {/* Prompt / caption footer */}
        {prompt || caption ? (
          <View
            style={{
              paddingHorizontal: spacing.md,
              paddingTop: spacing.sm,
              paddingBottom: spacing.md,
              gap: spacing.xs,
            }}
          >
            {isLoading ? (
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#71717a",
                  fontStyle: "italic",
                }}
              >
                Generating image...
              </Text>
            ) : null}

            {prompt ? (
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#a1a1aa",
                  lineHeight: 18,
                }}
                numberOfLines={2}
              >
                {prompt}
              </Text>
            ) : null}

            {caption?.trim() ? (
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#ffffff",
                  lineHeight: 20,
                }}
              >
                {caption}
              </Text>
            ) : null}
          </View>
        ) : isLoading ? (
          <View
            style={{
              paddingHorizontal: spacing.md,
              paddingBottom: spacing.md,
              paddingTop: spacing.sm,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#71717a",
                fontStyle: "italic",
              }}
            >
              Generating image...
            </Text>
          </View>
        ) : null}

        {/* Improved prompt — collapsible */}
        {improvedPrompt && !isLoading ? (
          <ImprovedPromptRow
            improvedPrompt={improvedPrompt}
            spacing={spacing}
            fontSize={fontSize}
          />
        ) : null}
      </View>

      <ImageViewerModal
        visible={viewerVisible}
        imageUrl={imageData.url}
        prompt={imageData.prompt}
        improvedPrompt={imageData.improvedPrompt}
        onClose={() => setViewerVisible(false)}
      />
    </>
  );
}

interface ImprovedPromptRowProps {
  improvedPrompt: string;
  spacing: ReturnType<typeof useResponsive>["spacing"];
  fontSize: ReturnType<typeof useResponsive>["fontSize"];
}

function ImprovedPromptRow({
  improvedPrompt,
  spacing,
  fontSize,
}: ImprovedPromptRowProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Pressable
      onPress={() => setExpanded((v) => !v)}
      style={{
        borderTopWidth: 1,
        borderTopColor: "rgba(255,255,255,0.06)",
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm,
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.xs,
      }}
    >
      <View style={{ flex: 1, gap: 2 }}>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#52525b",
            fontWeight: "600",
            letterSpacing: 0.3,
          }}
        >
          ENHANCED PROMPT {expanded ? "▲" : "▼"}
        </Text>
        {expanded ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#71717a",
              lineHeight: 16,
              marginTop: 2,
            }}
          >
            {improvedPrompt}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}
