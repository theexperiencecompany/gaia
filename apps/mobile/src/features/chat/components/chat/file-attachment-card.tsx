import * as WebBrowser from "expo-web-browser";
import { Card, Chip, PressableFeedback } from "heroui-native";
import { useCallback } from "react";
import { View } from "react-native";
import {
  AppIcon,
  DocumentAttachmentIcon,
  Download02Icon,
  File01Icon,
  FileEmpty02Icon,
  FolderFileStorageIcon,
  Image01Icon,
  LinkSquare02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

type FileType =
  | "pdf"
  | "doc"
  | "xls"
  | "ppt"
  | "txt"
  | "zip"
  | "image"
  | "generic";

function detectFileType(mimeType: string, fileName: string): FileType {
  const mime = mimeType.toLowerCase();
  const name = fileName.toLowerCase();

  if (mime.startsWith("image/")) return "image";
  if (mime === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (mime.includes("word") || name.endsWith(".doc") || name.endsWith(".docx"))
    return "doc";
  if (
    mime.includes("spreadsheet") ||
    mime.includes("excel") ||
    name.endsWith(".xls") ||
    name.endsWith(".xlsx") ||
    name.endsWith(".csv")
  )
    return "xls";
  if (
    mime.includes("presentation") ||
    mime.includes("powerpoint") ||
    name.endsWith(".ppt") ||
    name.endsWith(".pptx")
  )
    return "ppt";
  if (mime === "text/plain" || name.endsWith(".txt") || name.endsWith(".md"))
    return "txt";
  if (
    mime.includes("zip") ||
    mime.includes("compressed") ||
    name.endsWith(".zip") ||
    name.endsWith(".tar") ||
    name.endsWith(".gz") ||
    name.endsWith(".rar")
  )
    return "zip";
  return "generic";
}

type ChipColor = React.ComponentProps<typeof Chip>["color"];

interface FileTypeConfig {
  chipColor: ChipColor;
  iconColor: string;
  bgColor: string;
  label: string;
}

const FILE_TYPE_CONFIGS: Record<FileType, FileTypeConfig> = {
  pdf: {
    chipColor: "danger",
    iconColor: "#ef4444",
    bgColor: "rgba(239,68,68,0.12)",
    label: "PDF",
  },
  doc: {
    chipColor: "accent",
    iconColor: "#3b82f6",
    bgColor: "rgba(59,130,246,0.12)",
    label: "DOC",
  },
  xls: {
    chipColor: "success",
    iconColor: "#22c55e",
    bgColor: "rgba(34,197,94,0.12)",
    label: "XLS",
  },
  ppt: {
    chipColor: "warning",
    iconColor: "#f97316",
    bgColor: "rgba(249,115,22,0.12)",
    label: "PPT",
  },
  txt: {
    chipColor: "default",
    iconColor: "#a1a1aa",
    bgColor: "rgba(161,161,170,0.12)",
    label: "TXT",
  },
  zip: {
    chipColor: "warning",
    iconColor: "#eab308",
    bgColor: "rgba(234,179,8,0.12)",
    label: "ZIP",
  },
  image: {
    chipColor: "default",
    iconColor: "#8b5cf6",
    bgColor: "rgba(139,92,246,0.12)",
    label: "IMG",
  },
  generic: {
    chipColor: "default",
    iconColor: "#71717a",
    bgColor: "rgba(113,113,122,0.12)",
    label: "FILE",
  },
};

function getFileIcon(fileType: FileType) {
  switch (fileType) {
    case "pdf":
      return DocumentAttachmentIcon;
    case "doc":
      return File01Icon;
    case "xls":
      return FileEmpty02Icon;
    case "ppt":
      return FolderFileStorageIcon;
    case "txt":
      return File01Icon;
    case "zip":
      return FolderFileStorageIcon;
    case "image":
      return Image01Icon;
    default:
      return File01Icon;
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface FileAttachmentData {
  url: string;
  fileName: string;
  mimeType: string;
  fileSize?: number;
}

interface FileAttachmentCardProps {
  attachment: FileAttachmentData;
}

export function FileAttachmentCard({ attachment }: FileAttachmentCardProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  const fileType = detectFileType(attachment.mimeType, attachment.fileName);
  const config = FILE_TYPE_CONFIGS[fileType];
  const IconComponent = getFileIcon(fileType);

  const handleOpen = useCallback(async () => {
    await WebBrowser.openBrowserAsync(attachment.url);
  }, [attachment.url]);

  const isPdf = fileType === "pdf";

  return (
    <PressableFeedback
      onPress={() => void handleOpen()}
      style={{ maxWidth: 280 }}
    >
      <Card
        variant="secondary"
        animation="disable-all"
        className="rounded-xl border border-white/[0.08] bg-white/[0.05]"
      >
        <Card.Body
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
            padding: spacing.sm + 2,
          }}
        >
          {/* File type icon */}
          <View
            style={{
              width: 44,
              height: 44,
              borderRadius: moderateScale(10, 0.5),
              backgroundColor: config.bgColor,
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <AppIcon icon={IconComponent} size={22} color={config.iconColor} />
          </View>

          {/* File metadata */}
          <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
            <Text
              numberOfLines={1}
              style={{
                fontSize: fontSize.sm,
                fontWeight: "500",
                color: "#e4e4e7",
              }}
            >
              {attachment.fileName}
            </Text>
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
            >
              <Chip
                size="sm"
                variant="soft"
                color={config.chipColor}
                animation="disable-all"
              >
                <Chip.Label
                  style={{
                    fontSize: fontSize.xs - 1,
                    fontWeight: "600",
                    letterSpacing: 0.3,
                  }}
                >
                  {config.label}
                </Chip.Label>
              </Chip>
              {attachment.fileSize !== undefined ? (
                <Text style={{ fontSize: fontSize.xs - 1, color: "#71717a" }}>
                  {formatFileSize(attachment.fileSize)}
                </Text>
              ) : null}
            </View>
          </View>

          {/* Action icon */}
          <View style={{ flexShrink: 0, paddingLeft: spacing.xs }}>
            <AppIcon
              icon={isPdf ? Download02Icon : LinkSquare02Icon}
              size={16}
              color="#71717a"
            />
          </View>
        </Card.Body>
      </Card>
    </PressableFeedback>
  );
}
