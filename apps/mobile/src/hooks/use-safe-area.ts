import type { ViewStyle } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

interface SafeAreaHelpers {
  topInset: number;
  bottomInset: number;
  leftInset: number;
  rightInset: number;
  horizontalInsets: { paddingLeft: number; paddingRight: number };
  containerStyle: ViewStyle;
}

export function useSafeArea(): SafeAreaHelpers {
  const insets = useSafeAreaInsets();

  return {
    topInset: insets.top,
    bottomInset: insets.bottom,
    leftInset: insets.left,
    rightInset: insets.right,
    horizontalInsets: {
      paddingLeft: insets.left,
      paddingRight: insets.right,
    },
    containerStyle: {
      paddingTop: insets.top,
      paddingBottom: insets.bottom,
    },
  };
}
