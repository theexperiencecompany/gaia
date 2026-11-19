"""Download the memory engine's ONNX models at pinned commits into an image directory.

Run by apps/api/Dockerfile's models stage as: bake_models.py <target dir> <repo>@<sha> ...
Each repo lands in <target dir>/<repo>, the layout app/memory/embeddings.py loads
through MEMORY_BAKED_MODELS_DIR.
"""

import argparse
from pathlib import Path
import shutil

from huggingface_hub import snapshot_download

# Exactly what fastembed reads for these models: tokenizer/config files plus model_file.
FASTEMBED_FILES = [
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "onnx/model.onnx",
]


def bake(target_root: Path, specs: list[str]) -> None:
    """Download each <repo>@<sha> spec into target_root/<repo>, dropping the hub's local metadata."""
    for spec in specs:
        repo, revision = spec.split("@")
        target = target_root / repo
        snapshot_download(repo, revision=revision, local_dir=target, allow_patterns=FASTEMBED_FILES)
        shutil.rmtree(target / ".cache")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_root", type=Path)
    parser.add_argument("specs", nargs="+", metavar="repo@sha")
    args = parser.parse_args()
    bake(args.target_root, args.specs)
