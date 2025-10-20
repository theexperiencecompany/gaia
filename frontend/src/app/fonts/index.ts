// Main font configuration file
import { inter } from "./inter";
import { instrumentSerif } from "./instrument-serif";

// Export fonts
export { inter, instrumentSerif };

// Set Inter as the default font
export const defaultFont = inter;

// The default text font (used for body text)
export const defaultTextFont = inter;

// Helper function to get font variables
export function getAllFontVariables() {
  return `${inter.variable} ${instrumentSerif.variable}`;
}
