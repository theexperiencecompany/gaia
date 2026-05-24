#!/usr/bin/env bash
# Full end-to-end: featurize all synthesized + real audio, train both
# architectures, pick the winner via the validation gates, deploy into apps.
#
#   bash scripts/train_and_deploy.sh
#
# Expects:
#   - data/synthetic/{positive,hard_negative,random_negative,real_negative}/*.wav
#     produced by `src.synthesize` + `src.fetch_real_negatives`
#   - ../models/{melspectrogram,embedding_model,silero_vad}.onnx (already present)

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
TRAIN_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$TRAIN_DIR"

source .venv/bin/activate

echo "=== 1. featurize ==="
time python -m src.featurize --data data/synthetic --models ../models --out data/features --workers 8

echo
echo "=== 2. train conv head ==="
mkdir -p ../models
time python -m src.train --features data/features --output ../models/hey_gaia.onnx --arch conv --epochs 80 --batch_size 1024 --lr 1e-3

echo
echo "=== 3. train fc head (for comparison) ==="
time python -m src.train --features data/features --output ../models/hey_gaia_fc.onnx --arch fc --epochs 80 --batch_size 1024 --lr 1e-3 --no_gates

echo
echo "=== 4. validate conv head ==="
python -m src.validate --model ../models/hey_gaia.onnx --models_dir ../models --data data/synthetic --sample_n 800

echo
echo "=== 5. validate fc head ==="
python -m src.validate --model ../models/hey_gaia_fc.onnx --models_dir ../models --data data/synthetic --sample_n 800

echo
echo "=== 6. deploy conv head as production ==="
bash scripts/deploy_model.sh

echo
echo "all done"
