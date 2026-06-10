import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { WORKFLOW_COLORS } from "../constants/colors";

interface SectionHeaderProps {
  title: string;
  description?: string;
  count?: number;
}

/**
 * Section header used across the workflows surface. Mirrors the web pattern:
 * `text-base font-semibold` + small flat count chip on the trailing edge of
 * the title row.
 */
export function SectionHeader({
  title,
  description,
  count,
}: SectionHeaderProps) {
  const { fontSize } = useResponsive();

  return (
    <View style={{ gap: 4 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "600",
            color: WORKFLOW_COLORS.textPrimary,
          }}
        >
          {title}
        </Text>
        {count !== undefined && count > 0 ? (
          <View
            style={{
              borderRadius: 999,
              backgroundColor: WORKFLOW_COLORS.cardBgActive,
              paddingHorizontal: 6,
              paddingVertical: 0,
              minWidth: 22,
              height: 16,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Text
              style={{
                fontSize: 11,
                lineHeight: 14,
                fontWeight: "600",
                color: WORKFLOW_COLORS.textMuted,
                includeFontPadding: false,
                textAlignVertical: "center",
              }}
            >
              {count}
            </Text>
          </View>
        ) : null}
      </View>
      {description ? (
        <Text
          style={{
            fontSize: fontSize.sm,
            fontWeight: "400",
            color: WORKFLOW_COLORS.textZinc500,
          }}
        >
          {description}
        </Text>
      ) : null}
    </View>
  );
}
