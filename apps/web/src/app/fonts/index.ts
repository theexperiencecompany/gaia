// Main font configuration file
import { anonymousPro } from "./anonymous-pro";
import { instrumentSerif } from "./instrument-serif";
import { inter } from "./inter";
import { ppEditorialNew } from "./pp-editorial-new";

// Export fonts
export { anonymousPro, ppEditorialNew, instrumentSerif, inter };

// Set Inter as the default font
export const defaultFont = inter;

// The default text font (used for body text)
export const defaultTextFont = inter;

// The default monospace font (used for code blocks)
export const defaultMonoFont = anonymousPro;

// Helper function to get font variables
export function getAllFontVariables() {
  return `${inter.variable} ${ppEditorialNew.variable} ${instrumentSerif.variable} ${anonymousPro.variable}`;
}
