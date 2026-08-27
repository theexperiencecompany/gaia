---
name: biome-gritql-plugins
description: Use when creating custom lint rules in Biome via GritQL plugins, writing .grit files, or debugging why plugin diagnostics are not firing on violations.
---

# Biome GritQL Plugins

## Overview

Biome 2.x supports custom lint rules via GritQL `.grit` files. Rules use pattern matching against the AST. Several patterns look like they should work but silently don't — this skill documents what actually does.

## File Structure

```text
rules/
  no-barrel-reexport.grit
  no-direct-gaia-icons-import.grit
biome.json   ← plugins registered here at ROOT level
```

Rules live at the **workspace root** in `rules/`. Sub-directory `biome.json` files shadow root plugins (see Config Discovery below).

## .grit File Format

```grit
engine biome(1.0)
language js(typescript, jsx)

`import { $_ } from $source` as $node where {
  $source <: `"some-package"`,
  register_diagnostic(
    span = $node,
    message = "Human-readable error message.",
    severity = "error"
  )
}
```

Severity options: `"error"`, `"warn"`, `"info"`.

## biome.json Registration

```json
{
  "plugins": ["./rules/my-rule.grit"],
  "overrides": [
    {
      "includes": ["src/features/**/index.ts"],
      "plugins": ["./rules/no-barrel-reexport.grit"]
    }
  ]
}
```

Paths are **relative to CWD** when biome runs, not to the config file.

---

## What Works vs What Doesn't

### Import source matching

```grit
// ✅ WORKS — exact string literal in backticks
`import { $_ } from $source` where {
  $source <: `"@my-package"`
}

// ✅ WORKS — multiple sources via or
`import { $_ } from $source` where {
  $source <: or {
    `"@my-package"`,
    `"@my-package/variant-a"`,
    `"@my-package/variant-b"`
  }
}

// ❌ DOES NOT WORK — regex on string content
$source <: r"@my-package"

// ❌ DOES NOT WORK — $_ inside string for partial match
`import { $_ } from "@my-package/$_"`
```

Regex (`r"..."`) and metavariables inside string literals do not match string content. Enumerate every package variant explicitly in an `or` clause.

### Named import specifier matching

```grit
// ✅ WORKS — capture all named imports, match exactly
`import { $_ } from $source`

// ✅ WORKS — positional $_ to find a specific name
or {
  `import { ChevronDown } from "@icons"`,
  `import { ChevronDown, $_ } from "@icons"`,
  `import { $_, ChevronDown } from "@icons"`,
  `import { $_, ChevronDown, $_ } from "@icons"`
} as $node

// ❌ DOES NOT WORK — contains on specifier list
`import { $imports } from "@icons"` where {
  $imports <: contains `ChevronDown`
}

// ❌ DOES NOT WORK — $node <: contains on the full import
`import { $_ } from "@icons"` as $node where {
  $node <: contains `ChevronDown`
}
```

`contains` does not recurse into import/export specifier lists. Use explicit positional patterns (add variants for each position).

### Export patterns

```grit
// ✅ WORKS — star exports
`export * from $source` as $node
`export * as $_ from $source` as $node

// ❌ DOES NOT WORK — metavariables in named export specifiers
`export { $_ } from $source`
`export { $name } from $source`

// ✅ WORKS — exact literal specifier
`export { SpecificName } from "./path"`
```

Named export specifier lists (`export { $_ }`) do not match with metavariables in Biome's GritQL engine. Only `export *` is generically matchable. Named re-exports must be caught via exact patterns or other enforcement.

---

## Critical: Config Discovery and Plugin Shadowing

**Plugins only fire from the config Biome stops at when walking up from the file.**

```text
workspace-root/
  biome.json          ← has plugins: ["./rules/foo.grit"]
  apps/web/
    biome.json        ← extends "//", NO plugins key
    src/
      file.ts         ← Biome finds apps/web/biome.json first → STOPS HERE
```

Result: **root plugins do NOT fire** on `file.ts`. The sub-directory config shadows the root, even with `extends: "//"`. The `extends` mechanism does not inherit plugins.

### Fix: consolidate into root biome.json

Move sub-directory settings to overrides in the root config, then delete the sub-directory `biome.json`:

```json
{
  "files": {
    "maxSize": 2097152,
    "includes": ["!!apps/web/public", "...rest of root excludes..."]
  },
  "overrides": [
    {
      "includes": ["apps/web/**"],
      "linter": { "domains": { "next": "recommended" } }
    }
  ],
  "plugins": ["./rules/my-rule.grit"]
}
```

With no `apps/web/biome.json`, Biome walks up to the root config for all files — plugins fire everywhere.

---

## Debugging Plugins

```bash
# Isolate plugin output (no formatter/import noise)
pnpm biome check --formatter-enabled=false --assist-enabled=false path/to/file.ts

# Verify plugin path resolves (if plugins key is read, wrong path → "Cannot read file.")
# Temporarily set a nonexistent path — if you see the error, the key is active

# Verify rule pattern matches (use absolute path in temp config for fast iteration)
cat > /tmp/test.json << 'EOF'
{
  "$schema": "https://biomejs.dev/schemas/2.3.7/schema.json",
  "plugins": ["/absolute/path/to/rule.grit"]
}
EOF
pnpm biome check --config-path=/tmp/test.json --formatter-enabled=false --assist-enabled=false path/to/file.ts
```

Start with a catch-all pattern to confirm the plugin loads and the rule fires at all:

```grit
engine biome(1.0)
language js(typescript, jsx)

`import $_ from $source` as $node where {
  register_diagnostic(span = $node, message = "catch-all: plugin loaded", severity = "error")
}
```

If the catch-all fires but your real rule doesn't, the issue is the pattern. If neither fires, the plugin isn't being applied (config discovery problem).

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| Plugins in `apps/web/biome.json`, extending root | Delete sub-directory biome.json, consolidate into root overrides |
| Using regex `r"..."` to match package name | List every variant explicitly in `or { }` |
| `contains` to find a specific import specifier | Use positional `$_` patterns for each position |
| `export { $_ } from $source` to catch re-exports | Only `export *` is generically matchable; use `export * from $source` |
| Plugin path relative to config file | Paths are relative to CWD; use `./rules/` from workspace root |
| Testing with formatter on | Add `--formatter-enabled=false --assist-enabled=false` to isolate plugin output |
