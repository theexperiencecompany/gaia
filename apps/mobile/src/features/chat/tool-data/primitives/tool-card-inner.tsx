import type { ReactNode } from "react";
import { Pressable, View } from "react-native";

interface ToolCardInnerProps {
  children: ReactNode;
  onPress?: () => void;
  dense?: boolean;
  className?: string;
}

export function ToolCardInner({
  children,
  onPress,
  dense = false,
  className,
}: ToolCardInnerProps) {
  const base = `${dense ? "rounded-xl p-2.5" : "rounded-2xl p-3"} bg-zinc-900 ${className ?? ""}`;

  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        className={base}
        android_ripple={{ color: "rgba(255,255,255,0.05)" }}
      >
        {children}
      </Pressable>
    );
  }

  return <View className={base}>{children}</View>;
}
