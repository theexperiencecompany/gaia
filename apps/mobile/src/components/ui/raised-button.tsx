/**
 * RaisedButton Component
 * A React Native button with 3D elevation effects using NativeWind
 */

import { useMemo } from "react";
import { Pressable, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { cn } from "@/lib/utils";
import {
  getContrastColor,
  getLuminance,
  parseColor,
  rgbToHex,
} from "@/shared/utils/color-utils";

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

export interface RaisedButtonProps {
  /**
   * Custom color for the button (hex, rgb, rgba)
   */
  color?: string;

  /**
   * Button size variant
   */
  size?: "default" | "sm" | "lg" | "icon";

  /**
   * Button content
   */
  children?: React.ReactNode;

  /**
   * Press handler
   */
  onPress?: () => void;

  /**
   * Disabled state
   */
  disabled?: boolean;

  /**
   * Additional class names (for NativeWind)
   */
  className?: string;
}

/**
 * RaisedButton - 3D elevated button component
 */
export function RaisedButton({
  color = "#00bbff",
  size = "default",
  children,
  onPress,
  disabled = false,
  className = "",
}: RaisedButtonProps) {
  const scale = useSharedValue(1);

  // Generate dynamic styles based on color
  const dynamicStyles = useMemo(() => {
    const rgb = parseColor(color);
    if (!rgb) {
      return {
        backgroundColor: "#00bbff",
        textColor: "#000000",
        borderColor: "rgba(0, 187, 255, 0.5)",
        shadowColor: "#00bbff",
      };
    }

    const luminance = getLuminance(rgb);
    const textColor = getContrastColor(luminance);

    return {
      backgroundColor: rgbToHex(rgb),
      textColor,
      borderColor: `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.5)`,
      shadowColor: rgbToHex(rgb),
      whiteBorder: "rgba(255, 255, 255, 0.4)",
    };
  }, [color]);

  // Get size-specific classes
  const sizeClasses = useMemo(() => {
    switch (size) {
      case "sm":
        return "h-9 px-3 rounded-lg";
      case "lg":
        return "h-11 px-8 rounded-xl";
      case "icon":
        return "h-10 w-10 rounded-xl";
      default:
        return "h-10 px-4 rounded-xl";
    }
  }, [size]);

  // Animated style for press effect
  const animatedStyle = useAnimatedStyle(() => {
    return {
      transform: [{ scale: scale.value }],
    };
  });

  const handlePressIn = () => {
    scale.value = withSpring(0.96, {
      damping: 15,
      stiffness: 300,
    });
  };

  const handlePressOut = () => {
    scale.value = withSpring(1, {
      damping: 15,
      stiffness: 300,
    });
  };

  return (
    <AnimatedPressable
      onPress={onPress}
      onPressIn={handlePressIn}
      onPressOut={handlePressOut}
      disabled={disabled}
      className={cn(
        "flex-row items-center justify-center gap-2 border overflow-hidden relative",
        sizeClasses,
        disabled && "opacity-50",
        className,
      )}
      style={[
        {
          backgroundColor: dynamicStyles.backgroundColor,
          borderColor: dynamicStyles.borderColor,
          shadowColor: dynamicStyles.shadowColor,
          shadowOffset: { width: 0, height: 4 },
          shadowOpacity: 0.3,
          shadowRadius: 5,
          elevation: 6,
        },
        animatedStyle,
      ]}
    >
      {/* Top white border gradient effect */}
      <View
        className="absolute inset-0 border-t"
        style={{
          borderTopColor: dynamicStyles.whiteBorder,
          opacity: 0.6,
        }}
      />

      {/* Content */}
      {typeof children === "string" ? (
        <Text
          className={cn(
            "font-semibold z-10",
            size === "sm" ? "text-sm" : size === "lg" ? "text-base" : "text-sm",
          )}
          style={{ color: dynamicStyles.textColor }}
        >
          {children}
        </Text>
      ) : (
        children
      )}
    </AnimatedPressable>
  );
}
