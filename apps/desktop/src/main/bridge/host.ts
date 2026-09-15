// Hosts the device bridge tunnel inside the Electron main process — the desktop
// equivalent of the CLI's `gaia bridge up` daemon. It configures bridge-core to
// keep state under userData/bridge and to spawn with the login-shell PATH, then
// supervises a single Tunnel: transient drops reconnect inside Tunnel.run(),
// while an auth exit (401/revoke) clears credentials and goes unpaired instead
// of hammering a dead token.
//
// Pairing (task 2.2) and IPC (task 2.3) are NOT wired here yet — this builds the
// host and its lifecycle only, exposed via the getBridgeHost() singleton getter.

import { EventEmitter } from "node:events";
import { hostname } from "node:os";
import { join } from "node:path";
import type {
  ErrorEnvelope,
  SelfPairResponse,
} from "@gaia/shared/api/generated";
import {
  type BridgeLogger,
  type BridgeStatus,
  clearCredentials,
  configureBridge,
  type DeviceServerState,
  type DeviceServerView,
  deregisterConfiguredServer,
  isPaired,
  loadConfig,
  loadCredentials,
  registerConfiguredServers,
  type ServerConfig,
  saveCredentials,
  Tunnel,
  testServer,
  upsertServer,
} from "@gaia/shared/bridge-core";
import { app, session } from "electron";
import { getApiOrigin } from "../api-origin";
import { resolveLoginShellPath } from "./env";

/** Backend REST prefix — the device endpoints live under `<origin>/api/v1`. */
const API_PREFIX = "/api/v1";

/** Thrown by start() when the device is not yet paired — pairing is task 2.2, so
 * until then start() has nothing to authenticate with. Typed so the IPC layer
 * (task 2.3) can surface "pair first" rather than a generic failure. */
export class BridgeNotPairedError extends Error {
  constructor() {
    super("bridge is not paired — pair this device before starting the tunnel");
    this.name = "BridgeNotPairedError";
  }
}

/** Thrown by pair() when the app has no authenticated session — self-pair mints
 * the device off the signed-in user's `wos_session` cookie, so there is nobody
 * to pair as. Typed so the IPC layer (task 2.3) can surface "sign in first"
 * rather than a generic failure. */
export class BridgeNotAuthenticatedError extends Error {
  constructor() {
    super("sign in to the app first — pairing needs an authenticated session");
    this.name = "BridgeNotAuthenticatedError";
  }
}

/** Consecutive unexpected-throw restarts before the supervisor gives up,
 * mirroring server.ts's Next.js supervisor. Transient network drops never reach
 * this — Tunnel.run() reconnects them internally with jittered backoff. */
const MAX_RESTART_ATTEMPTS = 3;
/** Delay between unexpected-throw restarts. */
const RESTART_DELAY_MS = 2_000;

const STATUS_EVENT = "status";
const SERVERS_EVENT = "servers";

export class BridgeHost {
  private readonly events = new EventEmitter();
  private readonly logger: BridgeLogger = {
    info: (message) => console.log(message),
    error: (message) => console.error(message),
  };

  private tunnel: Tunnel | null = null;
  private stateDirConfigured = false;
  private initialized = false;
  private running = false;
  /** Set before we call tunnel.stop() so the supervise loop can tell a stop WE
   * asked for from an auth exit the tunnel decided on. */
  private intentionalStop = false;

  /** Transient per-server connect state (keyed by server key). A freshly added
   * server is "connecting" while its test+register runs in the background, then
   * settles to "connected" or "error". Servers with no entry (loaded from config
   * at startup) are reported "connected". */
  private readonly serverStates = new Map<
    string,
    { state: DeviceServerState; error?: string }
  >();

  /** Point bridge-core's state (credentials.json, config.json) at userData/bridge
   * and wire the logger. Cheap and idempotent — no shell spawn — so credential-only
   * operations (pair, reconcile, teardown) can read/write state without paying for
   * the login-shell PATH resolution that only the tunnel actually needs. Called at
   * startup by the IPC layer so status()/pair() resolve state without spawning a
   * shell. */
  configureStateDir(): void {
    if (this.stateDirConfigured) return;
    configureBridge({
      stateDir: join(app.getPath("userData"), "bridge"),
      logger: this.logger,
    });
    this.stateDirConfigured = true;
  }

