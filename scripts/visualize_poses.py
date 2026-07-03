#!/usr/bin/env python3
"""Combine a COLMAP sparse model's point cloud with its camera poses into a single
viewable file (PLY and/or GLB), so poses are visible alongside the reconstruction
without needing a separate renderer.

Camera poses are drawn as small frustums (apex at the camera center, base at the
image plane) using each image's actual intrinsics/extrinsics, so their size and
orientation reflect the real camera.

Usage:
    visualize_poses.py <model_dir> [--out-dir DIR] [--format {ply,glb,both}]
                        [--frustum-scale S] [--out-name NAME]
"""
import argparse
import os
import struct
import sys

import numpy as np

try:
    import pycolmap
except ImportError:
    sys.exit("visualize_poses.py requires pycolmap: pip install pycolmap")

FRUSTUM_COLOR = (255, 0, 0)


def load_reconstruction(model_dir):
    rec = pycolmap.Reconstruction(model_dir)
    points_xyz = np.empty((0, 3), dtype=np.float64)
    points_rgb = np.empty((0, 3), dtype=np.uint8)
    if rec.num_points3D() > 0:
        points_xyz = np.array([p.xyz for p in rec.points3D.values()], dtype=np.float64)
        points_rgb = np.array([p.color for p in rec.points3D.values()], dtype=np.uint8)

    images = sorted(rec.images.values(), key=lambda im: im.name)
    poses = []  # list of (R_world_from_cam, t_world_from_cam, width, height, K)
    for img in images:
        if not img.has_pose or not img.has_camera_ptr():
            continue
        cam = rec.camera(img.camera_id)
        world_from_cam = img.cam_from_world().inverse()
        R = world_from_cam.rotation.matrix()
        t = world_from_cam.translation
        K = cam.calibration_matrix()
        poses.append((R, t, cam.width, cam.height, K))

    return points_xyz, points_rgb, poses


def auto_frustum_scale(points_xyz, poses):
    # Camera spacing is the primary signal: sizing off it keeps frustums proportionate to
    # the trajectory regardless of overall scene extent. A bbox-only heuristic overshoots
    # badly on dense/high-fps captures, where many small-baseline cameras sit inside a much
    # larger scene bbox (e.g. diag=15.5 but consecutive cameras only 0.125 apart -> a bbox-based
    # frustum would be ~6x the camera spacing and cameras render as one solid red blob).
    bbox_diag = None
    if points_xyz.shape[0] > 0:
        # Use a 2nd/98th-percentile extent rather than raw min/max: sparse reconstructions
        # often have a handful of far-flung outlier points that would otherwise blow up the
        # bounding box (and thus the frustum size) by 10-100x relative to the actual scene.
        bbox_lo = np.percentile(points_xyz, 2, axis=0)
        bbox_hi = np.percentile(points_xyz, 98, axis=0)
        diag = float(np.linalg.norm(bbox_hi - bbox_lo))
        if diag > 1e-9:
            bbox_diag = diag

    if len(poses) >= 2:
        centers = np.array([p[1] for p in poses])
        dists = np.linalg.norm(np.diff(centers, axis=0), axis=1)
        dists = dists[dists > 1e-9]
        if dists.size > 0:
            scale = float(np.median(dists)) * 1.5
            # Clamp against the scene bbox so sparsely-sampled/object-centric captures (large
            # gaps between consecutive cameras) don't produce oversized frustums either.
            if bbox_diag is not None:
                scale = min(scale, bbox_diag * 0.05)
            return scale

    if bbox_diag is not None:
        return bbox_diag * 0.03
    return 0.2


def frustum_vertices(R, t, width, height, K, scale):
    """Return 5 world-space points: [apex, top-left, top-right, bottom-right, bottom-left]."""
    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]
    corners_px = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float64)
    x = (corners_px[:, 0] - cx) / fx * scale
    y = (corners_px[:, 1] - cy) / fy * scale
    z = np.full(4, scale)
    cam_pts = np.stack([x, y, z], axis=1)  # (4, 3), camera frame
    cam_pts = np.vstack([[0.0, 0.0, 0.0], cam_pts])  # apex + 4 corners
    world_pts = (R @ cam_pts.T).T + t
    return world_pts


def build_combined_geometry(points_xyz, points_rgb, poses, scale):
    """Returns (vertices Nx3 float, colors Nx3 uint8, triangles Mx3 int) covering scene
    points (no faces) followed by per-camera frustum pyramids (with faces)."""
    n_points = points_xyz.shape[0]
    vert_chunks = [points_xyz]
    color_chunks = [points_rgb]
    triangles = []

    offset = n_points
    frustum_color = np.array([FRUSTUM_COLOR], dtype=np.uint8)
    for R, t, width, height, K in poses:
        verts = frustum_vertices(R, t, width, height, K, scale)  # (5,3): apex,tl,tr,br,bl
        vert_chunks.append(verts)
        color_chunks.append(np.repeat(frustum_color, 5, axis=0))
        a, tl, tr, br, bl = offset, offset + 1, offset + 2, offset + 3, offset + 4
        # 4 side faces (apex to each base edge) + 2 base faces to close the pyramid
        triangles.extend([
            (a, tl, tr), (a, tr, br), (a, br, bl), (a, bl, tl),
            (tl, tr, br), (tl, br, bl),
        ])
        offset += 5

    vertices = np.vstack(vert_chunks) if vert_chunks else np.empty((0, 3))
    colors = np.vstack(color_chunks) if color_chunks else np.empty((0, 3), dtype=np.uint8)
    triangles = np.array(triangles, dtype=np.int64) if triangles else np.empty((0, 3), dtype=np.int64)
    return vertices, colors, triangles


