import { View, type ViewProps } from "react-native";
import { cn } from "@/lib/utils";

interface DividerProps extends ViewProps {
  orientation?: "horizontal" | "vertical";
  className?: string;
}

export function Divider({
  orientation = "horizontal",
  className,
  style,
  ...rest
}: DividerProps) {
  const base = orientation === "vertical" ? "w-px h-full" : "h-px w-full";
  return (
    <View
      {...rest}
      style={style}
      className={cn(base, "bg-zinc-700/50", className)}
    />
  );
}
