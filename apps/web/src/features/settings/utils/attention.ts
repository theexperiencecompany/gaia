/** The most updates a day GAIA may be allowed unprompted: the API's own ceiling. */
export const ATTENTION_BUDGET_MAX = 50;
export const ATTENTION_BUDGET_MARKS = [0, 10, 25, 50];

/** The most check-in times the API accepts. */
export const ATTENTION_CHECKIN_MAX = 6;

/** The time a newly added check-in starts at, until the user changes it. */
export const NEW_CHECKIN_TIME = "09:00";

/** The API stores a time as HH:MM:SS; a time input shows HH:MM. */
export function toTimeInput(time: string): string {
  return time.slice(0, 5);
}
