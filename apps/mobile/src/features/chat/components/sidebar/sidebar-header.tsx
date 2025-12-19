import { Image, TextInput, TouchableOpacity, View } from "react-native";
import {
  HugeiconsIcon,
  PencilEdit02Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

interface SidebarHeaderProps {
  onNewChat: () => void;
}

export function SidebarHeader({ onNewChat }: SidebarHeaderProps) {
  return (
    <View className="px-6 py-4 pt-6">
      {/* Brand Header */}
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

      <View className="flex-row items-center gap-4">
        {/* Search Bar */}
        <View className="flex-1 flex-row items-center bg-secondary/20 rounded-xl px-3 h-10 border border-border/30">
          <HugeiconsIcon icon={Search01Icon} size={16} color="#8e8e93" />
          <TextInput
            className="flex-1 ml-2 text-foreground text-sm"
            placeholder="Search"
            placeholderTextColor="#666666"
          />
        </View>

        {/* New Chat Button */}
        <TouchableOpacity
          onPress={onNewChat}
          className="h-10 w-10 items-center justify-center rounded-xl bg-secondary/20 border border-border/30"
          activeOpacity={0.7}
        >
          <HugeiconsIcon icon={PencilEdit02Icon} size={18} color="#ffffff" />
        </TouchableOpacity>
      </View>
    </View>
  );
}
