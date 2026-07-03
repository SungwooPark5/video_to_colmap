#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $(basename "$0") <image_dir> <workspace_dir> [--dense] [--exhaustive] [--camera-model <MODEL>] [--nas-dest <path>] [--no-visualize] [--visualize-format {ply,glb,both}]" >&2
    exit 1
}

if [[ $# -lt 2 ]]; then
    usage
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_PATH="$1"
WORKSPACE="$2"
shift 2

DENSE=0
EXHAUSTIVE=0
CAMERA_MODEL="SIMPLE_RADIAL"
NAS_DEST=""
VISUALIZE=1
VISUALIZE_FORMAT="ply"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dense)
            DENSE=1
            shift
            ;;
        --exhaustive)
            EXHAUSTIVE=1
            shift
            ;;
        --camera-model)
            CAMERA_MODEL="${2:?--camera-model requires a model name}"
            shift 2
            ;;
        --nas-dest)
            NAS_DEST="${2:?--nas-dest requires a path}"
            shift 2
            ;;
        --no-visualize)
            VISUALIZE=0
            shift
            ;;
        --visualize-format)
            VISUALIZE_FORMAT="${2:?--visualize-format requires ply|glb|both}"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            ;;
    esac
done

DB_PATH="${WORKSPACE}/database.db"
SPARSE_PATH="${WORKSPACE}/sparse"

mkdir -p "$SPARSE_PATH"

# DSP-SIFT (estimate_affine_shape + domain_size_pooling) yields more robust features and
# is what the COLMAP GUI uses by default. These options are CPU-only (see colmap sift.cc:
# the "Covariant SIFT CPU feature extractor" path), so GPU extraction is disabled here.
colmap feature_extractor \
    --database_path "$DB_PATH" \
    --image_path "$IMAGE_PATH" \
    --ImageReader.camera_model "$CAMERA_MODEL" \
    --ImageReader.single_camera 1 \
    --FeatureExtraction.use_gpu 0 \
    --SiftExtraction.estimate_affine_shape 1 \
    --SiftExtraction.domain_size_pooling 1

if [[ "$EXHAUSTIVE" == "1" ]]; then
    colmap exhaustive_matcher \
        --database_path "$DB_PATH" \
        --FeatureMatching.use_gpu 1 \
        --FeatureMatching.guided_matching 1
else
    colmap sequential_matcher \
        --database_path "$DB_PATH" \
        --FeatureMatching.use_gpu 1 \
        --FeatureMatching.guided_matching 1 \
        --SequentialMatching.loop_detection 1
fi

colmap mapper \
    --database_path "$DB_PATH" \
    --image_path "$IMAGE_PATH" \
    --output_path "$SPARSE_PATH" \
    --Mapper.ba_use_gpu 1

for model_dir in "$SPARSE_PATH"/*/; do
    model_dir="${model_dir%/}"
    if [[ -f "${model_dir}/cameras.bin" ]]; then
        colmap model_converter \
            --input_path "$model_dir" \
            --output_path "${model_dir}/points3D.ply" \
            --output_type PLY

        if [[ "$VISUALIZE" == "1" ]]; then
            python3 "$SCRIPT_DIR/visualize_poses.py" "$model_dir" --format "$VISUALIZE_FORMAT"
        fi
    fi
done

if [[ "$DENSE" == "1" ]]; then
    DENSE_PATH="${WORKSPACE}/dense"
    mkdir -p "$DENSE_PATH"

    colmap image_undistorter \
        --image_path "$IMAGE_PATH" \
        --input_path "${SPARSE_PATH}/0" \
        --output_path "$DENSE_PATH"

    colmap patch_match_stereo --workspace_path "$DENSE_PATH"

    colmap stereo_fusion \
        --workspace_path "$DENSE_PATH" \
        --output_path "${DENSE_PATH}/fused.ply"
fi

if [[ -n "$NAS_DEST" ]]; then
    mkdir -p "$NAS_DEST"
    cp -r "$WORKSPACE"/. "$NAS_DEST"/
    rm -rf "$WORKSPACE"
    echo "Moved results: ${WORKSPACE} -> ${NAS_DEST}"
fi
