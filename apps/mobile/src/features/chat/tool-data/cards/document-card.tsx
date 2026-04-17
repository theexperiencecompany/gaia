import { Chip } from "heroui-native";
import { Linking, Pressable, View } from "react-native";
import { AppIcon, Download02Icon, File01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

export interface DocumentData {
  filename?: string;
  url?: string;
  is_plain_text?: boolean;
  title?: string;
  metadata?: Record<string, unknown>;
  // Legacy fields
  content?: string;
  type?: string;
}

function getFileExtension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

type ExtColors = {
  variant: "primary" | "secondary" | "tertiary" | "soft";
  color: "accent" | "default" | "success" | "warning" | "danger";
};

function getExtensionChipProps(ext: string): ExtColors {
  switch (ext) {
    case "pdf":
      return { variant: "secondary", color: "danger" };
    case "doc":
    case "docx":
      return { variant: "primary", color: "accent" };
    case "xls":
    case "xlsx":
    case "csv":
      return { variant: "secondary", color: "success" };
    case "md":
      return { variant: "secondary", color: "warning" };
    default:
      return { variant: "secondary", color: "default" };
  }
}

export function DocumentCard({ data }: { data: DocumentData }) {
  const displayName = data.title || data.filename || "Untitled Document";
  const filename = data.filename || "";
  const ext = filename ? getFileExtension(filename) : (data.type ?? "");
  const chipProps = getExtensionChipProps(ext);
  const showFilename =
    data.title && data.filename && data.title !== data.filename;

  const handleDownload = () => {
    if (data.url) {
      Linking.openURL(data.url);
    }
  };

  return (
    <ToolCardShell>
      <ToolCardInner>
        <View className="flex-row items-center gap-3">
          {/* File icon */}
          <View className="w-10 h-10 rounded-xl bg-[#00bbff]/10 items-center justify-center flex-shrink-0">
            <AppIcon icon={File01Icon} size={20} color="#00bbff" />
          </View>

          {/* File info */}
          <View className="flex-1 min-w-0">
            <View className="flex-row items-center gap-2 flex-wrap">
              <Text
                className="text-sm font-medium text-zinc-200 flex-shrink-1"
                numberOfLines={1}
              >
                {displayName}
              </Text>
              {!!ext && (
                <Chip
                  size="sm"
                  variant={chipProps.variant}
                  color={chipProps.color}
                  animation="disable-all"
                >
                  <Chip.Label>{ext.toUpperCase()}</Chip.Label>
                </Chip>
              )}
            </View>
            {showFilename && (
              <Text className="text-xs text-zinc-400 mt-0.5" numberOfLines={1}>
                {data.filename}
              </Text>
            )}
            {/* Content preview for legacy usage */}
            {data.content && !data.url && (
              <Text
                className="text-xs text-zinc-400 mt-1 leading-4"
                numberOfLines={2}
              >
                {data.content}
              </Text>
            )}
          </View>

          {/* Download button */}
          {!!data.url && (
            <Pressable
              onPress={handleDownload}
              android_ripple={{ color: "rgba(255,255,255,0.08)" }}
              className="flex-shrink-0 flex-row items-center gap-1.5 bg-zinc-700 rounded-xl px-3 py-2"
            >
              <AppIcon icon={Download02Icon} size={14} color="#00bbff" />
              <Text className="text-xs font-medium text-[#00bbff]">
                Download
              </Text>
            </Pressable>
          )}
        </View>
      </ToolCardInner>
    </ToolCardShell>
  );
}
