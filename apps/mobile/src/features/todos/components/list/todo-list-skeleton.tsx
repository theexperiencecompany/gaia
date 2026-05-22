import { View } from "react-native";

const SKELETON_COUNT = 6;

/**
 * 6 placeholder rows shaped like a `TodoRow`:
 * `bg-zinc-800/30 rounded-2xl h-16 marginVertical: 4` per spec §C.empty.
 */
export function TodoListSkeleton() {
  return (
    <View>
      {Array.from({ length: SKELETON_COUNT }).map((_, i) => {
        const key = `todo-skeleton-${i}`;
        return (
          <View
            key={key}
            style={{
              height: 64,
              marginHorizontal: 16,
              marginVertical: 4,
              borderRadius: 16,
              backgroundColor: "rgba(39,39,42,0.30)",
            }}
          />
        );
      })}
    </View>
  );
}
