"""Model-onboarding tests bill real tokens by design — the root hermetic fence
(tests/conftest.py) must leave the model keys they need untouched. Declared at
import time, before the session fence runs."""

import os

os.environ.setdefault("HERMETIC_ALLOW_KEYS", "OPENROUTER_API_KEY")
