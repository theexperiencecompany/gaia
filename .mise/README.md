# .mise

Configuration for [mise](https://mise.jdx.dev/), a polyglot runtime and tool version manager.

## Structure

- **tool-stubs/** — mise tool stub configs for tools that aren't natively supported by mise registries. Each `.toml` file defines how to install and run a specific tool.
  - `prek.toml` — Stub for [prek](https://github.com/jdx/prek), a fast Rust-based alternative to pre-commit.

## Usage

Tool stubs are picked up automatically by mise. To activate:

```bash
mise install
```

Refer to the [mise tool-stub docs](https://mise.jdx.dev/dev-tools/tool-stubs.html) for authoring new stubs.