def write_ply(path, vertices, colors, triangles):
    n_verts = vertices.shape[0]
    n_faces = triangles.shape[0]
    with open(path, "wb") as f:
        header = (
            "ply\n"
            "format binary_little_endian 1.0\n"
            f"element vertex {n_verts}\n"
            "property float x\n"
            "property float y\n"
            "property float z\n"
            "property uchar red\n"
            "property uchar green\n"
            "property uchar blue\n"
            f"element face {n_faces}\n"
            "property list uchar int vertex_indices\n"
            "end_header\n"
        )
        f.write(header.encode("ascii"))

        vert_dtype = np.dtype([
            ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
            ("r", "u1"), ("g", "u1"), ("b", "u1"),
        ])
        vert_records = np.empty(n_verts, dtype=vert_dtype)
        vert_records["x"] = vertices[:, 0]
        vert_records["y"] = vertices[:, 1]
        vert_records["z"] = vertices[:, 2]
        vert_records["r"] = colors[:, 0]
        vert_records["g"] = colors[:, 1]
        vert_records["b"] = colors[:, 2]
        f.write(vert_records.tobytes())

        for tri in triangles:
            f.write(struct.pack("<B3i", 3, int(tri[0]), int(tri[1]), int(tri[2])))


def write_glb(path, points_xyz, points_rgb, poses, scale):
    import trimesh

    scene = trimesh.Scene()

    if points_xyz.shape[0] > 0:
        rgba = np.hstack([points_rgb, np.full((points_rgb.shape[0], 1), 255, dtype=np.uint8)])
        cloud = trimesh.points.PointCloud(vertices=points_xyz, colors=rgba)
        scene.add_geometry(cloud, node_name="points")

    if poses:
        line_segments = []
        for R, t, width, height, K in poses:
            verts = frustum_vertices(R, t, width, height, K, scale)
            apex, tl, tr, br, bl = verts
            edges = [(apex, tl), (apex, tr), (apex, br), (apex, bl),
                     (tl, tr), (tr, br), (br, bl), (bl, tl)]
            line_segments.extend(edges)
        path_verts = np.array(line_segments, dtype=np.float64).reshape(-1, 3)
        entities = [trimesh.path.entities.Line([2 * i, 2 * i + 1]) for i in range(len(line_segments))]
        colors = np.tile(np.array([FRUSTUM_COLOR + (255,)], dtype=np.uint8), (len(entities), 1))
        cam_path = trimesh.path.Path3D(entities=entities, vertices=path_verts, colors=colors)
        scene.add_geometry(cam_path, node_name="camera_poses")

    scene.export(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", help="Sparse model dir with cameras.bin/images.bin/points3D.bin")
    parser.add_argument("--out-dir", default=None, help="Output dir (default: model_dir)")
    parser.add_argument("--out-name", default="points_with_cameras",
                         help="Output file base name (default: points_with_cameras)")
    parser.add_argument("--format", choices=["ply", "glb", "both"], default="ply")
    parser.add_argument("--frustum-scale", type=float, default=None,
                         help="Camera frustum depth in scene units (default: auto)")
    args = parser.parse_args()

    if not os.path.isfile(os.path.join(args.model_dir, "cameras.bin")):
        sys.exit(f"No cameras.bin found in {args.model_dir}; not a sparse model dir")

    out_dir = args.out_dir or args.model_dir
    os.makedirs(out_dir, exist_ok=True)

    points_xyz, points_rgb, poses = load_reconstruction(args.model_dir)
    if not poses:
        print(f"warning: no registered camera poses found in {args.model_dir}", file=sys.stderr)

    scale = args.frustum_scale if args.frustum_scale is not None else auto_frustum_scale(points_xyz, poses)

    if args.format in ("ply", "both"):
        vertices, colors, triangles = build_combined_geometry(points_xyz, points_rgb, poses, scale)
        ply_path = os.path.join(out_dir, f"{args.out_name}.ply")
        write_ply(ply_path, vertices, colors, triangles)
        print(f"Wrote {ply_path} ({points_xyz.shape[0]} points, {len(poses)} camera frustums)")

    if args.format in ("glb", "both"):
        glb_path = os.path.join(out_dir, f"{args.out_name}.glb")
        write_glb(glb_path, points_xyz, points_rgb, poses, scale)
        print(f"Wrote {glb_path} ({points_xyz.shape[0]} points, {len(poses)} camera frustums)")


if __name__ == "__main__":
    main()
