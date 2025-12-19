import { Image, View } from "react-native";
import { Text } from "@/components/ui/text";

interface AuthHeaderProps {
  title: string;
}

export function AuthHeader({ title }: AuthHeaderProps) {
  return (
    <View className="items-center mb-8">
      <View className="w-[70px] h-[70px] rounded-full bg-[#16c1ff]/15 items-center justify-center mb-4">
        <Image
          source={require("@/assets/logo/logo.webp")}
          className="w-[50px] h-[50px]"
          resizeMode="contain"
        />
      </View>
      <Text className="text-2xl font-bold text-white text-center">{title}</Text>
    </View>
  );
}
