import type { BottomSheetBackdropProps } from "@gorhom/bottom-sheet";
import {
  BottomSheetBackdrop,
  BottomSheetModal,
  useBottomSheetSpringConfigs,
} from "@gorhom/bottom-sheet";
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
  sheetRef: React.RefObject<BottomSheetModal | null>;
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
  const sheetRef = useRef<BottomSheetModal | null>(null);

  useEffect(() => {
    if (isOpen) {
      sheetRef.current?.present();
    } else {
      sheetRef.current?.dismiss();
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
//
// BottomSheetModal portals its content through the BottomSheetModalProvider
// mounted at the app root (see apps/mobile/src/app/_layout.tsx). This keeps
// the sheet's gesture handler tree at root level — sibling to (not nested
// inside) sibling DrawerLayout/Stack gesture trees. Portal here is a logical
// no-op kept for API parity.

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
  enableContentPanningGesture?: boolean;
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
  enableContentPanningGesture = true,
  backgroundStyle,
  handleIndicatorStyle,
}: ContentProps) {
  const { sheetRef: sheetRefCtx, onOpenChange } = useBottomSheetContext();
  const sheetRef = sheetRefCtx as React.RefObject<BottomSheetModal>;

  const animationConfigs = useBottomSheetSpringConfigs({
    damping: 20,
    stiffness: 200,
    mass: 1,
  });

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

  const handleDismiss = useCallback(() => {
    onOpenChange?.(false);
  }, [onOpenChange]);

  return (
    <BottomSheetModal
      ref={sheetRef}
      snapPoints={enableDynamicSizing ? undefined : snapPoints}
      enableDynamicSizing={enableDynamicSizing}
      enablePanDownToClose={enablePanDownToClose}
      enableContentPanningGesture={enableContentPanningGesture}
      backdropComponent={renderBackdrop}
      animationConfigs={animationConfigs}
      backgroundStyle={
        backgroundStyle
          ? (backgroundStyle as StyleProp<ViewStyle>)
          : { backgroundColor: "#18181b" }
      }
      handleIndicatorStyle={
        handleIndicatorStyle
          ? (handleIndicatorStyle as StyleProp<ViewStyle>)
          : { backgroundColor: "#4b5563" }
      }
      onDismiss={handleDismiss}
    >
      <View style={{ flex: 1 }}>{children}</View>
    </BottomSheetModal>
  );
}

// ─── Compound export ──────────────────────────────────────────────────────────

export const BottomSheet = Object.assign(BottomSheetRoot, {
  Portal,
  Overlay,
  Content,
});
