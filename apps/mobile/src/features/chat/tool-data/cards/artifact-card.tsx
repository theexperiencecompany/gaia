import type { ArtifactData } from "@gaia/shared";
import { Linking, Pressable, View } from "react-native";
import {
  AppIcon,
  CodeIcon,
  Download01Icon,
  File01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

// Ported 1:1 from apps/web/src/features/chat/components/bubbles/bot/FileArtifactSection.tsx

// HeroUI Chip color → mobile pill background + text color.
// Mirrors the chip variant="flat" tone used in web FILE_TYPE_CONFIG.
type ChipColor =
  | "primary"
  | "secondary"
  | "success"
  | "warning"
  | "danger"
  | "default";

interface FileTypeConfig {
  label: string;
  color: ChipColor;
  icon: "code" | "file";
}

const FILE_TYPE_CONFIG: Record<string, FileTypeConfig> = {
  md: { label: "Markdown", color: "secondary", icon: "file" },
  html: { label: "HTML", color: "warning", icon: "code" },
  htm: { label: "HTML", color: "warning", icon: "code" },
  txt: { label: "Text", color: "default", icon: "file" },
  json: { label: "JSON", color: "success", icon: "code" },
  py: { label: "Python", color: "primary", icon: "code" },
  js: { label: "JavaScript", color: "warning", icon: "code" },
  ts: { label: "TypeScript", color: "primary", icon: "code" },
  tsx: { label: "TSX", color: "primary", icon: "code" },
  jsx: { label: "JSX", color: "warning", icon: "code" },
  css: { label: "CSS", color: "secondary", icon: "code" },
  csv: { label: "CSV", color: "success", icon: "file" },
  tex: { label: "LaTeX", color: "danger", icon: "file" },
  sql: { label: "SQL", color: "primary", icon: "code" },
  yaml: { label: "YAML", color: "success", icon: "code" },
  yml: { label: "YAML", color: "success", icon: "code" },
  xml: { label: "XML", color: "warning", icon: "code" },
  sh: { label: "Shell", color: "default", icon: "code" },
};

// HeroUI flat-variant chip palette (bg-{color}/20 + text-{color}).
// Fixed hex values keep the mobile build aligned with the web rendered look
// without depending on web-only Tailwind tokens.
const CHIP_PALETTE: Record<ChipColor, { bg: string; text: string }> = {
  primary: { bg: "rgba(0,187,255,0.2)", text: "#00bbff" },
  secondary: { bg: "rgba(168,85,247,0.2)", text: "#c084fc" },
  success: { bg: "rgba(34,197,94,0.2)", text: "#4ade80" },
  warning: { bg: "rgba(245,158,11,0.2)", text: "#fbbf24" },
  danger: { bg: "rgba(239,68,68,0.2)", text: "#f87171" },
  default: { bg: "rgba(63,63,70,0.6)", text: "#e4e4e7" },
};

function getFileConfig(filename: string): FileTypeConfig {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  return (
    FILE_TYPE_CONFIG[ext] || {
      label: ext.toUpperCase() || "File",
      color: "default",
      icon: "file",
    }
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function ArtifactRow({ artifact }: { artifact: ArtifactData }) {
  const config = getFileConfig(artifact.filename);
  const Icon = config.icon === "code" ? CodeIcon : File01Icon;
  const chipPalette = CHIP_PALETTE[config.color];

  // Mobile cannot stream blobs to disk like web; both Open and Download
  // fall through to Linking.openURL so the artifact still resolves if the
  // backend exposes a public URL.
  const open = () => {
    if (artifact.path) Linking.openURL(artifact.path).catch(() => undefined);
  };

  return (
    // Mirrors web `border border-zinc-700/80 bg-zinc-900/70` standalone card.
    <Pressable
      onPress={open}
      className="rounded-2xl border border-zinc-700 bg-zinc-900 p-3.5"
      android_ripple={{ color: "rgba(255,255,255,0.05)" }}
    >
      <View className="flex-row items-center justify-between gap-3">
        {/* Left: icon + chip + filename + size */}
        <View className="flex-1 min-w-0 flex-row items-center gap-2.5">
          <AppIcon icon={Icon} size={20} color="#00bbff" />

          <View className="flex-1 min-w-0">
            <View className="mb-1 flex-row items-center gap-2.5">
              <View
                className="rounded-full px-2 py-0.5"
                style={{ backgroundColor: chipPalette.bg }}
              >
                <Text
                  className="text-xs font-medium"
                  style={{ color: chipPalette.text }}
                >
                  {config.label}
                </Text>
              </View>
              <Text
                className="flex-1 text-sm font-medium text-white"
                numberOfLines={1}
              >
                {artifact.filename}
              </Text>
            </View>

            <Text className="text-xs text-zinc-400" numberOfLines={1}>
              {formatSize(artifact.size_bytes)} · Tap to open
            </Text>
          </View>
        </View>

        {/* Right: Open button + Download icon */}
        <View className="flex-row items-center gap-2 shrink-0">
          <Pressable
            onPress={open}
            className="rounded-lg bg-zinc-800 px-2.5 py-1"
          >
            <Text className="text-xs font-medium text-zinc-200">Open</Text>
          </Pressable>
          <Pressable
            onPress={open}
            hitSlop={8}
            accessibilityLabel="Download artifact"
          >
            <AppIcon icon={Download01Icon} size={16} color="#d4d4d8" />
          </Pressable>
        </View>
      </View>
    </Pressable>
  );
}

export function ArtifactCard({ data }: { data: ArtifactData[] }) {
  const artifacts = Array.isArray(data) ? data : [data];

  if (artifacts.length === 0) return null;

  // Mirrors web `mt-3 flex flex-col gap-2` wrapper; mx-4 my-1 keeps the cards
  // aligned with other mobile tool renderers in the chat stream.
  return (
    <View className="mx-4 my-1 gap-2">
      {artifacts.map((artifact, index) => (
        <ArtifactRow key={`${artifact.path}-${index}`} artifact={artifact} />
      ))}
    </View>
  );
}
