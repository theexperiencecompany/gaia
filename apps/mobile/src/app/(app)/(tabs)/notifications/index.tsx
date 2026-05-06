// Both routes (chat header bell + tab bar bell) render the same screen.
// Re-exporting from (app)/notifications keeps the implementation in one place
// and prevents UI drift between the two entry points.
export { default } from "../../notifications/index";
