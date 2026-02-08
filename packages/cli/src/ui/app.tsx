import type React from "react";
import { InitScreen } from "./screens/init.js";
import { SetupScreen } from "./screens/setup.js";
import { StatusScreen } from "./screens/status.js";
import { ServiceScreen } from "./screens/service.js";
import type { CLIStore } from "./store.js";

export type CLICommand = "init" | "setup" | "status" | "start" | "stop";

interface AppProps {
  store: CLIStore;
  command: CLICommand;
}

export const App: React.FC<AppProps> = ({ store, command }) => {
  switch (command) {
    case "init":
      return <InitScreen store={store} />;
    case "setup":
      return <SetupScreen store={store} />;
    case "status":
      return <StatusScreen store={store} />;
    case "start":
    case "stop":
      return <ServiceScreen store={store} command={command} />;
    default:
      return null;
  }
};
