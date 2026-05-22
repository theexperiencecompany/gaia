import { Stack } from "expo-router";

export default function TabsLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: "#111111" },
        animation: "fade",
        animationDuration: 150,
      }}
    />
  );
}
