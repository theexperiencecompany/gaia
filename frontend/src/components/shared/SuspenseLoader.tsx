import { memo } from "react";

import Spinner from "../ui/spinner";

// Lightweight CSS-only loader to reduce JS execution time
const SuspenseLoader = memo(function SuspenseLoader({
  fullHeight = false,
  fullWidth = false,
}: {
  fullHeight?: boolean;
  fullWidth?: boolean;
}) {
  return (
    <div
      className={`w-full ${fullHeight ? "h-screen" : "h-full"} ${
        fullWidth ? "w-screen" : "w-full"
      } flex items-center justify-center p-3`}
    >
      <Spinner />
    </div>
  );
});

export default SuspenseLoader;
