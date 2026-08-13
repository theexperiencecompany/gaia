/**
 * Emit the contract's scenarios through the REAL bot logging stack.
 *
 * Nothing here is a fixture: the lines land on stdout via `emitBotLogLine` and
 * `withWideEvent`, exactly as a running Discord/Slack/Telegram/WhatsApp bot
 * produces them. `run.py` diffs this output against the Python emitter's, so a
 * change to either sink shows up here as a shape diff.
 *
 * Run through `run.py`; standalone it is `pnpm exec tsx emit_typescript.ts`.
 */
import {
  createBotLogger,
  emitBotLogLine,
} from "../../../libs/shared/ts/src/bots/utils/logger";
import {
  wideLog,
  withWideEvent,
} from "../../../libs/shared/ts/src/bots/utils/wide-events";

const PLATFORM = "discord" as const;
const COMPONENT = "conformance";

const logger = createBotLogger(PLATFORM, COMPONENT);

/** Scenarios 1-5: real-time lines, deliberately outside any boundary. */
function emitRealtimeScenarios(): void {
  logger.info("conformance_info", { op_index: 1 });
  logger.warn("conformance_warning", { error_type: "SlowResponse" });
  logger.error(
    "conformance_error",
    { http_status: 502 },
    new ConnectionError("upstream refused"),
  );
  // `audit` has no createBotLogger method (it is a wide-event concept), so it
  // goes through the same low-level emitter wideLog.audit() uses.
  emitBotLogLine("audit", PLATFORM, COMPONENT, "conformance_audit", {
    actor: "u_1",
  });
  // App code fighting the envelope: both keys must come back as ctx_<key>
  // with the line's real service/level intact.
  logger.error("conformance_collision", {
    service: "HIJACKED",
    level: "HIJACKED",
  });
}

/** Scenarios 6-7: the canonical event, on the success and failure paths. */
async function emitBoundaryScenarios(): Promise<void> {
  await withWideEvent(
    "conformance_success",
    { platform: PLATFORM, component: COMPONENT },
    async () => {
      wideLog.set({ operation: "demo" });
      // Two writes of one namespace, with disjoint keys: both runtimes must
      // ACCUMULATE them. A replacing `set` drops trigger_type here, which is
      // exactly the production bug this scenario exists to pin.
      wideLog.set({ workflow: { id: "wf_1", trigger_type: "schedule" } });
      wideLog.set({ workflow: { status: "success" } });
      wideLog.warning("conformance_warning", { error_type: "SlowResponse" });
      wideLog.error(
        "conformance_error",
        { http_status: 502 },
        new ConnectionError("upstream refused"),
      );
      wideLog.audit("conformance_audit", { actor: "u_1" });
    },
  );

  try {
    await withWideEvent(
      "conformance_failure",
      { platform: PLATFORM, component: COMPONENT },
      async () => {
        throw new RuntimeError("boom {not a format string}");
      },
    );
  } catch {
    // Expected: the boundary re-throws after emitting.
  }
}

/**
 * Named to match the Python exception classes the same scenario throws, so the
 * `error_type` values line up and the diff is about SHAPE, not vocabulary.
 */
class ConnectionError extends Error {
  override name = "ConnectionError";
}

class RuntimeError extends Error {
  override name = "RuntimeError";
}

async function main(): Promise<void> {
  emitRealtimeScenarios();
  await emitBoundaryScenarios();
}

void main();
