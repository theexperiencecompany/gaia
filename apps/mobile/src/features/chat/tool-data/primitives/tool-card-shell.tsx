import type { ReactNode } from "react";
import { View } from "react-native";

interface ToolCardShellProps {
  children: ReactNode;
  className?: string;
}

export function ToolCardShell({ children, className }: ToolCardShellProps) {
  return (
    <View
      className={`rounded-2xl bg-zinc-800 p-4 mx-4 my-1 ${className ?? ""}`}
    >
      {children}
    </View>
  );
}
