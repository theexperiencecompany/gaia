import type { ArtifactData } from "@gaia/shared";
import { Linking, View } from "react-native";
import {
  type AnyIcon,
  AppIcon,
  CodeIcon,
  DocumentAttachmentIcon,
  Download02Icon,
  File01Icon,
  FileEmpty02Icon,
  Image01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Helpers -----------------------------------------------------------------

function formatFileSize(bytes?: number): string | undefined {
  if (bytes === undefined || bytes === null) return undefined;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function getFileIcon(contentType?: string, filename?: string): AnyIcon {
  const type = (contentType ?? "").toLowerCase();
  const name = (filename ?? "").toLowerCase();

  if (type.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg)$/.test(name)) {
    return Image01Icon;
  }
  if (type.includes("pdf") || name.endsWith(".pdf")) {
    return DocumentAttachmentIcon;
  }
  if (
    type.includes("json") ||
    type.includes("javascript") ||
    type.includes("typescript") ||
    /\.(js|ts|tsx|jsx|json|py|go|rs|rb|java|cpp|c|css|html)$/.test(name)
  ) {
    return CodeIcon;
  }
  if (
    type.includes("document") ||
    type.includes("text") ||
    /\.(doc|docx|txt|md)$/.test(name)
  ) {
    return FileEmpty02Icon;
  }
  return File01Icon;
}

// -- File row ----------------------------------------------------------------

function FileRow({ file }: { file: ArtifactData }) {
  const icon = getFileIcon(file.content_type, file.filename);
  const size = formatFileSize(file.size_bytes);
  const hasUrl = Boolean(file.path);

  const onPress = hasUrl ? () => Linking.openURL(file.path) : undefined;

  return (
    <ToolCardInner dense onPress={onPress}>
      <View className="flex-row items-center gap-3">
        <View className="w-8 h-8 rounded-full bg-zinc-800 items-center justify-center">
          <AppIcon icon={icon} size={16} color="#00bbff" />
        </View>
        <View className="flex-1 min-w-0">
          <Text className="text-zinc-100 text-sm font-medium" numberOfLines={1}>
            {file.filename ?? "Untitled"}
          </Text>
          {(size || file.content_type) && (
            <Text className="text-zinc-500 text-xs mt-0.5" numberOfLines={1}>
              {[size, file.content_type]
                .filter((s): s is string => !!s && s.length > 0)
                .join(" · ")}
            </Text>
          )}
        </View>
        {hasUrl ? (
          <View className="flex-row items-center gap-1">
            <AppIcon icon={Download02Icon} size={14} color="#00bbff" />
            <Text className="text-primary text-xs font-semibold">Download</Text>
          </View>
        ) : null}
      </View>
    </ToolCardInner>
  );
}

// -- Card --------------------------------------------------------------------

export function ArtifactCard({ data }: { data: ArtifactData[] }) {
  const files = Array.isArray(data) ? data : [data];

  return (
    <ToolCardShell>
      <ToolCardHeader icon={File01Icon} title="Files" count={files.length} />
      {files.length === 0 ? (
        <Text className="text-zinc-500 text-sm">No files</Text>
      ) : (
        <View className="gap-1.5">
          {files.map((file, idx) => (
            <FileRow
              key={`${file.path ?? "file"}-${file.filename ?? idx}`}
              file={file}
            />
          ))}
        </View>
      )}
    </ToolCardShell>
  );
}
