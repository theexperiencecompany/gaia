/**
 * Uniwind-wrapped third-party components
 * Use these instead of the original components to get className support
 */
import { withUniwind } from "uniwind";
import { SafeAreaView } from "react-native-safe-area-context";
import { LinearGradient } from "expo-linear-gradient";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import {
  BottomSheetView,
  BottomSheetScrollView,
  BottomSheetFlatList,
} from "@gorhom/bottom-sheet";

// SafeAreaView with className support
export const StyledSafeAreaView = withUniwind(SafeAreaView);

// LinearGradient with className support (if needed)
export const StyledLinearGradient = withUniwind(LinearGradient);

// GestureHandlerRootView with className support
export const StyledGestureHandlerRootView = withUniwind(GestureHandlerRootView);

// BottomSheet components with className support
export const StyledBottomSheetView = withUniwind(BottomSheetView);
export const StyledBottomSheetScrollView = withUniwind(BottomSheetScrollView);
export const StyledBottomSheetFlatList = withUniwind(BottomSheetFlatList);

