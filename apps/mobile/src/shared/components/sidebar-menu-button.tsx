import * as Haptics from "expo-haptics";
import { Pressable } from "react-native";
import { AppIcon, Menu01Icon } from "@/components/icons";
import { useSidebar } from "@/features/chat/hooks/sidebar-context";

/**
 * The hamburger button that opens the app-wide sidebar drawer.
 * Used across chat, workflows, integrations, todos — keep one source of
 * truth for hit area, haptics, accessibility, and pressed-state styling.
 */
export function SidebarMenuButton() {
  const { toggleSidebar } = useSidebar();

  return (
    <Pressable
      onPress={() => {
        void Haptics.selectionAsync();
        toggleSidebar();
      }}
      hitSlop={{ top: 16, bottom: 16, left: 16, right: 16 }}
      accessibilityRole="button"
      accessibilityLabel="Toggle menu"
      style={({ pressed }) => ({
        width: 44,
        height: 44,
        borderRadius: 22,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: pressed ? "rgba(255,255,255,0.10)" : "transparent",
      })}
    >
      <AppIcon icon={Menu01Icon} size={20} color="#a1a1aa" />
    </Pressable>
  );
}
