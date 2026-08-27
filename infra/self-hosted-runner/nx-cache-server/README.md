# nx-cache-server

Shared Nx remote cache for the home runner instances (spec: https://nx.dev/docs/kb/self-hosted-caching).

- Zero-dependency Node script, systemd **user** unit `gaia-nx-cache.service` (installed by `../setup.sh`).
- Binds **loopback only** by default. Widen to the Tailscale address (`NX_CACHE_HOST=100.x.y.z`) only if laptops need it — a remote cache with a single shared token is the cache-poisoning surface (CREEP, CVE-2025-36852) that got Nx's S3 packages deprecated.
- Size-bounded (`NX_CACHE_MAX_BYTES`, default 8 GiB, LRU by access time). Also reported by `prune-cache.sh`.
- Runners get `NX_SELF_HOSTED_REMOTE_CACHE_SERVER` + `NX_SELF_HOSTED_REMOTE_CACHE_ACCESS_TOKEN` in their `.env`; the token lives in `~/ci-cache/nx-remote.token` (mode 600), never in the repo.
- `curl localhost:4222/stats` → hits/misses/puts/bytes.
