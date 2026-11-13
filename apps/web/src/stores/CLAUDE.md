# Client state: where each kind of state lives

One owner per piece of state. Before adding a store, answer which row you are in.

| State | Lives in | Never in |
|---|---|---|
| Server data (anything a `GET` returns) | TanStack Query: `useQuery` / `useInfiniteQuery` with a `queryKey`, `staleTime` for freshness, `setQueryData` for websocket pushes, `invalidateQueries` after mutations | Zustand. A store with `isLoading` / `error` / `lastFetched` / a TTL is a query cache written by hand: delete it. |
| Local UI state of one component or one modal | `useState` / `useReducer` in that component, or a hook it owns | A global store with a single reader |
| Page filters the URL should reflect (search text, category, tab) | Page state passed down, or URL search params | A global store: it leaks the filter across routes |
| Cross-cutting client state (composer draft, stream progress, auth session, voice mode, sidebar layout) | Zustand in `src/stores/`, named `use<Name>Store`, one file per concern | Duplicating a query result into a store "for instant paint" |
| Imperative global modals opened from outside React (401 interceptor, 402 interceptor) | A store with `open(payload)` / `close()` | Anything else: a plain `isOpen` flag belongs in `uiStore` or the component |

## Zustand rules

- **Selectors, not whole-store reads.** `useXStore((s) => s.field)`; object selectors go through `useShallow`. Export named selector hooks from the store file.
- **Persist the minimum.** `persist` always with `partialize`; never persist derived, volatile, or selection state (a selection that survives a reload can auto-send something the user did not mean).
- **Only data in a store.** No React refs, callbacks, `ReactNode`s, timers or interval handles. A store that needs a timer is component state with `useEffect` cleanup.
- **No derived state.** If two fields always change together, one is computed. If a value falls out of the state, compute it in a selector or `useMemo`.
- **Actions mutate; components don't.** Cap enforcement, toggling, resetting live in the store or reducer, not in the component that renders the control.
- **Devtools on every store** (`devtools(..., { name })`), action names on every `set`.

## TanStack Query rules

- `queryKey` is the identity: include every argument the fetch depends on. Pagination is part of the key.
- `staleTime` is the cache policy. Do not add a store to remember "last fetched".
- Mutations: `useMutation` + `invalidateQueries`, or `setQueryData` for optimistic updates with rollback in `onError`.
- Live updates (websocket) write with `setQueryData` into the same key the page reads.

## Refactoring an existing store (zero-risk protocol)

1. List every reader and writer (`grep -rn use<Name>Store`). Note what each reads.
2. Write the target (query hook, reducer, or slice on an existing store) next to the old store; move readers one file at a time; keep behaviour identical.
3. Delete the old store and its selector hooks in the same change. `tsc` must be clean; every test that mocked the old store is rewritten, not deleted.
4. Verify the affected screens in a browser before the commit, not after.
