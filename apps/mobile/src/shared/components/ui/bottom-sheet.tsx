import BottomSheetGorhom, {
  BottomSheetBackdrop,
  type BottomSheetBackdropProps,
  type BottomSheetProps as GorhomBottomSheetProps,
} from "@gorhom/bottom-sheet";
import type { BottomSheetMethods } from "@gorhom/bottom-sheet/lib/typescript/types";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
} from "react";

interface BottomSheetContextValue {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

const BottomSheetContext = createContext<BottomSheetContextValue>({
  isOpen: false,
  onOpenChange: () => {},
});

interface RootProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}

function Root({ isOpen, onOpenChange, children }: RootProps) {
  return (
    <BottomSheetContext.Provider value={{ isOpen, onOpenChange }}>
      {children}
    </BottomSheetContext.Provider>
  );
}

function Portal({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

function Overlay() {
  return null;
}

type ContentProps = Omit<
  GorhomBottomSheetProps,
  "index" | "onChange" | "backdropComponent"
> & { children: ReactNode };

function Content({ children, ...sheetProps }: ContentProps) {
  const { isOpen, onOpenChange } = useContext(BottomSheetContext);
  const sheetRef = useRef<BottomSheetMethods>(null);

  useEffect(() => {
    if (isOpen) {
      sheetRef.current?.expand();
    } else {
      sheetRef.current?.close();
    }
  }, [isOpen]);

  const renderBackdrop = useCallback(
    (props: BottomSheetBackdropProps) => (
      <BottomSheetBackdrop
        {...props}
        disappearsOnIndex={-1}
        appearsOnIndex={0}
        onPress={() => onOpenChange(false)}
      />
    ),
    [onOpenChange],
  );

  return (
    <BottomSheetGorhom
      ref={sheetRef}
      index={-1}
      onChange={(index) => {
        if (index === -1) onOpenChange(false);
      }}
      backdropComponent={renderBackdrop}
      {...sheetProps}
    >
      {children}
    </BottomSheetGorhom>
  );
}

export const BottomSheet = Object.assign(Root, {
  Portal,
  Overlay,
  Content,
});
