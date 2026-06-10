// Stub module — used to alias unused libraries (e.g. cytoscape) to nothing
// via turbopack.resolveAlias. Importing this returns an empty object/proxy
// that no-ops most usage.
const handler = {
  get: () => () => undefined,
  apply: () => undefined,
  construct: () => ({}),
};
const stub = new Proxy(function () {}, handler);
export default stub;
export const __esModule = true;
