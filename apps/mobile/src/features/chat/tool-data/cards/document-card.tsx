import { Button, Card, Chip } from "heroui-native";
import { Linking, View } from "react-native";
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
  const ext = filename ? getFileExtension(filename) : data.type || "";
  const chipProps = getExtensionChipProps(ext);
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
            <AppIcon icon={File01Icon} size={20} color="#00bbff" />
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
            <>
              <View
                style={{
                  height: 1,
                  backgroundColor: "rgba(255,255,255,0.07)",
                  marginVertical: 4,
                }}
              />
              <Button
                size="sm"
                variant="secondary"
                onPress={handleDownload}
                className="flex-shrink-0 rounded-xl"
              >
                <AppIcon icon={Download02Icon} size={14} color="#00bbff" />
                <Button.Label className="text-[#00bbff]">Download</Button.Label>
              </Button>
            </>
          )}
        </View>
      </Card.Body>
    </Card>
  );
}
