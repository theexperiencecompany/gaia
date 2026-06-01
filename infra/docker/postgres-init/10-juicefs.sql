-- Create the JuiceFS metadata database used by the API container's sidecar
-- mount. Runs once on first postgres boot (postgres-image init mechanism).
-- For Phase 2 (sharded) add one DB per shard: gaia_juicefs_1 ... gaia_juicefs_15.
CREATE DATABASE gaia_juicefs_0;
