// Metro resolves `global.css` (Tailwind/uniwind) at bundle time; TypeScript has
// no knowledge of it. TypeScript 6 turned on `noUncheckedSideEffectImports` by
// default, which rejects a side-effect import that resolves to no declaration,
// so the stylesheet modules are declared here. The web app gets the equivalent
// declaration from the `next-env.d.ts` Next.js generates for it.
declare module "*.css" {}
