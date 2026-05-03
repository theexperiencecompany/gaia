import { useState } from "react";
import { Image, Linking, View } from "react-native";
import { SquareArrowUpRight02Icon, ToolsIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import {
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

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

/** Action badge using bg contrast only — no borders */
function ActionBadge({ label }: { label: string }) {
  return (
    <View className="px-2 py-0.5 rounded-full bg-[#00bbff]/10">
      <Text className="text-xs font-medium text-[#00bbff] capitalize">
        {label}
      </Text>
    </View>
  );
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
    <ToolCardShell>
      {/* Optional message header */}
      {!!data.message && (
        <Text className="text-xs text-zinc-400 mb-3">{data.message}</Text>
      )}

      <ToolCardInner onPress={url ? handleOpen : undefined}>
        <View className="flex-row items-center gap-3">
          {/* Google Docs icon */}
          <View className="w-10 h-10 rounded-xl bg-zinc-700/50 items-center justify-center flex-shrink-0">
            <GoogleDocsIcon />
          </View>

          {/* Document info */}
          <View className="flex-1 min-w-0">
            <Text
              className="text-sm font-medium text-zinc-200"
              numberOfLines={2}
            >
              {title}
            </Text>
            <View className="flex-row items-center gap-2 mt-1 flex-wrap">
              {!!doc.modified_time && (
                <Text className="text-xs text-zinc-500">
                  Modified {formatDate(doc.modified_time)}
                </Text>
              )}
              {!!actionLabel && <ActionBadge label={actionLabel} />}
            </View>
          </View>

          {/* Open link indicator */}
          {!!url && (
            <View className="flex-shrink-0 flex-row items-center gap-1.5 bg-zinc-800 rounded-xl px-3 py-2">
              <AppIcon
                icon={SquareArrowUpRight02Icon}
                size={14}
                color="#00bbff"
              />
              <Text className="text-xs font-medium text-[#00bbff]">Open</Text>
            </View>
          )}
        </View>
      </ToolCardInner>
    </ToolCardShell>
  );
}
