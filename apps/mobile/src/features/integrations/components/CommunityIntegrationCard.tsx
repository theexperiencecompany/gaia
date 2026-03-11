import { Image } from "expo-image";
import { Button } from "heroui-native";
import { useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import { HugeiconsIcon, UserIcon, Wrench01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAddPublicIntegration } from "../hooks/useCommunityIntegrations";
import type { CommunityIntegration } from "../types";

const FALLBACK_LOGO =
  "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/512px-No_image_available.svg.png";

interface CommunityIntegrationCardProps {
  integration: CommunityIntegration;
  onPress?: (integration: CommunityIntegration) => void;
}

export function CommunityIntegrationCard({
  integration,
  onPress,
}: CommunityIntegrationCardProps) {
  const { mutate: addIntegration, isPending } = useAddPublicIntegration();
  const [added, setAdded] = useState(false);

  const logoUri = integration.iconUrl ?? FALLBACK_LOGO;

  const handleAdd = () => {
    addIntegration(
      { slug: integration.slug },
      {
        onSuccess: () => setAdded(true),
      },
    );
  };

  return (
    <Pressable
      onPress={() => onPress?.(integration)}
      className="flex-row items-center px-4 py-3 active:opacity-60"
    >
      <View className="w-10 h-10 rounded-xl items-center justify-center bg-muted/10 mr-3">
        <Image
          source={{ uri: logoUri }}
          style={{ width: 32, height: 32 }}
          contentFit="contain"
        />
      </View>

      <View className="flex-1 mr-3">
        <View className="flex-row items-center gap-2 mb-0.5">
          <Text className="font-medium text-sm" numberOfLines={1}>
            {integration.name}
          </Text>
          {integration.category ? (
            <View className="px-1.5 py-0.5 rounded bg-muted/15">
              <Text className="text-muted text-[10px]">
                {integration.category}
              </Text>
            </View>
          ) : null}
        </View>

        <Text className="text-muted text-xs" numberOfLines={2}>
          {integration.description}
        </Text>

        <View className="flex-row items-center gap-3 mt-1.5">
          <View className="flex-row items-center gap-1">
            <HugeiconsIcon
              icon={Wrench01Icon}
              size={11}
              color="#6b6b6b"
            />
            <Text className="text-muted text-[11px]">
              {integration.toolCount} tools
            </Text>
          </View>

          <View className="flex-row items-center gap-1">
            <HugeiconsIcon icon={UserIcon} size={11} color="#6b6b6b" />
            <Text className="text-muted text-[11px]">
              {integration.cloneCount} added
            </Text>
          </View>

          {integration.creator?.name ? (
            <Text className="text-muted text-[11px]" numberOfLines={1}>
              by {integration.creator.name}
            </Text>
          ) : null}
        </View>
      </View>

      <Button
        size="sm"
        variant="tertiary"
        onPress={handleAdd}
        isDisabled={isPending || added}
        className={added ? "bg-success/15 px-3 min-w-16" : "bg-muted/10 px-3 min-w-16"}
      >
        {isPending ? (
          <ActivityIndicator size="small" color="#8e8e93" />
        ) : (
          <Button.Label
            className={added ? "text-success text-xs" : "text-muted text-xs"}
          >
            {added ? "Added" : "Add"}
          </Button.Label>
        )}
      </Button>
    </Pressable>
  );
}
