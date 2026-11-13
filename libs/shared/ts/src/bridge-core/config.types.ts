// Types for the bridge config: this device's credentials and the MCP servers it exposes.

export interface Credentials {
  apiUrl: string;
  deviceId: string;
  refreshToken: string;
  // The GAIA user this device is bound to, stored atomically with the token so the two
  // never drift. CLI leaves it undefined (no session-user concept); desktop sets it at
  // self-pair time to enforce the account-switch/logout teardown (R5).
  userId?: string;
}

export interface FilesystemServer {
  type: "filesystem";
  key: string;
  name: string;
  allow: string[];
  allowWrite: boolean;
}

export interface UrlServer {
  type: "url";
  key: string;
  name: string;
  url: string;
  // Sent on every request to the local server (e.g. Authorization). Stored 0600
  // like stdio env; never leaves this machine.
  headers?: Record<string, string>;
}

export interface StdioServer {
  type: "stdio";
  key: string;
  name: string;
  command: string;
  args: string[];
  // Resolved values, stored 0600. Captured once at setup (whether typed or
  // pulled from the user's environment) so `up` works from any launch context.
  env: Record<string, string>;
}

export type ServerConfig = FilesystemServer | UrlServer | StdioServer;
