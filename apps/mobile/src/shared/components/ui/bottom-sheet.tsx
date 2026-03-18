import type { BottomSheetBackdropProps } from "@gorhom/bottom-sheet";
import GorhomBottomSheet, { BottomSheetBackdrop } from "@gorhom/bottom-sheet";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
} from "react";
import type { StyleProp, ViewStyle } from "react-native";
import { View } from "react-native";

// ─── Context ─────────────────────────────────────────────────────────────────

interface BottomSheetContextValue {
  sheetRef: React.RefObject<GorhomBottomSheet | null>;
  snapPoints: Array<string | number>;
  enableDynamicSizing: boolean;
  enablePanDownToClose: boolean;
  backgroundStyle?: StyleProp<ViewStyle>;
  handleIndicatorStyle?: StyleProp<ViewStyle>;
  onOpenChange?: (open: boolean) => void;
}

const BottomSheetContext = createContext<BottomSheetContextValue | null>(null);

function useBottomSheetContext(): BottomSheetContextValue {
  const ctx = useContext(BottomSheetContext);
  if (!ctx)
    throw new Error(
      "BottomSheet compound components must be used within <BottomSheet>",
    );
  return ctx;
}

// ─── Root ─────────────────────────────────────────────────────────────────────

interface BottomSheetRootProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}

function BottomSheetRoot({
  isOpen,
  onOpenChange,
  children,
}: BottomSheetRootProps) {
  const sheetRef = useRef<GorhomBottomSheet | null>(null);

  useEffect(() => {
    if (isOpen) {
      sheetRef.current?.expand();
    } else {
      sheetRef.current?.close();
    }
  }, [isOpen]);

  return (
    <BottomSheetContext.Provider
      value={{
        sheetRef,
        snapPoints: ["50%"],
        enableDynamicSizing: true,
        enablePanDownToClose: true,
        onOpenChange,
      }}
    >
      {children}
    </BottomSheetContext.Provider>
  );
}

// ─── Portal (pass-through wrapper) ───────────────────────────────────────────

interface PortalProps {
  children: ReactNode;
}

function Portal({ children }: PortalProps) {
  return <>{children}</>;
}

// ─── Overlay (backdrop) ──────────────────────────────────────────────────────

function Overlay() {
  return null;
}

// ─── Content ─────────────────────────────────────────────────────────────────

interface ContentProps {
  children: ReactNode;
  snapPoints?: Array<string | number>;
  enableDynamicSizing?: boolean;
  enablePanDownToClose?: boolean;
  backgroundStyle?: StyleProp<ViewStyle>;
  handleIndicatorStyle?: StyleProp<ViewStyle>;
  keyboardBehavior?: string;
  keyboardBlurBehavior?: string;
  [key: string]: unknown;
}

function Content({
  children,
  snapPoints = ["50%"],
  enableDynamicSizing = false,
  enablePanDownToClose = true,
  backgroundStyle,
  handleIndicatorStyle,
}: ContentProps) {
  const { sheetRef: sheetRefCtx, onOpenChange } = useBottomSheetContext();
  const sheetRef = sheetRefCtx as React.RefObject<GorhomBottomSheet>;

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

  const handleChange = useCallback(
    (index: number) => {
      if (index === -1) {
        onOpenChange?.(false);
      }
    },
    [onOpenChange],
  );

  return (
    <GorhomBottomSheet
      ref={sheetRef}
      index={-1}
      snapPoints={enableDynamicSizing ? undefined : snapPoints}
      enableDynamicSizing={enableDynamicSizing}
      enablePanDownToClose={enablePanDownToClose}
      backdropComponent={renderBackdrop}
      backgroundStyle={
        backgroundStyle
          ? (backgroundStyle as StyleProp<ViewStyle>)
          : { backgroundColor: "#1c1c1e" }
      }
      handleIndicatorStyle={
        handleIndicatorStyle
          ? (handleIndicatorStyle as StyleProp<ViewStyle>)
          : { backgroundColor: "#4b5563" }
      }
      onChange={handleChange}
    >
      <View style={{ flex: 1 }}>{children}</View>
    </GorhomBottomSheet>
  );
}

// ─── Compound export ──────────────────────────────────────────────────────────

export const BottomSheet = Object.assign(BottomSheetRoot, {
  Portal,
  Overlay,
  Content,
});
