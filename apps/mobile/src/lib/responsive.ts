import { useWindowDimensions } from "react-native";

// Base dimensions (iPhone 8/SE - 375x667)
const BASE_WIDTH = 375;
const BASE_HEIGHT = 667;

/**
 * Scale a value based on screen width
 * Good for: widths, horizontal margins/paddings, icon sizes
 */
export function scale(size: number, width: number): number {
  return (width / BASE_WIDTH) * size;
}

/**
 * Scale a value based on screen height
 * Good for: heights, vertical margins/paddings
 */
export function verticalScale(size: number, height: number): number {
  return (height / BASE_HEIGHT) * size;
}

/**
 * Moderate scaling - applies a fraction of the full scale
 * Good for: font sizes (use factor 0.3), spacing (use factor 0.5)
 *
 * @param size - The base size to scale
 * @param width - Screen width
 * @param factor - How much to scale (0 = no scale, 1 = full scale)
 */
export function moderateScale(
  size: number,
  width: number,
  factor = 0.5,
): number {
  return size + (scale(size, width) - size) * factor;
}

/**
 * Get responsive sidebar width
 * - Small screens (<375px): 85% of screen width
 * - Medium screens (375-428px): 80% of screen width
 * - Large screens (>428px): 75% of screen width, max 340px
 */
export function getSidebarWidth(width: number): number {
  if (width < 375) {
    return Math.round(width * 0.85);
  }
  if (width <= 428) {
    return Math.round(width * 0.8);
  }
  return Math.min(Math.round(width * 0.75), 340);
}

export interface ResponsiveValues {
  // Screen dimensions
  width: number;
  height: number;

  // Device size categories
  isSmallDevice: boolean; // < 375px (iPhone SE 1st gen, older Android)
  isMediumDevice: boolean; // 375-428px (most iPhones, mid-size Android)
  isLargeDevice: boolean; // > 428px (iPhone Pro Max, large Android)

  // Sidebar width
  sidebarWidth: number;

  // Scaling functions bound to current screen dimensions
  scale: (size: number) => number;
  verticalScale: (size: number) => number;
  moderateScale: (size: number, factor?: number) => number;

  // Common scaled values
  spacing: {
    xs: number; // 4
    sm: number; // 8
    md: number; // 16
    lg: number; // 24
    xl: number; // 32
  };

  // Common scaled font sizes
  fontSize: {
    xs: number; // 10
    sm: number; // 12
    md: number; // 14
    base: number; // 16
    lg: number; // 18
    xl: number; // 20
    "2xl": number; // 24
    "3xl": number; // 30
  };

  // Common scaled icon sizes
  iconSize: {
    sm: number; // 16
    md: number; // 20
    lg: number; // 24
    xl: number; // 32
  };
}

/**
 * Hook that provides responsive values and scaling functions
 * based on current screen dimensions.
 *
 * @example
 * const { scale, moderateScale, fontSize, sidebarWidth } = useResponsive();
 *
 * <View style={{ padding: scale(16), width: sidebarWidth }}>
 *   <Text style={{ fontSize: fontSize.lg }}>Hello</Text>
 * </View>
 */
export function useResponsive(): ResponsiveValues {
  const { width, height } = useWindowDimensions();

  const isSmallDevice = width < 375;
  const isMediumDevice = width >= 375 && width <= 428;
  const isLargeDevice = width > 428;

  const boundScale = (size: number) => scale(size, width);
  const boundVerticalScale = (size: number) => verticalScale(size, height);
  const boundModerateScale = (size: number, factor = 0.5) =>
    moderateScale(size, width, factor);

  // Pre-calculated common spacing values (moderate scaling with 0.5 factor)
  const spacing = {
    xs: Math.round(moderateScale(4, width, 0.5)),
    sm: Math.round(moderateScale(8, width, 0.5)),
    md: Math.round(moderateScale(16, width, 0.5)),
    lg: Math.round(moderateScale(24, width, 0.5)),
    xl: Math.round(moderateScale(32, width, 0.5)),
  };

  // Pre-calculated font sizes (conservative scaling with 0.3 factor)
  const fontSize = {
    xs: Math.round(moderateScale(10, width, 0.3)),
    sm: Math.round(moderateScale(12, width, 0.3)),
    md: Math.round(moderateScale(14, width, 0.3)),
    base: Math.round(moderateScale(16, width, 0.3)),
    lg: Math.round(moderateScale(18, width, 0.3)),
    xl: Math.round(moderateScale(20, width, 0.3)),
    "2xl": Math.round(moderateScale(24, width, 0.3)),
    "3xl": Math.round(moderateScale(30, width, 0.3)),
  };

  // Pre-calculated icon sizes (proportional scaling)
  const iconSize = {
    sm: Math.round(scale(16, width)),
    md: Math.round(scale(20, width)),
    lg: Math.round(scale(24, width)),
    xl: Math.round(scale(32, width)),
  };

  return {
    width,
    height,
    isSmallDevice,
    isMediumDevice,
    isLargeDevice,
    sidebarWidth: getSidebarWidth(width),
    scale: boundScale,
    verticalScale: boundVerticalScale,
    moderateScale: boundModerateScale,
    spacing,
    fontSize,
    iconSize,
  };
}

/**
 * Get responsive values without a hook (for use outside components)
 * Note: This won't automatically update on dimension changes
 */
export function getResponsiveValues(
  width: number,
  height: number,
): ResponsiveValues {
  const isSmallDevice = width < 375;
  const isMediumDevice = width >= 375 && width <= 428;
  const isLargeDevice = width > 428;

  const boundScale = (size: number) => scale(size, width);
  const boundVerticalScale = (size: number) => verticalScale(size, height);
  const boundModerateScale = (size: number, factor = 0.5) =>
    moderateScale(size, width, factor);

  const spacing = {
    xs: Math.round(moderateScale(4, width, 0.5)),
    sm: Math.round(moderateScale(8, width, 0.5)),
    md: Math.round(moderateScale(16, width, 0.5)),
    lg: Math.round(moderateScale(24, width, 0.5)),
    xl: Math.round(moderateScale(32, width, 0.5)),
  };

  const fontSize = {
    xs: Math.round(moderateScale(10, width, 0.3)),
    sm: Math.round(moderateScale(12, width, 0.3)),
    md: Math.round(moderateScale(14, width, 0.3)),
    base: Math.round(moderateScale(16, width, 0.3)),
    lg: Math.round(moderateScale(18, width, 0.3)),
    xl: Math.round(moderateScale(20, width, 0.3)),
    "2xl": Math.round(moderateScale(24, width, 0.3)),
    "3xl": Math.round(moderateScale(30, width, 0.3)),
  };

  const iconSize = {
    sm: Math.round(scale(16, width)),
    md: Math.round(scale(20, width)),
    lg: Math.round(scale(24, width)),
    xl: Math.round(scale(32, width)),
  };

  return {
    width,
    height,
    isSmallDevice,
    isMediumDevice,
    isLargeDevice,
    sidebarWidth: getSidebarWidth(width),
    scale: boundScale,
    verticalScale: boundVerticalScale,
    moderateScale: boundModerateScale,
    spacing,
    fontSize,
    iconSize,
  };
}
