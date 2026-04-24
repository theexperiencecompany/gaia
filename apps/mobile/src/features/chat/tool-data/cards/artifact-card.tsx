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

// -- File type config (mirrors web FILE_TYPE_CONFIG) --------------------------

interface FileTypeConfig {
  label: string;
  color: string; // text color class
  bg: string; // pill bg class
  icon: "code" | "file" | "image" | "pdf";
}

const FILE_TYPE_CONFIG: Record<string, FileTypeConfig> = {
  md: {
    label: "Markdown",
    color: "text-violet-400",
    bg: "bg-violet-400/10",
    icon: "file",
  },
  html: {
    label: "HTML",
    color: "text-amber-400",
    bg: "bg-amber-400/10",
    icon: "code",
  },
  htm: {
    label: "HTML",
    color: "text-amber-400",
    bg: "bg-amber-400/10",
    icon: "code",
  },
  txt: {
    label: "Text",
    color: "text-zinc-400",
    bg: "bg-zinc-700",
    icon: "file",
  },
  json: {
    label: "JSON",
    color: "text-emerald-400",
    bg: "bg-emerald-400/10",
    icon: "code",
  },
  py: {
    label: "Python",
    color: "text-primary",
    bg: "bg-primary/10",
    icon: "code",
  },
  js: {
    label: "JavaScript",
    color: "text-amber-400",
    bg: "bg-amber-400/10",
    icon: "code",
  },
  ts: {
    label: "TypeScript",
    color: "text-primary",
    bg: "bg-primary/10",
    icon: "code",
  },
  tsx: {
    label: "TSX",
    color: "text-primary",
    bg: "bg-primary/10",
    icon: "code",
  },
  jsx: {
    label: "JSX",
    color: "text-amber-400",
    bg: "bg-amber-400/10",
    icon: "code",
  },
  css: {
    label: "CSS",
    color: "text-violet-400",
    bg: "bg-violet-400/10",
    icon: "code",
  },
  csv: {
    label: "CSV",
    color: "text-emerald-400",
    bg: "bg-emerald-400/10",
    icon: "file",
  },
  sql: {
    label: "SQL",
    color: "text-primary",
    bg: "bg-primary/10",
    icon: "code",
  },
  yaml: {
    label: "YAML",
    color: "text-emerald-400",
    bg: "bg-emerald-400/10",
    icon: "code",
  },
  yml: {
    label: "YAML",
    color: "text-emerald-400",
    bg: "bg-emerald-400/10",
    icon: "code",
  },
  xml: {
    label: "XML",
    color: "text-amber-400",
    bg: "bg-amber-400/10",
    icon: "code",
  },
  sh: {
    label: "Shell",
    color: "text-zinc-300",
    bg: "bg-zinc-700",
    icon: "code",
  },
  pdf: {
    label: "PDF",
    color: "text-red-400",
    bg: "bg-red-400/10",
    icon: "pdf",
  },
  png: {
    label: "PNG",
    color: "text-pink-400",
    bg: "bg-pink-400/10",
    icon: "image",
  },
  jpg: {
    label: "JPEG",
    color: "text-pink-400",
    bg: "bg-pink-400/10",
    icon: "image",
  },
  jpeg: {
    label: "JPEG",
    color: "text-pink-400",
    bg: "bg-pink-400/10",
    icon: "image",
  },
  gif: {
    label: "GIF",
    color: "text-pink-400",
    bg: "bg-pink-400/10",
    icon: "image",
  },
  webp: {
    label: "WebP",
    color: "text-pink-400",
    bg: "bg-pink-400/10",
    icon: "image",
  },
  svg: {
    label: "SVG",
    color: "text-pink-400",
    bg: "bg-pink-400/10",
    icon: "image",
  },
};

function getFileConfig(filename: string, contentType?: string): FileTypeConfig {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (FILE_TYPE_CONFIG[ext]) return FILE_TYPE_CONFIG[ext];

  // Fall back on content type
  const type = (contentType ?? "").toLowerCase();
  if (type.startsWith("image/")) {
    return {
      label: "Image",
      color: "text-pink-400",
      bg: "bg-pink-400/10",
      icon: "image",
    };
  }
  if (type.includes("pdf")) {
    return {
      label: "PDF",
      color: "text-red-400",
      bg: "bg-red-400/10",
      icon: "pdf",
    };
  }

  return {
    label: ext.toUpperCase() || "File",
    color: "text-zinc-400",
    bg: "bg-zinc-700",
    icon: "file",
  };
}

// -- Helpers ------------------------------------------------------------------

function formatFileSize(bytes?: number): string | undefined {
  if (bytes === undefined || bytes === null) return undefined;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function getFileIcon(iconKind: FileTypeConfig["icon"]): AnyIcon {
  if (iconKind === "image") return Image01Icon;
  if (iconKind === "pdf") return DocumentAttachmentIcon;
  if (iconKind === "code") return CodeIcon;
  return FileEmpty02Icon;
}

// -- File row -----------------------------------------------------------------

function FileRow({ file }: { file: ArtifactData }) {
  const config = getFileConfig(file.filename ?? "", file.content_type);
  const icon = getFileIcon(config.icon);
  const size = formatFileSize(file.size_bytes);
  const hasUrl = Boolean(file.path);

  const onPress = hasUrl ? () => Linking.openURL(file.path) : undefined;

  return (
    <ToolCardInner dense onPress={onPress}>
      <View className="flex-row items-center gap-3">
        {/* File type icon — square container, matches web shrink-0 pattern */}
        <View className="w-8 h-8 rounded-lg bg-zinc-700 items-center justify-center shrink-0">
          <AppIcon icon={icon} size={16} color="#00bbff" />
        </View>

        <View className="flex-1 min-w-0">
          {/* File type chip + filename row (mirrors web layout) */}
          <View className="flex-row items-center gap-2 mb-0.5 flex-wrap">
            <View className={`rounded-full px-2 py-0.5 ${config.bg}`}>
              <Text className={`text-[10px] font-medium ${config.color}`}>
                {config.label}
              </Text>
            </View>
            <Text
              className="text-zinc-100 text-sm font-medium flex-shrink"
              numberOfLines={1}
            >
              {file.filename ?? "Untitled"}
            </Text>
          </View>
          <Text className="text-zinc-400 text-xs" numberOfLines={1}>
            {[size, hasUrl ? "Tap to open" : undefined]
              .filter((s): s is string => !!s)
              .join(" · ")}
          </Text>
        </View>

        {/* Open + Download actions — mirrors web's Open button + Download icon */}
        {hasUrl ? (
          <View className="flex-row items-center gap-2 shrink-0">
            <View
              className="rounded-lg px-2.5 py-1 items-center justify-center"
              style={{ backgroundColor: "rgba(0,187,255,0.15)" }}
            >
              <Text className="text-primary text-xs font-semibold">Open</Text>
            </View>
            <AppIcon icon={Download02Icon} size={16} color="#71717a" />
          </View>
        ) : null}
      </View>
    </ToolCardInner>
  );
}

// -- Card ---------------------------------------------------------------------

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
