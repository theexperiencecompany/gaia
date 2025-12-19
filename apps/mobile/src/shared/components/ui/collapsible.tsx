import { type PropsWithChildren, useState } from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { IconSymbol } from "@/shared/components/ui/icon-symbol";
import { Colors } from "@/shared/constants/theme";
import { useColorScheme } from "@/shared/hooks/use-color-scheme";

export function Collapsible({
  children,
  title,
}: PropsWithChildren & { title: string }) {
  const [isOpen, setIsOpen] = useState(false);
  const theme = useColorScheme() ?? "light";
  const textColor = theme === "light" ? Colors.light.text : Colors.dark.text;

  return (
    <View>
      <TouchableOpacity
        style={styles.heading}
        onPress={() => setIsOpen((value) => !value)}
        activeOpacity={0.8}
      >
        <IconSymbol
          name="chevron.right"
          size={18}
          weight="medium"
          color={theme === "light" ? Colors.light.icon : Colors.dark.icon}
          style={{ transform: [{ rotate: isOpen ? "90deg" : "0deg" }] }}
        />

        <Text style={[styles.title, { color: textColor }]}>{title}</Text>
      </TouchableOpacity>
      {isOpen && <View style={styles.content}>{children}</View>}
    </View>
  );
}

const styles = StyleSheet.create({
  heading: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  title: {
    fontWeight: "600",
    fontSize: 16,
  },
  content: {
    marginTop: 6,
    marginLeft: 24,
  },
});
