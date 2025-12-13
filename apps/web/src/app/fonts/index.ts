// Main font configuration file
import { instrumentSerif } from "./instrument-serif";
import { inter } from "./inter";

// Export fonts
export { instrumentSerif, inter };

// Set Inter as the default font
export const defaultFont = inter;

// The default text font (used for body text)
export const defaultTextFont = inter;

// Helper function to get font variables
export function getAllFontVariables() {
  return `${inter.variable} ${instrumentSerif.variable}`;
}