  /** Full configuration for running the tunnel: state dir plus the login-shell
   * PATH/SHELL so spawned npx/uvx/node resolve from a Finder launch. The shell
   * resolution runs a real `$SHELL -ilc`, so it is deferred behind start() rather
   * than paid on every launch. Idempotent — safe to call from every entry point. */
  async init(): Promise<void> {
    if (this.initialized) return;
    this.configureStateDir();
    const loginPath = await resolveLoginShellPath();
    configureBridge({
      env: { ...process.env, PATH: loginPath },
      shell: process.env["SHELL"] || "/bin/zsh",
    });
    this.initialized = true;
  }

  status(): BridgeStatus {
    return {
      paired: isPaired(),
      running: this.running,
      deviceId: loadCredentials()?.deviceId ?? null,
    };
  }

  onStatusChange(listener: (status: BridgeStatus) => void): void {
    this.events.on(STATUS_EVENT, listener);
  }

  offStatusChange(listener: (status: BridgeStatus) => void): void {
    this.events.off(STATUS_EVENT, listener);
  }

  onServersChange(listener: (servers: DeviceServerView[]) => void): void {
    this.events.on(SERVERS_EVENT, listener);
  }

  offServersChange(listener: (servers: DeviceServerView[]) => void): void {
    this.events.off(SERVERS_EVENT, listener);
  }

  /** Start the supervised tunnel. Throws BridgeNotPairedError if unpaired. The
   * tunnel is held in the background; this returns once it is running, not when
   * it stops.
   *
   * Enforces the R5 user binding first: if this device is bound to a different
   * GAIA user than the current session (account switch) or the session is gone
   * (logged out), the stored credential is torn down before anything starts, so
   * the tunnel can never come up under the wrong identity. */
  async start(): Promise<void> {
    await this.init();
    await this.enforceUserBinding();
    if (!isPaired()) throw new BridgeNotPairedError();
    if (this.running) return;
    this.intentionalStop = false;
    this.running = true;
    this.emitStatus();
    // Register the configured servers with the cloud on every start (like
    // `gaia bridge up`), so they appear as integrations and re-create their
    // records if those were lost. Best-effort — a failure must not stop the
    // tunnel from coming up.
    void registerConfiguredServers().catch((err: unknown) =>
      this.logger.error(
        `[bridge] failed to register configured servers: ${err instanceof Error ? err.message : String(err)}`,
      ),
    );
    void this.superviseLoop();
  }

  /** Stop the tunnel we are holding. Marks the stop as intentional so the
   * supervise loop does not mistake the resulting run() return for an auth
   * exit. */
  async stop(): Promise<void> {
    this.intentionalStop = true;
    const tunnel = this.tunnel;
    this.tunnel = null;
    if (tunnel) await tunnel.stop();
    if (this.running) {
      this.running = false;
      this.emitStatus();
    }
  }

  listServers(): DeviceServerView[] {
    return loadConfig().servers.map((server) => {
      const runtime = this.serverStates.get(server.key);
      const view: DeviceServerView = {
        key: server.key,
        name: server.name,
        type: server.type,
        state: runtime?.state ?? "connected",
      };
      if (runtime?.error) view.error = runtime.error;
      return view;
    });
  }

  async addServer(config: ServerConfig): Promise<void> {
    // Save immediately and report the server as "connecting"; the test +
    // cloud-register runs in the background (connectServer) so the card returns
    // at once and shows live state instead of blocking on a spinner. A bad
    // command (e.g. `npm` for `npx`) surfaces as an "error" state with retry,
    // not a modal that hangs until the spawn times out.
    await this.init();
    upsertServer(config);
    this.setServerState(config.key, "connecting");
    void this.connectServer(config);
  }

  /** Background: prove the server starts and speaks MCP, then register it with
   * the cloud. Records the outcome as the server's state. */
  private async connectServer(config: ServerConfig): Promise<void> {
    try {
      await testServer(config);
      await registerConfiguredServers();
      this.setServerState(config.key, "connected");
    } catch (err) {
      this.setServerState(
        config.key,
        "error",
        err instanceof Error ? err.message : String(err),
      );
    }
  }

  /** Retry the background connect for a server that failed, reusing its saved
   * config. */
  async retryServer(key: string): Promise<void> {
    await this.init();
    const config = loadConfig().servers.find((server) => server.key === key);
    if (!config) return;
    this.setServerState(key, "connecting");
    void this.connectServer(config);
  }

