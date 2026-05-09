import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useRef,
  useState,
} from "react";
import { Pressable, Text, View } from "react-native";
import { BottomSheet } from "./bottom-sheet";

interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function useConfirmDialog(): ConfirmFn {
  const fn = useContext(ConfirmContext);
  if (!fn) {
    throw new Error(
      "useConfirmDialog must be used inside <AppConfirmDialogProvider>",
    );
  }
  return fn;
}

interface ProviderProps {
  children: ReactNode;
}

export function AppConfirmDialogProvider({ children }: ProviderProps) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const resolverRef = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((opts) => {
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
      setOptions(opts);
      setIsOpen(true);
    });
  }, []);

  const settle = useCallback((value: boolean) => {
    const resolver = resolverRef.current;
    resolverRef.current = null;
    setIsOpen(false);
    resolver?.(value);
  }, []);

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (!open) settle(false);
    },
    [settle],
  );

  const confirmLabel = options?.confirmLabel ?? "Confirm";
  const cancelLabel = options?.cancelLabel ?? "Cancel";
  const isDestructive = options?.destructive === true;

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <BottomSheet isOpen={isOpen} onOpenChange={handleOpenChange}>
        <BottomSheet.Portal>
          <BottomSheet.Overlay />
          <BottomSheet.Content
            enableDynamicSizing
            backgroundStyle={{ backgroundColor: "#18181b" }}
            handleIndicatorStyle={{ backgroundColor: "#3f3f46" }}
          >
            <View className="px-5 pb-8 pt-2">
              {options ? (
                <>
                  <Text className="text-zinc-100 text-lg font-semibold mb-2">
                    {options.title}
                  </Text>
                  {options.message ? (
                    <Text className="text-zinc-400 text-sm leading-5 mb-6">
                      {options.message}
                    </Text>
                  ) : (
                    <View className="h-4" />
                  )}
                  <View className="flex-row gap-3">
                    <Pressable
                      onPress={() => settle(false)}
                      className="flex-1 h-12 rounded-2xl bg-zinc-800/70 items-center justify-center"
                      accessibilityRole="button"
                      accessibilityLabel={cancelLabel}
                    >
                      <Text className="text-zinc-200 text-sm font-semibold">
                        {cancelLabel}
                      </Text>
                    </Pressable>
                    <Pressable
                      onPress={() => settle(true)}
                      className={
                        isDestructive
                          ? "flex-1 h-12 rounded-2xl bg-red-500 items-center justify-center"
                          : "flex-1 h-12 rounded-2xl bg-[#00bbff] items-center justify-center"
                      }
                      accessibilityRole="button"
                      accessibilityLabel={confirmLabel}
                    >
                      <Text
                        className={
                          isDestructive
                            ? "text-white text-sm font-semibold"
                            : "text-black text-sm font-semibold"
                        }
                      >
                        {confirmLabel}
                      </Text>
                    </Pressable>
                  </View>
                </>
              ) : null}
            </View>
          </BottomSheet.Content>
        </BottomSheet.Portal>
      </BottomSheet>
    </ConfirmContext.Provider>
  );
}
