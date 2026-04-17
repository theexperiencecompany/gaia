import type { EmailSentData } from "@gaia/shared";
import { Chip } from "heroui-native";
import { View } from "react-native";
import Svg, { Path } from "react-native-svg";
import { AppIcon, CheckmarkCircle02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

export type { EmailSentData };

function GmailIcon({
  width = 20,
  height = 20,
}: {
  width?: number;
  height?: number;
}) {
  return (
    <Svg width={width} height={height} viewBox="0 0 256 193">
      <Path
        d="M58.182 192.05V93.14L27.507 65.077L0 49.504v125.091c0 9.658 7.825 17.455 17.455 17.455z"
        fill="#4285f4"
      />
      <Path
        d="M197.818 192.05h40.727c9.659 0 17.455-7.826 17.455-17.455V49.505l-31.156 17.837l-27.026 25.798z"
        fill="#34a853"
      />
      <Path
        d="m58.182 93.14l-4.174-38.647l4.174-36.989L128 69.868l69.818-52.364l4.669 34.992l-4.669 40.644L128 145.504z"
        fill="#ea4335"
      />
      <Path
        d="M197.818 17.504V93.14L256 49.504V26.231c0-21.585-24.64-33.89-41.89-20.945z"
        fill="#fbbc04"
      />
      <Path
        d="m0 49.504l26.759 20.07L58.182 93.14V17.504L41.89 5.286C24.61-7.66 0 4.646 0 26.23z"
        fill="#c5221f"
      />
    </Svg>
  );
}

function formatTime(timestamp?: string): string {
  if (!timestamp) return "Just now";

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "Just now";

  const now = new Date();
  const diffInSeconds = (now.getTime() - date.getTime()) / 1000;

  if (diffInSeconds < 60) return "Just now";
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

export function EmailSentCard({ data }: { data: EmailSentData }) {
  const timestamp = data.timestamp ?? data.sent_at;
  const recipients = data.recipients ?? data.to ?? [];
  const summary = data.message ?? data.body;

  return (
    <View className="mx-4 my-1 rounded-2xl bg-green-900/20 p-4">
      {/* Header */}
      <View className="mb-3 flex-row items-center justify-between">
        <View className="flex-row items-center gap-2">
          <GmailIcon width={20} height={20} />
          <AppIcon icon={CheckmarkCircle02Icon} size={20} color="#4ade80" />
          <Text className="text-sm font-medium text-green-400">Email Sent</Text>
        </View>
        <Chip size="sm" variant="soft" color="success" animation="disable-all">
          <Chip.Label>{formatTime(timestamp)}</Chip.Label>
        </Chip>
      </View>

      {/* Email Details */}
      <View className="gap-2">
        {data.subject ? (
          <Text className="text-sm">
            <Text className="text-gray-400">Subject: </Text>
            <Text className="text-gray-200">{data.subject}</Text>
          </Text>
        ) : null}

        {recipients.length > 0 ? (
          <Text className="text-sm">
            <Text className="text-gray-400">To: </Text>
            <Text className="text-gray-200">{recipients.join(", ")}</Text>
          </Text>
        ) : null}

        {summary ? (
          <Text className="text-sm font-medium text-green-400">{summary}</Text>
        ) : null}
      </View>
    </View>
  );
}
