import {
  BottomSheetBackdrop,
  type BottomSheetBackdropProps,
  BottomSheetFlatList,
  BottomSheetModal,
} from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";
import { Image, Pressable, View } from "react-native";
import {
  Cancel01Icon,
  Tick02Icon,
  AppIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { AI_MODELS } from "@/features/chat/data/models";
import type { AIModel } from "@/features/chat/types";
import { useResponsive } from "@/lib/responsive";

export interface ModelPickerSheetRef {
  open: () => void;
  close: () => void;
}

interface ModelPickerSheetProps {
  currentModelId?: string;
  onSelectModel: (modelId: string) => void;
}

export const ModelPickerSheet = forwardRef<
  ModelPickerSheetRef,
  ModelPickerSheetProps
>(({ currentModelId, onSelectModel }, ref) => {
  const bottomSheetRef = useRef<BottomSheetModal>(null);
  const { spacing, fontSize, iconSize } = useResponsive();

  const snapPoints = useMemo(() => ["45%", "70%"], []);

  useImperativeHandle(ref, () => ({
    open: () => {
      bottomSheetRef.current?.present();
    },
    close: () => {
      bottomSheetRef.current?.dismiss();
    },
  }));

  const handleSelect = useCallback(
    (model: AIModel) => {
      onSelectModel(model.id);
      bottomSheetRef.current?.dismiss();
    },
    [onSelectModel],
  );

  const renderBackdrop = useCallback(
    (props: BottomSheetBackdropProps) => (
      <BottomSheetBackdrop
        {...props}
        disappearsOnIndex={-1}
        appearsOnIndex={0}
        opacity={0.5}
      />
    ),
    [],
  );

  const renderModelItem = useCallback(
    ({ item }: { item: AIModel }) => {
      const isSelected = item.id === currentModelId;
      return (
        <Pressable
          onPress={() => handleSelect(item)}
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm + 2,
            marginHorizontal: spacing.sm,
            borderRadius: 12,
            backgroundColor: isSelected
              ? "rgba(0,187,255,0.08)"
              : "transparent",
          }}
          android_ripple={{ color: "rgba(255,255,255,0.08)" }}
        >
          <View
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              backgroundColor: "#27272a",
              alignItems: "center",
              justifyContent: "center",
              marginRight: spacing.sm,
              overflow: "hidden",
            }}
          >
            <Image
              source={{ uri: item.icon }}
              style={{ width: 24, height: 24 }}
              resizeMode="contain"
            />
          </View>

          <View style={{ flex: 1, marginRight: spacing.sm }}>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#e4e4e7",
                fontWeight: "500",
              }}
              numberOfLines={1}
            >
              {item.name}
            </Text>
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#71717a",
                marginTop: 2,
              }}
              numberOfLines={1}
            >
              {item.provider}
            </Text>
          </View>

          {isSelected && (
            <AppIcon icon={Tick02Icon} size={iconSize.sm} color="#00bbff" />
          )}
        </Pressable>
      );
    },
    [currentModelId, handleSelect, spacing, fontSize, iconSize],
  );

  return (
    <BottomSheetModal
      ref={bottomSheetRef}
      snapPoints={snapPoints}
      enableDynamicSizing={false}
      enablePanDownToClose
      backdropComponent={renderBackdrop}
      backgroundStyle={{ backgroundColor: "#141414" }}
      handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
    >
      {/* Header */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.sm,
        }}
      >
        <Text
          style={{
            fontSize: fontSize.lg,
            fontWeight: "600",
            color: "#ffffff",
          }}
        >
          Select Model
        </Text>
        <Pressable
          onPress={() => bottomSheetRef.current?.dismiss()}
          style={{
            width: 32,
            height: 32,
            borderRadius: 16,
            backgroundColor: "rgba(142,142,147,0.1)",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <AppIcon icon={Cancel01Icon} size={18} color="#8e8e93" />
        </Pressable>
      </View>

      {/* Model list */}
      <BottomSheetFlatList
        data={AI_MODELS}
        keyExtractor={(item: AIModel) => item.id}
        renderItem={renderModelItem}
        contentContainerStyle={{ paddingBottom: 24, paddingTop: spacing.xs }}
        showsVerticalScrollIndicator={false}
      />
    </BottomSheetModal>
  );
});

ModelPickerSheet.displayName = "ModelPickerSheet";
