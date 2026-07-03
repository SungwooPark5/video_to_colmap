# video to colmap

Pipeline that extracts frames from a video and runs COLMAP sparse/dense reconstruction on them.
Uses a Docker environment based on `colmap/colmap:latest` (the official CUDA image) with ffmpeg added on top.

## Build

```bash
docker build -t video-to-colmap .
```

## Run

`work_dir` is a symlink registered in `.gitignore`, used as the workspace for videos/outputs. Point it
at wherever your data lives — a local directory, an external drive, or a network share (NAS/NFS/SMB).

```bash
docker run --gpus all --rm -it \
  -v "$(pwd)/work_dir":/workspace/work_dir \
  video-to-colmap
```

Inside the container (or directly via `docker run ... video-to-colmap pipeline.sh ...`):

```bash
# video -> frames -> sparse reconstruction
pipeline.sh work_dir/<video>.mp4 <workspace_dir> [fps] [--dense] [--exhaustive] [--nas-dest <path>] [--no-visualize] [--visualize-format {ply,glb,both}]

# example: extract at 2fps, including dense reconstruction, then move results out to work_dir
pipeline.sh work_dir/sample.mp4 /workspace/scratch/sample 2 --dense --nas-dest work_dir/sample
```

To run individual steps only:

```bash
extract_frames.sh work_dir/<video>.mp4 <workspace_dir>/images [fps]
run_colmap.sh <workspace_dir>/images <workspace_dir> [--dense] [--exhaustive] [--camera-model <MODEL>] [--nas-dest <path>] [--no-visualize] [--visualize-format {ply,glb,both}]
```

Reconstruction settings (chosen to match the COLMAP GUI defaults, which reconstruct this footage well):
- **`--ImageReader.single_camera 1`** — all frames come from one physical camera, so they share
  intrinsics. Without it, COLMAP fits a separate camera per EXIF-less frame and reconstruction collapses.
- **Camera model `SIMPLE_RADIAL`** (override with `--camera-model`, e.g. `OPENCV`). SIMPLE_RADIAL has a
  single distortion param and is far more stable for uncalibrated video than OPENCV — OPENCV's extra
  distortion DOF let bundle adjustment diverge on low-parallax initial pairs, causing registration to
  fail (symptom: only ~2 frames registered).
- **DSP-SIFT features** — `--SiftExtraction.estimate_affine_shape 1 --SiftExtraction.domain_size_pooling 1`
  for more robust features, plus `--FeatureMatching.guided_matching 1`. These extraction options are
  **CPU-only** in COLMAP, so feature extraction runs on CPU (`--FeatureExtraction.use_gpu 0`); matching
  and bundle adjustment still use the GPU.
- Matching defaults to `sequential_matcher` with loop detection (fast, assumes temporal frame order);
  pass `--exhaustive` for small/object-centric captures where sequential order doesn't imply overlap.

> **Network filesystem note:** if `work_dir` (or any other input path) is a network mount (NFS, SMB, etc.),
> COLMAP's `database.db` uses SQLite mmap, which crashes with `SIGBUS` when opened on some network
> filesystems. Always point `<workspace_dir>` (the COLMAP working directory containing
> `database.db`/`sparse`/`dense`) at a path local to the container, e.g. `/workspace/scratch/<run_name>` —
> never directly at a network-mounted path. The source video/images can stay on the network mount
> (read-only sequential access is fine); use `--nas-dest` to copy final results back out to one.

Outputs:
- `<workspace_dir>/sparse/<model_id>/{cameras,images,points3D}.bin` plus a `points3D.ply` exported alongside each model (always generated, no flag needed)
- `<workspace_dir>/sparse/<model_id>/points_with_cameras.ply` — the same point cloud with each
  registered camera pose drawn as a small red frustum, so poses are visible in one file without a
  separate renderer (always generated, no flag needed; see below to disable or add `.glb`)
- `<workspace_dir>/dense/fused.ply` when `--dense` is used

Pass `--nas-dest <path>` to `run_colmap.sh` (or forward it through `pipeline.sh`) to automatically move the
entire `<workspace_dir>` (database, sparse, dense, plys) to `<path>` once the run finishes, and delete the
local copy.

### Visualizing camera poses

`points_with_cameras.ply` combines the sparse point cloud and camera-pose frustums (red pyramids,
apex at each camera center, sized from the frustum's real intrinsics) into a single file — open it
in any mesh viewer (MeshLab, CloudCompare, Blender) to see both together. Pass `--visualize-format glb`
(or `both`) to also/instead export a `.glb` with the points as a point cloud and poses as red frustum
wireframes. Skip generation entirely with `--no-visualize`.

To run it standalone against an existing model:

```bash
visualize_poses.py <workspace_dir>/sparse/0 [--out-dir DIR] [--format {ply,glb,both}] [--frustum-scale S]
```

`--frustum-scale` sets the frustum depth in scene units; by default it's derived automatically from
the point cloud's bounding-box size (or camera spacing, if there are no points).
