import {
  BottomSheetFlatList,
  BottomSheetScrollView,
  BottomSheetView,
} from "@gorhom/bottom-sheet";
import { LinearGradient } from "expo-linear-gradient";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaView } from "react-native-safe-area-context";
import { withUniwind } from "uniwind";

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
