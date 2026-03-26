import { Skeleton, Surface } from "heroui-native";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
import Animated, {
  FadeIn,
  FadeOut,
  LinearTransition,
} from "react-native-reanimated";
import { AppIcon, File01Icon, Image01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

export interface AttachmentFile {
  /** Unique local identifier before upload completes */
  localId: string;
  uri: string;
  name: string;
  mimeType: string;
  size?: number;
  /** Populated once upload completes */
  fileId?: string;
  fileUrl?: string;
  isUploading: boolean;
  error?: string;
}

interface AttachmentChipProps {
  attachment: AttachmentFile;
  onRemove: (localId: string) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function AttachmentChip({ attachment, onRemove }: AttachmentChipProps) {
  const { spacing, fontSize, iconSize } = useResponsive();
  const isImage = attachment.mimeType.startsWith("image/");

  return (
    <Animated.View
      entering={FadeIn.duration(200)}
      exiting={FadeOut.duration(150)}
      layout={LinearTransition.springify()}
    >
      <Surface
        style={{
          flexDirection: "row",
          alignItems: "center",
          backgroundColor: "#3f3f46",
          borderRadius: 10,
          paddingLeft: spacing.sm,
          paddingRight: spacing.xs,
          paddingVertical: spacing.xs,
          gap: spacing.xs,
          maxWidth: 200,
        }}
      >
        <Skeleton
          isLoading={attachment.isUploading}
          style={{
            width: iconSize.sm,
            height: iconSize.sm,
            borderRadius: iconSize.sm / 2,
          }}
        >
          {attachment.isUploading ? (
            <ActivityIndicator size="small" color="#a1a1aa" />
          ) : (
            <AppIcon
              icon={isImage ? Image01Icon : File01Icon}
              size={iconSize.sm}
              color={attachment.error ? "#ef4444" : "#a1a1aa"}
            />
          )}
        </Skeleton>

        <View style={{ flex: 1, minWidth: 0 }}>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: attachment.error ? "#ef4444" : "#e4e4e7",
              fontWeight: "400",
            }}
            numberOfLines={1}
          >
            {attachment.name}
          </Text>
          {attachment.size !== undefined && !attachment.error && (
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                color: "#71717a",
              }}
              numberOfLines={1}
            >
              {formatSize(attachment.size)}
            </Text>
          )}
          {attachment.error && (
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                color: "#ef4444",
              }}
              numberOfLines={1}
            >
              {attachment.error}
            </Text>
          )}
        </View>

        <Pressable onPress={() => onRemove(attachment.localId)} hitSlop={8}>
          <AppIcon icon={File01Icon} size={12} color="#a1a1aa" />
        </Pressable>
      </Surface>
    </Animated.View>
  );
}

interface AttachmentPreviewProps {
  attachments: AttachmentFile[];
  onRemove: (localId: string) => void;
}

export function AttachmentPreview({
  attachments,
  onRemove,
}: AttachmentPreviewProps) {
  const { spacing } = useResponsive();

  if (attachments.length === 0) return null;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={{
        paddingHorizontal: spacing.sm + 2,
        paddingTop: spacing.sm,
        gap: spacing.xs,
      }}
      keyboardShouldPersistTaps="handled"
    >
      {attachments.map((attachment) => (
        <AttachmentChip
          key={attachment.localId}
          attachment={attachment}
          onRemove={onRemove}
        />
      ))}
    </ScrollView>
  );
}
