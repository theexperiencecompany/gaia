import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { useState } from "react";
import { Image, Pressable, ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface Platform {
  id: string;
  name: string;
  description: string;
  icon: string;
  authType: "bot_link" | "oauth";
  botUrl?: string;
}

const PLATFORMS: Platform[] = [
  {
    id: "telegram",
    name: "Telegram",
    description: "Receive notifications via Telegram bot",
    icon: "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Telegram_2019_Logo.svg/120px-Telegram_2019_Logo.svg.png",
    authType: "bot_link",
    botUrl: "https://t.me/gaia_assistant_bot",
  },
  {
    id: "discord",
    name: "Discord",
    description: "Receive notifications via Discord bot",
    icon: "https://assets-global.slack.com/marketing-api/assets/img/icons/icon_app_home.png",
    authType: "oauth",
  },
  {
    id: "slack",
    name: "Slack",
    description: "Receive notifications via Slack",
    icon: "https://a.slack-edge.com/80588/marketing/img/meta/slack_hash_128.png",
    authType: "oauth",
  },
];

export function LinkedAccountsSection() {
  const { spacing, fontSize } = useResponsive();
  const [linkedPlatforms, setLinkedPlatforms] = useState<
    Record<string, boolean>
  >({});

  const handleConnect = async (platform: Platform) => {
    if (platform.authType === "bot_link" && platform.botUrl) {
      await Linking.openURL(platform.botUrl);
      return;
    }
    // OAuth flow — open in-app browser for OAuth
    // const redirectUrl = Linking.createURL("settings/linked-accounts/callback");
    // const authUrl = `${API_ORIGIN}/api/v1/auth/${platform.id}/connect?redirect=${encodeURIComponent(redirectUrl)}`;
    // const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
    // if (result.type === "success") {
    //   setLinkedPlatforms(prev => ({ ...prev, [platform.id]: true }));
    // }
  };

  const handleDisconnect = (platformId: string) => {
    setLinkedPlatforms((prev) => ({ ...prev, [platformId]: false }));
  };

  return (
    <ScrollView
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
    >
      <Text style={{ fontSize: fontSize.sm, color: "#71717a" }}>
        Connect your accounts to receive notifications and enable automations.
      </Text>

      {PLATFORMS.map((platform) => {
        const isLinked = linkedPlatforms[platform.id] ?? false;
        return (
          <View
            key={platform.id}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.md,
              backgroundColor: "#1c1c1e",
              borderRadius: 14,
              padding: spacing.md,
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.06)",
            }}
          >
            <Image
              source={{ uri: platform.icon }}
              style={{ width: 36, height: 36 }}
              resizeMode="contain"
            />
            <View style={{ flex: 1 }}>
              <Text
                style={{
                  fontSize: fontSize.sm,
                  fontWeight: "600",
                  color: "#fff",
                }}
              >
                {platform.name}
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                {platform.description}
              </Text>
            </View>
            <Pressable
              onPress={() =>
                isLinked
                  ? handleDisconnect(platform.id)
                  : void handleConnect(platform)
              }
              style={{
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.xs + 2,
                borderRadius: 10,
                backgroundColor: isLinked
                  ? "rgba(239,68,68,0.1)"
                  : "rgba(0,187,255,0.1)",
                borderWidth: 1,
                borderColor: isLinked
                  ? "rgba(239,68,68,0.3)"
                  : "rgba(0,187,255,0.3)",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  fontWeight: "600",
                  color: isLinked ? "#ef4444" : "#00bbff",
                }}
              >
                {isLinked ? "Disconnect" : "Connect"}
              </Text>
            </Pressable>
          </View>
        );
      })}
    </ScrollView>
  );
}
