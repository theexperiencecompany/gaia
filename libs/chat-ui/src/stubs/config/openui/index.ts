/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 *
 * The real `config/openui/genericLibrary.tsx` registers ~40 OpenUI component
 * defs via @openuidev/react-lang. This stub exposes a minimal `genericLibrary`
 * with no components — consumers (OpenUIRenderer) will compile but render nothing.
 *
 * NOTE: tsconfig path alias `@/config/openui/*` currently resolves to
 * `src/config/openui/*` (not into stubs). To use this stub, update the alias to
 * point at `src/stubs/config/openui/*`, or move/copy this file under
 * `src/config/openui/` at integration time.
 */
import { createLibrary } from "@openuidev/react-lang";

export const genericLibrary = createLibrary({
  components: [],
  componentGroups: [],
});

// Re-export stub views — real source exports many `*View` React components from
// subfolders. Consumers that import them by name should be migrated to the real
// impl; this stub does not enumerate them.
