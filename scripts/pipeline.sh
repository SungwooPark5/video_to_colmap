#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $(basename "$0") <video_path> <workspace_dir> [fps] [--dense] [--nas-dest <path>]" >&2
    exit 1
}

if [[ $# -lt 2 ]]; then
    usage
fi

VIDEO_PATH="$1"
WORKSPACE="$2"
shift 2

FPS=2
if [[ $# -gt 0 && "$1" != --* ]]; then
    FPS="$1"
    shift
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_DIR="${WORKSPACE}/images"

"$SCRIPT_DIR/extract_frames.sh" "$VIDEO_PATH" "$IMAGE_DIR" "$FPS"
"$SCRIPT_DIR/run_colmap.sh" "$IMAGE_DIR" "$WORKSPACE" "$@"
