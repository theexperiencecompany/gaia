// The page key and one target's guard, as observed now: equal to the snapshot's
// pair exactly when the decision still refers to this page and element.
(node => { const c=window.__jevFast; return c ? [c.pageKey(), node===null ? null : c.guard(c.nodes.get(node))] : null; })
