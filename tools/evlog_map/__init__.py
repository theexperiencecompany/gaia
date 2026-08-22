"""evlog map, ported to Python — observability scoring for GAIA's FastAPI backend.

A static-analysis port of the ``evlog map`` CLI (https://github.com/HugoRCD/evlog,
MIT) with an adapter for this repo's wide-event runtime (``shared.py.wide_events``).
It answers: if something goes wrong in production tonight, which parts of the
backend will be able to tell you why?

Stdlib only — no app imports, no third-party deps — so it runs on a bare CI
runner exactly like ``tools/lints``.
"""
