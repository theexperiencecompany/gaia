import { Card } from "heroui-native";
import { useState } from "react";
import { Image, Linking, Pressable, View } from "react-native";
import { SquareArrowUpRight02Icon, ToolsIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";

const GOOGLE_DOCS_LOGO_URI =
  "https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Google_Docs_logo_%282020%29.svg/512px-Google_Docs_logo_%282020%29.svg.png";

export interface GoogleDocsDocument {
  id?: string;
  title?: string;
  url?: string;
  created_time?: string;
  modified_time?: string;
  type?: string;
}

export interface GoogleDocsData {
  document?: GoogleDocsDocument;
  query?: string | null;
  action?: string;
  message?: string;
  type?: string;
  // Legacy flat fields
  documentId?: string;
  title?: string;
  url?: string;
}

function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function getActionLabel(action?: string): string {
  switch (action) {
    case "create":
      return "Created";
    case "update":
      return "Updated";
    case "share":
      return "Shared";
    case "list":
      return "Listed";
    default:
      return action ?? "";
  }
}

function GoogleDocsIcon() {
  const [errored, setErrored] = useState(false);

  if (errored) {
    return <AppIcon icon={ToolsIcon} size={22} color="#4285F4" />;
  }

  return (
    <Image
      source={{ uri: GOOGLE_DOCS_LOGO_URI }}
      style={{ width: 26, height: 26, resizeMode: "contain" }}
      onError={() => setErrored(true)}
    />
  );
}

export function GoogleDocsCard({ data }: { data: GoogleDocsData }) {
  // Normalise: support both nested `document` object and legacy flat fields
  const doc = data.document ?? {
    id: data.documentId,
    title: data.title,
    url: data.url,
  };

  const title = doc.title || "Untitled Document";
  const url = doc.url;
  const actionLabel = getActionLabel(data.action);

  const handleOpen = () => {
    if (url) {
      Linking.openURL(url);
    }
  };

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Optional message header */}
        {!!data.message && (
          <Text className="text-xs text-muted mb-2">{data.message}</Text>
        )}

        {/* Document row */}
        <View className="flex-row items-center gap-3">
          {/* Google Docs icon */}
          <View className="w-10 h-10 rounded-xl bg-white/5 items-center justify-center flex-shrink-0">
            <GoogleDocsIcon />
          </View>

          {/* Document info */}
          <View className="flex-1 min-w-0">
            <Text
              className="text-sm font-medium text-foreground"
              numberOfLines={2}
            >
              {title}
            </Text>
            <View className="flex-row items-center gap-2 mt-0.5 flex-wrap">
              {doc.modified_time && (
                <Text className="text-[11px] text-muted">
                  Modified: {formatDate(doc.modified_time)}
                </Text>
              )}
              {!!actionLabel && (
                <View className="rounded-full bg-[#00bbff]/10 px-2 py-0.5">
                  <Text className="text-[10px] font-medium text-[#00bbff]">
                    {actionLabel}
                  </Text>
                </View>
              )}
            </View>
          </View>

          {/* Open button */}
          {!!url && (
            <Pressable
              onPress={handleOpen}
              className="flex-row items-center gap-1.5 rounded-xl bg-[#00bbff]/10 px-3 py-2 active:opacity-70 flex-shrink-0"
            >
              <AppIcon
                icon={SquareArrowUpRight02Icon}
                size={14}
                color="#00bbff"
              />
              <Text className="text-xs font-medium text-[#00bbff]">Open</Text>
            </Pressable>
          )}
        </View>
      </Card.Body>
    </Card>
  );
}
