// Color utility functions for the RaisedButton component

// Basic CSS color names for server-side parsing
const CSS_COLOR_NAMES: Record<string, [number, number, number]> = {
  black: [0, 0, 0],
  white: [255, 255, 255],
  red: [255, 0, 0],
  green: [0, 128, 0],
  blue: [0, 0, 255],
  yellow: [255, 255, 0],
  cyan: [0, 255, 255],
  magenta: [255, 0, 255],
  gray: [128, 128, 128],
  grey: [128, 128, 128],
  orange: [255, 165, 0],
  purple: [128, 0, 128],
  pink: [255, 192, 203],
  brown: [165, 42, 42],
  navy: [0, 0, 128],
  teal: [0, 128, 128],
  olive: [128, 128, 0],
  maroon: [128, 0, 0],
  silver: [192, 192, 192],
  lime: [0, 255, 0],
  aqua: [0, 255, 255],
  fuchsia: [255, 0, 255],
};

/**
 * Convert hex color to RGB object
 * @param hex Hex color string (e.g. "#ff0000" or "ff0000")
 * @returns RGB object or null if invalid
 */
export function hexToRgb(
  hex: string,
): { r: number; g: number; b: number } | null {
  // Handle various hex formats
  const normalizedHex = hex.charAt(0) === "#" ? hex.substring(1) : hex;

  // Handle shorthand hex (#rgb)
  if (normalizedHex.length === 3) {
    const r = parseInt(normalizedHex.charAt(0) + normalizedHex.charAt(0), 16);
    const g = parseInt(normalizedHex.charAt(1) + normalizedHex.charAt(1), 16);
    const b = parseInt(normalizedHex.charAt(2) + normalizedHex.charAt(2), 16);
    return { r, g, b };
  }

  // Handle standard hex (#rrggbb)
  if (normalizedHex.length === 6) {
    const r = parseInt(normalizedHex.substring(0, 2), 16);
    const g = parseInt(normalizedHex.substring(2, 4), 16);
    const b = parseInt(normalizedHex.substring(4, 6), 16);
    return { r, g, b };
  }

  // Handle CSS color names and other formats
  if (normalizedHex !== hex) {
    try {
      // Create a temporary element to use the browser's color parsing
      const tempElement = document.createElement("div");
      tempElement.style.color = hex;
      document.body.appendChild(tempElement);

      // Get computed style
      const computedColor = window.getComputedStyle(tempElement).color;
      document.body.removeChild(tempElement);

      // Parse rgb/rgba format
      const rgbMatch = computedColor.match(
        /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\)/,
      );
      if (rgbMatch) {
        return {
          r: parseInt(rgbMatch[1], 10),
          g: parseInt(rgbMatch[2], 10),
          b: parseInt(rgbMatch[3], 10),
        };
      }
    } catch (e) {
      console.error("Error processing color name:", e);
    }
  }

  return null;
}

/**
 * Calculate the relative luminance of a color
 * Using the formula from WCAG 2.0
 * @param rgb RGB color object
 * @returns Luminance value (0-1)
 */
export function getLuminance(rgb: { r: number; g: number; b: number }): number {
  const { r, g, b } = rgb;

  // Convert RGB to sRGB
  const sR = r / 255;
  const sG = g / 255;
  const sB = b / 255;

  // Calculate luminance components
  const R = sR <= 0.03928 ? sR / 12.92 : ((sR + 0.055) / 1.055) ** 2.4;
  const G = sG <= 0.03928 ? sG / 12.92 : ((sG + 0.055) / 1.055) ** 2.4;
  const B = sB <= 0.03928 ? sB / 12.92 : ((sB + 0.055) / 1.055) ** 2.4;

  // Calculate relative luminance (WCAG formula)
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

/**
 * Determine contrasting text color (black or white) based on background luminance
 * @param luminance Background color luminance
 * @returns "#ffffff" for dark backgrounds, "#000000" for light backgrounds
 */
export function getContrastColor(luminance: number): string {
  // WCAG 2.0 contrast threshold (simplified)
  return luminance > 0.5 ? "#000000" : "#ffffff";
}

/**
 * Parse any CSS color format into RGB
 * @param color Any valid CSS color string
 * @returns RGB object or null if invalid
 */
export function parseColor(
  color: string,
): { r: number; g: number; b: number } | null {
  // First try hex parsing
  const hexResult = hexToRgb(color);
  if (hexResult) return hexResult;

  try {
    // Handle CSS named colors
    if (typeof document !== "undefined") {
      // Create a temporary element to use the browser's color parsing
      const tempElement = document.createElement("div");
      tempElement.style.color = color;
      document.body.appendChild(tempElement);

      // Get computed style
      const computedColor = window.getComputedStyle(tempElement).color;
      document.body.removeChild(tempElement);

      // Parse rgb/rgba format
      const rgbMatch = computedColor.match(
        /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\)/,
      );
      if (rgbMatch) {
        return {
          r: parseInt(rgbMatch[1], 10),
          g: parseInt(rgbMatch[2], 10),
          b: parseInt(rgbMatch[3], 10),
        };
      }
    } else {
      // Server-side: use basic color name mapping
      const colorMap: Record<string, { r: number; g: number; b: number }> = {};
      for (const [name, rgb] of Object.entries(CSS_COLOR_NAMES)) {
        const [r, g, b] = rgb;
        colorMap[name.toLowerCase()] = { r, g, b };
      }

      // Check if the color name exists in our map
      const normalizedColorName = color.toLowerCase().trim();
      if (colorMap[normalizedColorName]) {
        return colorMap[normalizedColorName];
      }
    }

    // Try to parse rgb/rgba directly
    const rgbDirectMatch = color.match(
      /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\)/,
    );
    if (rgbDirectMatch) {
      return {
        r: parseInt(rgbDirectMatch[1], 10),
        g: parseInt(rgbDirectMatch[2], 10),
        b: parseInt(rgbDirectMatch[3], 10),
      };
    }

    // Try to parse hsl/hsla format
    const hslMatch = color.match(
      /hsla?\((\d+),\s*(\d+)%,\s*(\d+)%(?:,\s*[\d.]+)?\)/,
    );
    if (hslMatch) {
      const h = parseInt(hslMatch[1], 10) / 360;
      const s = parseInt(hslMatch[2], 10) / 100;
      const l = parseInt(hslMatch[3], 10) / 100;

      // Convert HSL to RGB
      return hslToRgb(h, s, l);
    }
  } catch (e) {
    console.error("Error processing color:", e);
  }

  return null;
}

/**
 * Convert HSL color to RGB
 * @param h Hue (0-1)
 * @param s Saturation (0-1)
 * @param l Lightness (0-1)
 * @returns RGB color object
 */
export function hslToRgb(
  h: number,
  s: number,
  l: number,
): { r: number; g: number; b: number } {
  let r: number, g: number, b: number;

  if (s === 0) {
    // Achromatic (gray)
    r = g = b = l * 255;
  } else {
    const hue2rgb = (p: number, q: number, t: number): number => {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };

    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;

    r = hue2rgb(p, q, h + 1 / 3) * 255;
    g = hue2rgb(p, q, h) * 255;
    b = hue2rgb(p, q, h - 1 / 3) * 255;
  }

  return {
    r: Math.round(r),
    g: Math.round(g),
    b: Math.round(b),
  };
}
