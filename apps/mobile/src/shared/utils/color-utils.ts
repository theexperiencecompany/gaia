/**
 * Color Utility Functions
 * Helper functions for parsing colors, calculating luminance, and generating contrast colors
 */

export interface RGB {
  r: number;
  g: number;
  b: number;
}

/**
 * Parse a color string (hex, rgb, rgba) into RGB values
 * @param color - Color string in hex (#fff, #ffffff) or rgb/rgba format
 * @returns RGB object or null if invalid
 */
export function parseColor(color: string): RGB | null {
  if (!color) return null;

  // Remove whitespace
  const trimmed = color.trim();

  // Handle hex colors
  if (trimmed.startsWith("#")) {
    const hex = trimmed.substring(1);
    let r: number, g: number, b: number;

    if (hex.length === 3) {
      // Short hex (#fff)
      r = parseInt(hex[0] + hex[0], 16);
      g = parseInt(hex[1] + hex[1], 16);
      b = parseInt(hex[2] + hex[2], 16);
    } else if (hex.length === 6) {
      // Full hex (#ffffff)
      r = parseInt(hex.substring(0, 2), 16);
      g = parseInt(hex.substring(2, 4), 16);
      b = parseInt(hex.substring(4, 6), 16);
    } else {
      return null;
    }

    return { r, g, b };
  }

  // Handle rgb/rgba colors
  if (trimmed.startsWith("rgb")) {
    const match = trimmed.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (match) {
      return {
        r: parseInt(match[1], 10),
        g: parseInt(match[2], 10),
        b: parseInt(match[3], 10),
      };
    }
  }

  return null;
}

/**
 * Calculate the relative luminance of a color
 * Based on WCAG 2.0 formula
 * @param rgb - RGB color object
 * @returns Luminance value between 0 and 1
 */
export function getLuminance(rgb: RGB): number {
  // Convert RGB to sRGB
  const rsRGB = rgb.r / 255;
  const gsRGB = rgb.g / 255;
  const bsRGB = rgb.b / 255;

  // Apply gamma correction
  const r = rsRGB <= 0.03928 ? rsRGB / 12.92 : ((rsRGB + 0.055) / 1.055) ** 2.4;
  const g = gsRGB <= 0.03928 ? gsRGB / 12.92 : ((gsRGB + 0.055) / 1.055) ** 2.4;
  const b = bsRGB <= 0.03928 ? bsRGB / 12.92 : ((bsRGB + 0.055) / 1.055) ** 2.4;

  // Calculate luminance
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * Get contrasting text color (black or white) based on background luminance
 * @param luminance - Background luminance value
 * @returns Contrasting color (#000000 or #ffffff)
 */
export function getContrastColor(luminance: number): string {
  // Use white text for dark backgrounds, black for light backgrounds
  return luminance > 0.5 ? "#000000" : "#ffffff";
}

/**
 * Convert RGB to hex color
 * @param rgb - RGB color object
 * @returns Hex color string
 */
export function rgbToHex(rgb: RGB): string {
  const toHex = (n: number) => {
    const hex = Math.round(n).toString(16);
    return hex.length === 1 ? `0${hex}` : hex;
  };
  return `#${toHex(rgb.r)}${toHex(rgb.g)}${toHex(rgb.b)}`;
}

/**
 * Darken a color by a given percentage
 * @param rgb - RGB color object
 * @param percent - Percentage to darken (0-100)
 * @returns Darkened RGB color
 */
export function darkenColor(rgb: RGB, percent: number): RGB {
  const factor = 1 - percent / 100;
  return {
    r: Math.max(0, Math.min(255, rgb.r * factor)),
    g: Math.max(0, Math.min(255, rgb.g * factor)),
    b: Math.max(0, Math.min(255, rgb.b * factor)),
  };
}

/**
 * Lighten a color by a given percentage
 * @param rgb - RGB color object
 * @param percent - Percentage to lighten (0-100)
 * @returns Lightened RGB color
 */
export function lightenColor(rgb: RGB, percent: number): RGB {
  const factor = percent / 100;
  return {
    r: Math.max(0, Math.min(255, rgb.r + (255 - rgb.r) * factor)),
    g: Math.max(0, Math.min(255, rgb.g + (255 - rgb.g) * factor)),
    b: Math.max(0, Math.min(255, rgb.b + (255 - rgb.b) * factor)),
  };
}
