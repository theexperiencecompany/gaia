import { Image } from "expo-image";
import { Button, Card, PressableFeedback, Skeleton } from "heroui-native";
import { useCallback, useState } from "react";
import { Platform, Share, View } from "react-native";
import { Share01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { ImageData } from "../../api/chat-api";
import { ImageViewerModal } from "./image-viewer-modal";

interface ImageGenerationCardProps {
  imageData: ImageData;
  isGenerating?: boolean;
  caption?: string;
}

export function ImageGenerationCard({
  imageData,
  isGenerating = false,
  caption,
}: ImageGenerationCardProps) {
  const [viewerVisible, setViewerVisible] = useState(false);
  const { width, spacing, moderateScale, fontSize } = useResponsive();

  const cardWidth = Math.min(width * 0.78, 360);
  const isLoading = isGenerating || !imageData.url;

  const handlePress = useCallback(() => {
    if (imageData.url) {
      setViewerVisible(true);
    }
  }, [imageData.url]);

  const handleShare = useCallback(async () => {
    if (!imageData.url) return;
    try {
      if (Platform.OS === "ios") {
        await Share.share({ url: imageData.url, message: imageData.url });
      } else {
        await Share.share({ message: imageData.url });
      }
    } catch {
      // User cancelled or share failed silently
    }
  }, [imageData.url]);

  if (!imageData.url && !isGenerating) return null;

  const prompt = imageData.prompt?.trim();
  const improvedPrompt = imageData.improvedPrompt?.trim();

  return (
    <>
      <Card
        variant="secondary"
        animation="disable-all"
        style={{ width: cardWidth, overflow: "hidden" }}
        className="rounded-[20px] border border-white/[0.07] bg-[#18181b]"
      >
        <Card.Body className="p-0">
          {/* Image / skeleton area */}
          <Skeleton
            isLoading={isLoading}
            style={{ width: cardWidth, aspectRatio: 1 }}
            className="rounded-none"
          >
            <PressableFeedback onPress={handlePress}>
              <Image
                source={{ uri: imageData.url }}
                style={{ width: cardWidth, aspectRatio: 1 }}
                contentFit="cover"
                transition={400}
                placeholder={{ blurhash: "L6PZfSi_.AyE_3t7t7R**0o#DgR4" }}
              />
            </PressableFeedback>
          </Skeleton>

          {/* Footer */}
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
                  fontStyle: "italic",
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

            {/* Share button */}
            {!isLoading ? (
              <View
                style={{
                  flexDirection: "row",
                  gap: spacing.sm,
                  marginTop: spacing.xs,
                }}
              >
                <Button
                  size="sm"
                  variant="ghost"
                  onPress={() => void handleShare()}
                  animation="disable-all"
                  className="rounded-xl bg-white/[0.06] border border-white/[0.08] px-3 py-1.5"
                >
                  <Share01Icon size={moderateScale(13, 0.5)} color="#a1a1aa" />
                  <Button.Label
                    style={{ fontSize: fontSize.xs, color: "#a1a1aa" }}
                  >
                    Share
                  </Button.Label>
                </Button>
              </View>
            ) : null}
          </View>

          {/* Improved prompt row */}
          {improvedPrompt && !isLoading ? (
            <ImprovedPromptRow
              improvedPrompt={improvedPrompt}
              spacing={spacing}
              fontSize={fontSize}
            />
          ) : null}
        </Card.Body>
      </Card>

      <ImageViewerModal
        isVisible={viewerVisible}
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
    <PressableFeedback
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
    </PressableFeedback>
  );
}
