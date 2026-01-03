import type { ReactNode } from "react";
import { View } from "react-native";

interface AuthCardProps {
  children: ReactNode;
}

export function AuthCard({ children }: AuthCardProps) {
  return (
    <View className="w-full max-w-[450px] bg-[#1a1a1a]/95 rounded-[20px] px-8 py-10 border border-white/10 shadow-2xl elevation-20">
      {children}
    </View>
  );
}
