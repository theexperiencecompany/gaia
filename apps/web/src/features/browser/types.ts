import type {
  BrowserLoginResponse,
  BrowserTaskResponse,
} from "@shared/api/generated";

export type BrowserTaskStatus = BrowserTaskResponse["status"];
export type BrowserTask = BrowserTaskResponse;
export type SavedBrowserLogin = BrowserLoginResponse;
