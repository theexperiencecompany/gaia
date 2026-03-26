import * as Linking from "expo-linking";
import { Button, Card } from "heroui-native";
import { useState } from "react";
import { Image, ScrollView, View } from "react-native";
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
          <Card
            key={platform.id}
            variant="secondary"
            className="rounded-3xl bg-surface"
          >
            <Card.Body className="flex-row items-center gap-4 px-4 py-4">
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
              <Button
                onPress={() =>
                  isLinked
                    ? handleDisconnect(platform.id)
                    : void handleConnect(platform)
                }
                variant="tertiary"
                className={isLinked ? "bg-danger/10" : "bg-primary/10"}
              >
                <Button.Label
                  className={isLinked ? "text-danger" : "text-primary"}
                >
                  {isLinked ? "Disconnect" : "Connect"}
                </Button.Label>
              </Button>
            </Card.Body>
          </Card>
        );
      })}
    </ScrollView>
  );
}
