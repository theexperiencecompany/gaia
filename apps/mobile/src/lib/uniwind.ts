/**
 * Uniwind-wrapped third-party components
 * Use these instead of the original components to get className support
 */
import { withUniwind } from "uniwind";
import { SafeAreaView } from "react-native-safe-area-context";
import { LinearGradient } from "expo-linear-gradient";
import { GestureHandlerRootView } from "react-native-gesture-handler";

// SafeAreaView with className support
export const StyledSafeAreaView = withUniwind(SafeAreaView);

// LinearGradient with className support (if needed)
export const StyledLinearGradient = withUniwind(LinearGradient);

// GestureHandlerRootView with className support
export const StyledGestureHandlerRootView = withUniwind(GestureHandlerRootView);
