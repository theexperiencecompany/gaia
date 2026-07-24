# Service Tests

Legacy home for service-layer tests, now nearly empty: the repository-layer
migration re-authored these against the repository seam and moved them into
`unit/services/`. What remains here is `test_user_service.py`, which duplicates
`unit/services/test_user_service.py` and should be folded into it.

Add new service tests to `unit/services/` (mock the domain's `*_repository`
singleton, assert on the service's own behaviour) — not here.
