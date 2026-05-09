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

// -- Extension pill config (mirrors web Chip color mapping) -------------------

interface ExtPillConfig {
  label: string;
  color: string;
  bg: string;
}

function getExtPillConfig(ext: string): ExtPillConfig {
  switch (ext) {
    case "pdf":
      return { label: "PDF", color: "text-red-400", bg: "bg-red-400/10" };
    case "doc":
    case "docx":
      return {
        label: ext.toUpperCase(),
        color: "text-primary",
        bg: "bg-primary/10",
      };
    case "xls":
    case "xlsx":
      return {
        label: ext.toUpperCase(),
        color: "text-emerald-400",
        bg: "bg-emerald-400/10",
      };
    case "csv":
      return {
        label: "CSV",
        color: "text-emerald-400",
        bg: "bg-emerald-400/10",
      };
    case "md":
      return {
        label: "Markdown",
        color: "text-violet-400",
        bg: "bg-violet-400/10",
      };
    case "txt":
      return { label: "Text", color: "text-zinc-400", bg: "bg-zinc-700/50" };
    default:
      return {
        label: ext ? ext.toUpperCase() : "File",
        color: "text-zinc-400",
        bg: "bg-zinc-700/50",
      };
  }
}

function getFileExtension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

export function DocumentCard({ data }: { data: DocumentData }) {
  const displayName = data.title || data.filename || "Untitled Document";
  const filename = data.filename || "";
  const ext = filename ? getFileExtension(filename) : (data.type ?? "");
  const pillConfig = getExtPillConfig(ext);
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
          <View className="w-10 h-10 rounded-xl bg-zinc-800 items-center justify-center flex-shrink-0">
            <AppIcon icon={File01Icon} size={20} color="#00bbff" />
          </View>

          {/* File info */}
          <View className="flex-1 min-w-0">
            <View className="flex-row items-center gap-2 flex-wrap mb-0.5">
              <Text
                className="text-sm font-medium text-zinc-100 flex-shrink-1"
                numberOfLines={1}
              >
                {displayName}
              </Text>
              {!!ext && (
                <View className={`rounded-full px-2 py-0.5 ${pillConfig.bg}`}>
                  <Text className={`text-xs font-medium ${pillConfig.color}`}>
                    {pillConfig.label}
                  </Text>
                </View>
              )}
            </View>
            {showFilename && (
              <Text className="text-xs text-zinc-400" numberOfLines={1}>
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
              className="flex-shrink-0 flex-row items-center gap-1.5 bg-zinc-800 rounded-xl px-3 py-2"
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
