import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

export function SectionHeader({ children }: { children: string }) {
  const { fontSize, spacing } = useResponsive();
  return (
    <Text
      style={{
        fontSize: fontSize.xs,
        color: "#71717a",
        textTransform: "uppercase",
        letterSpacing: 1,
        marginBottom: spacing.xs,
      }}
    >
      {children}
    </Text>
  );
}
