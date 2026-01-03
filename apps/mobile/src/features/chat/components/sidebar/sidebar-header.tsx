import { Button } from "heroui-native";
import { Image, Text, TextInput, View } from "react-native";
import {
  HugeiconsIcon,
  PencilEdit02Icon,
  Search01Icon,
} from "@/components/icons";

interface SidebarHeaderProps {
  onNewChat: () => void;
}

export function SidebarHeader({ onNewChat }: SidebarHeaderProps) {
  return (
    <View className="px-4 py-4 pt-6">
      <View className="flex-row items-center gap-3 mb-6 px-1">
        <Image
          source={require("@/assets/logo/logo.webp")}
          className="w-7 h-7"
          resizeMode="contain"
        />
        <Text className="text-xl font-bold tracking-tight text-foreground">
          GAIA
        </Text>
      </View>

      <View className="flex-row items-center">
        <View className="flex-1 flex-row items-center bg-default rounded-xl px-3 py-2">
          <HugeiconsIcon icon={Search01Icon} size={14} color="#8e8e93" />
          <TextInput
            placeholder="Search"
            placeholderTextColor="#8e8e93"
            className="flex-1 ml-2 text-sm text-foreground"
          />
        </View>

        <Button
          variant="secondary"
          size="sm"
          className="ml-2"
          isIconOnly
          onPress={onNewChat}
        >
          <HugeiconsIcon icon={PencilEdit02Icon} size={16} color="#ffffff" />
        </Button>
      </View>
    </View>
  );
}
