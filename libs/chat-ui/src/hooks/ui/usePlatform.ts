import { useEffect, useState } from "react";

export function usePlatform() {
  const [isMac, setIsMac] = useState(true);

  useEffect(() => {
    // Detect if user is on macOS
    setIsMac(/(Mac|iPhone|iPod|iPad)/i.test(navigator.platform));
  }, []);

  return {
    isMac,
    isWindows: !isMac,
    modifierKeyName: (isMac ? "command" : "ctrl") as "command" | "ctrl",
  };
}