  async removeServer(key: string): Promise<boolean> {
    // init() so the state dir points at userData/bridge before we touch config;
    // deregisterConfiguredServer drops it locally and best-effort notifies the
    // cloud (HELLO reconcile is the backstop if that call fails).
    await this.init();
    const removed = await deregisterConfiguredServer(key);
    this.serverStates.delete(key);
    this.emitServers();
    return removed;
  }

  private setServerState(
    key: string,
    state: DeviceServerState,
    error?: string,
  ): void {
    this.serverStates.set(
      key,
      error === undefined ? { state } : { state, error },
    );
    this.emitServers();
  }

  /** Pair this Mac as its own device off the app's authenticated session.
   *
   * Resolves the signed-in GAIA user, then POSTs `/device/self-pair` with the
   * `wos_session` cookie (main-process fetch on `session.defaultSession` — the
   * refresh token is minted and stored here, never handed to the renderer, R4).
   * The returned token is written to userData/bridge/credentials.json (0600)
   * bound to that user id (R5). Idempotent: already paired for the current user
   * is a no-op; paired for a *different* user tears down first (account switch).
   *
   * @throws BridgeNotAuthenticatedError when there is no signed-in session.
   */
  async pair(): Promise<void> {
    this.configureStateDir();
    const apiUrl = getApiOrigin();
    const sessionUserId = await this.resolveSessionUserId(apiUrl);

    const existing = loadCredentials();
    if (existing?.refreshToken) {
      if (existing.userId === sessionUserId) return;
      await this.unbindAndReset("account-switch");
    }

    const res = await session.defaultSession.fetch(
      `${apiUrl}${API_PREFIX}/device/self-pair`,
      {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: hostname(),
          platform: process.platform,
          client: "desktop",
          daemon_version: app.getVersion(),
        }),
      },
    );

    if (res.status === 401) throw new BridgeNotAuthenticatedError();
    if (!res.ok) throw new Error(await errorDetail(res));

    // The refresh token is minted here and written straight to disk, never returned to the renderer (R4).
    const data = (await res.json()) as SelfPairResponse;
    saveCredentials({
      apiUrl,
      deviceId: data.device_id,
      refreshToken: data.refresh_token,
      userId: sessionUserId,
    });
    this.emitStatus();
  }

  /** Tear this device down: stop the tunnel, best-effort revoke it server-side
   * (`DELETE /device/{id}` with the session cookie), then clear the stored
   * credential + user binding and go unpaired. Shared by the logout hook and the
   * account-switch guard; `reason` is for diagnostics only. */
  async unbindAndReset(reason: string): Promise<void> {
    this.configureStateDir();
    const creds = loadCredentials();
    await this.stop();

    if (creds?.deviceId && creds.apiUrl) {
      try {
        await session.defaultSession.fetch(
          `${creds.apiUrl}${API_PREFIX}/device/${creds.deviceId}`,
          { method: "DELETE", credentials: "include" },
        );
      } catch (error) {
        // Best-effort: the session may already be gone (logout) or belong to a
        // different user (switch), so the server-side revoke can fail. The local
        // credential is cleared regardless — a stale server row is harmless.
        this.logger.error(
          `[bridge] server-side device revoke failed during ${reason}: ${errorMessage(error)}`,
        );
      }
    }

    clearCredentials();
    this.logger.info(`[bridge] unbound and reset (${reason})`);
    this.emitStatus();
  }

  /** Reconcile the stored binding against the current session — the launch-time
   * counterpart to start()'s guard, so a logout or account switch that happened
   * while the app was closed is cleaned up on next launch (no cookie "changed"
   * event fires for a cookie removed while the process was dead). No-op when
   * unpaired. Best-effort by contract: callers wrap it so a transient failure to
   * reach the API never blocks startup and never wrongly discards the token. */
  async reconcileUserBinding(): Promise<void> {
    this.configureStateDir();
    await this.enforceUserBinding();
  }

  /** Resolve the signed-in GAIA user id from the app's session cookie.
   * @throws BridgeNotAuthenticatedError on 401 (no valid session). */
  private async resolveSessionUserId(apiUrl: string): Promise<string> {
    const res = await session.defaultSession.fetch(
      `${apiUrl}${API_PREFIX}/user/me`,
      { credentials: "include" },
    );
    if (res.status === 401) throw new BridgeNotAuthenticatedError();
    if (!res.ok) {
      throw new Error(
        `bridge: failed to resolve current user (${await errorDetail(res)})`,
      );
    }
    const data = (await res.json()) as { user_id: string };
    return data.user_id;
  }

  /** If a device is bound but the session no longer matches it, tear it down.
   * A definite 401 means logged out; a user-id mismatch means account switch.
   * A network/transient error is rethrown, NOT treated as logout — otherwise a
   * momentarily unreachable API would wrongly delete a valid credential. */
  private async enforceUserBinding(): Promise<void> {
    const creds = loadCredentials();
    if (!creds?.refreshToken) return;

    let sessionUserId: string;
    try {
      sessionUserId = await this.resolveSessionUserId(getApiOrigin());
    } catch (error) {
      if (error instanceof BridgeNotAuthenticatedError) {
        await this.unbindAndReset("logged-out");
        return;
      }
      throw error;
    }

    if (creds.userId !== sessionUserId)
      await this.unbindAndReset("account-switch");
  }

  /** Run the tunnel until it stops, reconnecting only on an UNEXPECTED throw.
   *
   * Tunnel.run() already loops internally over transient drops and returns only
   * when it stopped: a definitive 401 sets its `stopped` flag and returns (R6
   * auth exit), a REVOKE frame calls its stop() (same), and our own stop() sets
   * it too. So a clean return means one of two things, disambiguated by
   * intentionalStop:
   *   - intentionalStop=true  → we called stop(); done.
   *   - intentionalStop=false → the tunnel hit a 401/revoke; clear credentials,
   *     go unpaired, and wait for a user gesture. NEVER reconnect-loop a 401.
   * A throw is the only unexpected path; it gets a bounded backoff restart. */
  private async superviseLoop(): Promise<void> {
    let restartAttempts = 0;

    while (this.running && !this.intentionalStop) {
      const creds = loadCredentials();
      if (!creds?.refreshToken) {
        this.handleAuthExit();
        return;
      }

      this.tunnel = new Tunnel(creds);
      try {
        await this.tunnel.run();
      } catch (error) {
        this.logger.error(
          `[bridge] tunnel crashed unexpectedly: ${error instanceof Error ? error.message : String(error)}`,
        );
        if (this.intentionalStop) break;
        if (restartAttempts >= MAX_RESTART_ATTEMPTS) {
          this.logger.error(
            `[bridge] giving up after ${MAX_RESTART_ATTEMPTS} restart attempts`,
          );
          break;
        }
        restartAttempts += 1;
        this.logger.info(
          `[bridge] restarting tunnel (attempt ${restartAttempts}/${MAX_RESTART_ATTEMPTS})…`,
        );
        await delay(RESTART_DELAY_MS);
        continue;
      }

      // run() returned without throwing.
      if (this.intentionalStop) break;
      this.handleAuthExit();
      return;
    }

    this.tunnel = null;
    if (this.running) {
      this.running = false;
      this.emitStatus();
    }
  }

  /** The tunnel exited on an auth failure (401) or a revoke frame — the stored
   * credential is dead. Clear it so status() reports unpaired and a later user
   * gesture (re-pair, task 2.2) is required; do not reconnect. */
  private handleAuthExit(): void {
    this.logger.error(
      "[bridge] device no longer authorized (revoked or unpaired) — clearing credentials",
    );
    clearCredentials();
    this.tunnel = null;
    this.running = false;
    this.emitStatus();
  }

  private emitStatus(): void {
    this.events.emit(STATUS_EVENT, this.status());
  }

  private emitServers(): void {
    this.events.emit(SERVERS_EVENT, this.listServers());
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Extract the best human-readable detail from a failed API response: the
 * backend's `detail` field (its HTTPException message, e.g. the 409 device-cap)
 * when the body is JSON, otherwise the status line. */
async function errorDetail(res: Response): Promise<string> {
  try {
    const envelope = (await res.json()) as ErrorEnvelope;
    if (envelope.message) return envelope.message;
  } catch {
    // non-JSON body — fall through to the status line
  }
  return `HTTP ${res.status} ${res.statusText}`;
}

let instance: BridgeHost | null = null;

/** The process-wide BridgeHost singleton. A getter (not a module-level const) so
 * construction stays lazy and the host exists only once the bridge is used. */
export function getBridgeHost(): BridgeHost {
  if (!instance) instance = new BridgeHost();
  return instance;
}
