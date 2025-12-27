// Main font configuration file
import { anonymousPro } from "./anonymous-pro";
import { inter } from "./inter";
import { ppEditorialNew } from "./pp-editorial-new";

// Export fonts
export { anonymousPro, inter, ppEditorialNew };

// Set Inter as the default font
export const defaultFont = inter;

// The default text font (used for body text)
export const defaultTextFont = inter;

export const defaultMonoFont = anonymousPro;

// Helper function to get font variables
export function getAllFontVariables() {
  return `${inter.variable} ${ppEditorialNew.variable} ${anonymousPro.variable}`;
}
