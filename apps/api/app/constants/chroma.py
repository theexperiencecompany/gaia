"""ChromaDB collection naming, shared by every feature that owns a collection.

One Chroma process can be shared by several concurrent test lanes (see
``scripts/ci/shared-test-services.sh``), and Chroma has no database/namespace
concept — collections are a single flat namespace per server. So the *name* is
the namespace: ``GAIA_CHROMA_COLLECTION_SUFFIX`` is appended to every
collection GAIA creates, which is what keeps lane r0's ``notes_r0`` from
being wiped by lane r1's teardown.

The suffix also predates that use: it separates runs that embed with different
models/dimensions, which cannot share a collection. Empty (the default) is the
production naming, so unset envs reproduce the historical names byte for byte.
"""

import os

CHROMA_COLLECTION_SUFFIX = os.getenv("GAIA_CHROMA_COLLECTION_SUFFIX", "")

# Vector collections not owned by the memory engine (app/constants/memory.py)
# or the files feature (app/constants/files.py).
CHROMA_NOTES_COLLECTION = "notes" + CHROMA_COLLECTION_SUFFIX
CHROMA_CANVAS_COLLECTION = "gaia_canvas" + CHROMA_COLLECTION_SUFFIX
