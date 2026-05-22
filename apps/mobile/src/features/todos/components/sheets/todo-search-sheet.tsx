import {
  BottomSheetFlatList,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import { AppIcon, Cancel01Icon, Search01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { selectionHaptic } from "@/lib/haptics";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { todoApi } from "../../api/todo-api";
import type { Todo } from "../../types/todo-types";

export interface TodoSearchSheetRef {
  open: () => void;
  close: () => void;
}

interface TodoSearchSheetProps {
  onSelect: (todo: Todo) => void;
}

const DEBOUNCE_MS = 350;

/**
 * Bottom-sheet keyword search.
 *
 * Single search surface for the Tasks tab — debounced 350ms, calls
 * `/todos?q=`. Results render inline; tapping one closes the sheet and
 * opens the detail sheet.
 */
export const TodoSearchSheet = forwardRef<
  TodoSearchSheetRef,
  TodoSearchSheetProps
>(({ onSelect }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Todo[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestIdRef = useRef(0);

  useImperativeHandle(ref, () => ({
    open: () => {
      setIsOpen(true);
      setQuery("");
      setResults([]);
    },
    close: () => setIsOpen(false),
  }));

  const runSearch = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) {
      setResults([]);
      setIsLoading(false);
      return;
    }
    const requestId = ++requestIdRef.current;
    setIsLoading(true);
    try {
      const todos = await todoApi.searchTodos(trimmed);
      if (requestId === requestIdRef.current) {
        setResults(todos);
      }
    } catch {
      if (requestId === requestIdRef.current) {
        setResults([]);
      }
    } finally {
      if (requestId === requestIdRef.current) {
        setIsLoading(false);
      }
    }
  }, []);

  const handleQueryChange = useCallback(
    (text: string) => {
      setQuery(text);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        void runSearch(text);
      }, DEBOUNCE_MS);
    },
    [runSearch],
  );

  const handleClear = () => {
    selectionHaptic();
    setQuery("");
    setResults([]);
  };

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["75%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#18181b" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <View style={{ flex: 1, paddingHorizontal: 16, paddingTop: 8 }}>
            <Text
              style={{
                fontSize: 17,
                fontWeight: "600",
                color: "#f4f4f5",
                paddingBottom: 12,
              }}
            >
              Search tasks
            </Text>

            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 10,
                paddingHorizontal: 12,
                paddingVertical: 4,
                borderRadius: 12,
                backgroundColor: "rgba(39,39,42,0.40)",
              }}
            >
              <AppIcon icon={Search01Icon} size={16} color="#71717a" />
              <BottomSheetTextInput
                value={query}
                onChangeText={handleQueryChange}
                placeholder="Search by title or description…"
                placeholderTextColor="#52525b"
                autoFocus
                style={{
                  flex: 1,
                  fontSize: 15,
                  color: "#f4f4f5",
                  paddingVertical: 10,
                }}
                returnKeyType="search"
              />
              {isLoading ? (
                <ActivityIndicator size="small" color="#71717a" />
              ) : query.length > 0 ? (
                <Pressable onPress={handleClear} hitSlop={8}>
                  <AppIcon icon={Cancel01Icon} size={14} color="#71717a" />
                </Pressable>
              ) : null}
            </View>

            <BottomSheetFlatList<Todo>
              data={results}
              keyExtractor={(item: Todo) => item.id}
              keyboardShouldPersistTaps="handled"
              contentContainerStyle={{ paddingTop: 12 }}
              ListEmptyComponent={
                query.trim() && !isLoading ? (
                  <Text
                    style={{
                      paddingVertical: 24,
                      textAlign: "center",
                      fontSize: 13,
                      color: "#71717a",
                    }}
                  >
                    No matches
                  </Text>
                ) : !query.trim() ? (
                  <Text
                    style={{
                      paddingVertical: 24,
                      textAlign: "center",
                      fontSize: 13,
                      color: "#52525b",
                    }}
                  >
                    Type to start searching
                  </Text>
                ) : null
              }
              renderItem={({ item }: { item: Todo }) => (
                <Pressable
                  onPress={() => {
                    selectionHaptic();
                    setIsOpen(false);
                    onSelect(item);
                  }}
                  style={({ pressed }) => ({
                    paddingVertical: 12,
                    paddingHorizontal: 12,
                    borderRadius: 12,
                    backgroundColor: pressed
                      ? "rgba(63,63,70,0.40)"
                      : "transparent",
                  })}
                >
                  <Text
                    style={{
                      fontSize: 14,
                      fontWeight: "500",
                      color: "#f4f4f5",
                    }}
                    numberOfLines={1}
                  >
                    {item.title}
                  </Text>
                  {item.description ? (
                    <Text
                      style={{
                        fontSize: 12,
                        color: "#a1a1aa",
                        marginTop: 2,
                      }}
                      numberOfLines={1}
                    >
                      {item.description}
                    </Text>
                  ) : null}
                </Pressable>
              )}
            />
          </View>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

TodoSearchSheet.displayName = "TodoSearchSheet";
