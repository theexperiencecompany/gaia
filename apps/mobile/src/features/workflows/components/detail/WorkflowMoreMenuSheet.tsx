import { BottomSheetView } from "@gorhom/bottom-sheet";
import * as Haptics from "expo-haptics";
import { forwardRef, useImperativeHandle, useState } from "react";
import { Pressable, View } from "react-native";
import type { AnyIcon } from "@/components/icons";
import {
  AppIcon,
  Delete02Icon,
  GlobeIcon,
  MagicWand01Icon,
  PencilEdit02Icon,
  RepeatIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { WORKFLOW_COLORS } from "../../constants/colors";

export interface WorkflowMoreMenuSheetRef {
  open: () => void;
  close: () => void;
}

interface WorkflowMoreMenuSheetProps {
  isPublished: boolean;
  onRegenerate: () => void;
  onGeneratePrompt: () => void;
  onTogglePublish: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

interface MenuRow {
  key: string;
  label: string;
  icon: AnyIcon;
  iconColor?: string;
  labelColor?: string;
  destructive?: boolean;
  onPress: () => void;
}

export const WorkflowMoreMenuSheet = forwardRef<
  WorkflowMoreMenuSheetRef,
  WorkflowMoreMenuSheetProps
>(
  (
    {
      isPublished,
      onRegenerate,
      onGeneratePrompt,
      onTogglePublish,
      onEdit,
      onDelete,
    },
    ref,
  ) => {
    const { spacing, fontSize, moderateScale } = useResponsive();
    const [isOpen, setIsOpen] = useState(false);

    useImperativeHandle(ref, () => ({
      open: () => setIsOpen(true),
      close: () => setIsOpen(false),
    }));

    const handleAction = (callback: () => void) => {
      void Haptics.selectionAsync();
      setIsOpen(false);
      // Defer the parent action until the sheet's dismiss animation completes
      // — opening a follow-up modal/sheet while another is dismissing causes
      // the second to no-op on Android.
      setTimeout(callback, 240);
    };

    const primaryRows: MenuRow[] = [
      {
        key: "regenerate",
        label: "Regenerate Steps",
        icon: RepeatIcon,
        onPress: () => handleAction(onRegenerate),
      },
      {
        key: "generate_prompt",
        label: "Generate Prompt",
        icon: MagicWand01Icon,
        onPress: () => handleAction(onGeneratePrompt),
      },
      {
        key: "publish",
        label: isPublished ? "Unpublish" : "Publish Workflow",
        icon: GlobeIcon,
        onPress: () => handleAction(onTogglePublish),
      },
      {
        key: "edit",
        label: "Edit",
        icon: PencilEdit02Icon,
        onPress: () => handleAction(onEdit),
      },
    ];

    const destructiveRow: MenuRow = {
      key: "delete",
      label: "Delete Workflow",
      icon: Delete02Icon,
      iconColor: WORKFLOW_COLORS.dangerText,
      labelColor: WORKFLOW_COLORS.dangerText,
      destructive: true,
      onPress: () => handleAction(onDelete),
    };

    const renderRow = (row: MenuRow) => (
      <Pressable
        key={row.key}
        onPress={row.onPress}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.md,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm + 4,
          borderRadius: moderateScale(12, 0.5),
          backgroundColor: pressed
            ? WORKFLOW_COLORS.surfaceTinted
            : "transparent",
        })}
      >
        <View
          style={{
            width: 28,
            height: 28,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: row.destructive
              ? WORKFLOW_COLORS.dangerBg
              : WORKFLOW_COLORS.surfaceMuted,
          }}
        >
          <AppIcon
            icon={row.icon}
            size={15}
            color={row.iconColor ?? WORKFLOW_COLORS.textPrimary}
          />
        </View>
        <Text
          style={{
            fontSize: fontSize.sm,
            fontWeight: "500",
            color: row.labelColor ?? WORKFLOW_COLORS.textPrimary,
          }}
        >
          {row.label}
        </Text>
      </Pressable>
    );

    return (
      <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
        <BottomSheet.Portal>
          <BottomSheet.Overlay />
          <BottomSheet.Content
            enableDynamicSizing
            enablePanDownToClose
            backgroundStyle={{ backgroundColor: "#141418" }}
            handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
          >
            <BottomSheetView
              style={{
                paddingHorizontal: spacing.md,
                paddingTop: spacing.sm,
                paddingBottom: spacing.xl,
                gap: 4,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: WORKFLOW_COLORS.textFaint,
                  textTransform: "uppercase",
                  letterSpacing: 1.2,
                  fontWeight: "600",
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.xs,
                }}
              >
                Workflow Options
              </Text>

              {primaryRows.map(renderRow)}

              <View
                style={{
                  height: 1,
                  marginVertical: 6,
                  marginHorizontal: spacing.md,
                  backgroundColor: WORKFLOW_COLORS.borderSubtle,
                }}
              />

              {renderRow(destructiveRow)}
            </BottomSheetView>
          </BottomSheet.Content>
        </BottomSheet.Portal>
      </BottomSheet>
    );
  },
);

WorkflowMoreMenuSheet.displayName = "WorkflowMoreMenuSheet";
