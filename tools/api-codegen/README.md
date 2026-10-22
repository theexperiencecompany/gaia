# api-codegen — why this directory exists, and when it goes

`openapi-typescript` builds TypeScript AST nodes and renders them with `ts.factory` /
`ts.createPrinter` / `ts.createSourceFile`. TypeScript 7's native package ships none of
those — `require("typescript")` returns a version stub — so the generator cannot run on the
compiler the rest of this repo uses. It needs a compiler with the JavaScript API, and this
directory is where that compiler lives (`typescript@5.9.3`, pinned, with its own lockfile).

**It is outside the pnpm workspace on purpose.** `config/.syncpackrc.json` requires one
version per dependency across packages, and `manypkg` requires the most common range, so a
second `typescript` inside the workspace needs a policy exception in two places. Out here
it needs none: every app package stays on 7.x and the workspace checks stay untouched.

This is not a local hack. It is the arrangement upstream documents for TypeScript 7
applications — "run generation in a separate tooling package" — in
[openapi-typescript#2862](https://github.com/openapi-ts/openapi-typescript/pull/2862), with
the underlying incompatibility tracked in
[#2841](https://github.com/openapi-ts/openapi-typescript/issues/2841).

## Delete this directory when #2867 ships

[openapi-typescript#2867](https://github.com/openapi-ts/openapi-typescript/pull/2867) moves
the compiler from a peer dependency to a normal one, so the generator carries its own and
TypeScript 7 applications work directly. Once that is in a published release:

1. `pnpm add -D openapi-typescript@<that version>` at the repo root.
2. Delete `tools/api-codegen/`.
3. Remove the "Install the API codegen toolchain" step from
   `.github/actions/setup-node-pnpm/action.yml`.
4. Point `regenerateApiSchema()` in `scripts/ci/checks.mjs` back at `pnpm exec
   openapi-typescript` and drop the `codegenBin` existence check.

Then the repo has exactly one TypeScript, and no exception anywhere.

## Using it by hand

```sh
pnpm --dir tools/api-codegen install --frozen-lockfile --ignore-workspace
pnpm exec node scripts/ci/checks.mjs api-schema          # regenerates and compares
pnpm exec node scripts/ci/checks.mjs api-schema --write  # rewrite the generated file
```
