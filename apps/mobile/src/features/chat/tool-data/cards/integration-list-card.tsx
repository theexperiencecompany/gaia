import { Image, Linking, View } from "react-native";
import { AppIcon, ConnectIcon, PlusSignIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Types -------------------------------------------------------------------

export interface IntegrationListItem {
  id?: string;
  name: string;
  description?: string;
  category?: string;
  iconUrl?: string | null;
  slug?: string;
  connect_url?: string;
  relevanceScore?: number;
  authType?: string | null;
}

export interface IntegrationListData {
  hasSuggestions?: boolean;
  message?: string;
  suggested?: IntegrationListItem[];
  integrations?: IntegrationListItem[];
}

// -- Row ---------------------------------------------------------------------

function IntegrationRow({ item }: { item: IntegrationListItem }) {
  const connectUrl = item.connect_url;
  const onPress = connectUrl ? () => Linking.openURL(connectUrl) : undefined;

  return (
    <ToolCardInner dense onPress={onPress}>
      <View className="flex-row items-center gap-3">
        {item.iconUrl ? (
          <Image
            source={{ uri: item.iconUrl }}
            style={{ width: 32, height: 32, borderRadius: 8 }}
            resizeMode="contain"
          />
        ) : (
          <View className="w-8 h-8 rounded-lg bg-zinc-800 items-center justify-center">
            <AppIcon icon={PlusSignIcon} size={16} color="#00bbff" />
          </View>
        )}
        <View className="flex-1 min-w-0">
          <Text className="text-zinc-100 text-sm font-medium" numberOfLines={1}>
            {item.name}
          </Text>
          {item.description ? (
            <Text className="text-zinc-500 text-xs mt-0.5" numberOfLines={2}>
              {item.description}
            </Text>
          ) : item.category ? (
            <Text className="text-zinc-500 text-xs mt-0.5" numberOfLines={1}>
              {item.category}
            </Text>
          ) : null}
        </View>
        <View className="flex-row items-center gap-1 rounded-full bg-primary px-3 py-1">
          <AppIcon icon={ConnectIcon} size={12} color="#000000" />
          <Text className="text-black text-xs font-semibold">Connect</Text>
        </View>
      </View>
    </ToolCardInner>
  );
}

// -- Card --------------------------------------------------------------------

export function IntegrationListCard({ data }: { data: IntegrationListData }) {
  const integrations =
    data.integrations ?? data.suggested ?? ([] as IntegrationListItem[]);
  const hasItems = integrations.length > 0;

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={ConnectIcon}
        title="Integrations"
        count={hasItems ? integrations.length : undefined}
      />

      {data.message ? (
        <Text className="text-zinc-300 text-sm mb-3">{data.message}</Text>
      ) : null}

      {hasItems ? (
        <View className="gap-1.5">
          {integrations.map((item, idx) => (
            <IntegrationRow
              key={item.id ?? item.slug ?? `${item.name}-${idx}`}
              item={item}
            />
          ))}
        </View>
      ) : (
        <Text className="text-zinc-500 text-sm">No integrations available</Text>
      )}
    </ToolCardShell>
  );
}
