/** The API's base URL for links the browser follows itself, such as a file download. */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(
  /\/$/,
  "",
);
