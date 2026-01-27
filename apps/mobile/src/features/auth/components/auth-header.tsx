import { Image, Text, View } from "react-native";

interface AuthHeaderProps {
  title: string;
}

export function AuthHeader({ title }: AuthHeaderProps) {
  return (
    <View className="items-center mb-8">
      <View className="w-17.5 h-17.5 rounded-full bg-accent-soft items-center justify-center mb-4">
        <Image
          source={require("@shared/assets/logo/logo.webp")}
          className="w-12.5 h-12.5"
          resizeMode="contain"
        />
      </View>
      <Text className="text-2xl font-bold text-foreground text-center">
        {title}
      </Text>
    </View>
  );
}
