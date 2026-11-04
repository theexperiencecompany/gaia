// Main font configuration file
import { aeonik } from "./aeonik";
import { geistMono } from "./geist-mono";
import { inter } from "./inter";

// Export fonts
export { aeonik, geistMono, inter };

// Set Inter as the default font
export const defaultFont = inter;

// Helper function to get font variables
export function getAllFontVariables() {
  return `${inter.variable} ${geistMono.variable} ${aeonik.variable}`;
}
