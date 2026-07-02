#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $(basename "$0") <video_path> <output_dir> [fps]" >&2
    exit 1
fi

VIDEO_PATH="$1"
OUTPUT_DIR="$2"
FPS="${3:-2}"

mkdir -p "$OUTPUT_DIR"
ffmpeg -i "$VIDEO_PATH" -qscale:v 1 -vf "fps=${FPS}" "${OUTPUT_DIR}/%06d.jpg"

echo "Extracted $(ls "$OUTPUT_DIR" | wc -l) frames -> ${OUTPUT_DIR} (fps=${FPS})"
