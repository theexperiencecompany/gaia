import { Card } from "heroui-native";
import { Linking, Pressable, View } from "react-native";
import { AppIcon, Download02Icon, File01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

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

function getExtensionColor(ext: string): { bg: string; text: string } {
  switch (ext) {
    case "pdf":
      return { bg: "bg-red-500/15", text: "text-red-400" };
    case "doc":
    case "docx":
      return { bg: "bg-[#00bbff]/15", text: "text-[#00bbff]" };
    case "txt":
      return { bg: "bg-white/10", text: "text-muted" };
    case "md":
      return { bg: "bg-purple-500/15", text: "text-purple-400" };
    case "xls":
    case "xlsx":
      return { bg: "bg-green-500/15", text: "text-green-400" };
    case "csv":
      return { bg: "bg-green-500/15", text: "text-green-400" };
    default:
      return { bg: "bg-white/10", text: "text-muted" };
  }
}

export function DocumentCard({ data }: { data: DocumentData }) {
  const displayName = data.title || data.filename || "Untitled Document";
  const filename = data.filename || "";
  const ext = filename ? getFileExtension(filename) : data.type || "";
  const extColors = getExtensionColor(ext);
  const showFilename =
    data.title && data.filename && data.title !== data.filename;

  const handleDownload = () => {
    if (data.url) {
      Linking.openURL(data.url);
    }
  };

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <View className="flex-row items-center gap-3">
          {/* File icon */}
          <View className="w-10 h-10 rounded-xl bg-[#00bbff]/10 items-center justify-center flex-shrink-0">
            <HugeiconsIcon icon={File01Icon} size={20} color="#00bbff" />
          </View>

          {/* File info */}
          <View className="flex-1 min-w-0">
            <View className="flex-row items-center gap-2 flex-wrap">
              <Text
                className="text-sm font-medium text-foreground flex-shrink-1"
                numberOfLines={1}
              >
                {displayName}
              </Text>
              {!!ext && (
                <View className={`rounded-full px-2 py-0.5 ${extColors.bg}`}>
                  <Text
                    className={`text-[10px] font-semibold ${extColors.text}`}
                  >
                    {ext.toUpperCase()}
                  </Text>
                </View>
              )}
            </View>
            {showFilename && (
              <Text className="text-xs text-muted mt-0.5" numberOfLines={1}>
                {data.filename}
              </Text>
            )}
            {/* Content preview for legacy usage */}
            {data.content && !data.url && (
              <Text
                className="text-xs text-muted mt-1 leading-4"
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
              className="flex-row items-center gap-1.5 rounded-xl bg-[#00bbff]/10 px-3 py-2 active:opacity-70 flex-shrink-0"
            >
              <HugeiconsIcon icon={Download02Icon} size={14} color="#00bbff" />
              <Text className="text-xs font-medium text-[#00bbff]">
                Download
              </Text>
            </Pressable>
          )}
        </View>
      </Card.Body>
    </Card>
  );
}
