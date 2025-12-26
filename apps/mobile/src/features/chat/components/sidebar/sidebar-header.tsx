import { Image, View } from "react-native";
import { Button, TextField } from "heroui-native";
import {
  HugeiconsIcon,
  PencilEdit02Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "react-native";
import { router } from "expo-router";

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
        <View className="flex-1">
          <TextField>
            <TextField.Input placeholder="Search">
              <TextField.InputStartContent>
                <HugeiconsIcon icon={Search01Icon} size={16} color="#8e8e93" />
              </TextField.InputStartContent>
            </TextField.Input>
          </TextField>
        </View>

        {/* New Chat Button */}
        <Button variant="secondary" isIconOnly onPress={onNewChat}>
          <HugeiconsIcon icon={PencilEdit02Icon} size={18} color="#ffffff" />
        </Button>
      </View>
      <Button
        className="mt-10"
        size="lg"
        onPress={() => router.push("/(app)/test")}
      >
        <Button.Label>Test Route</Button.Label>
      </Button>
    </View>
  );
}
