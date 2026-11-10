"""
Builds the six benchmark datasets as watertight STL files (mm) in ./datasets.
You do not need to run this: the datasets are already included. It is here so the datasets are reproducible.

Extra packages needed only for this script: manifold3d (boolean unions/differences), fast-simplification (mesh decimation).
real_shapes also needs a local copy of https://github.com/alecjacobson/common-3d-test-models (pass its data folder with --real_models_folder).

python generate_datasets.py --real_models_folder path/to/common-3d-test-models/data
"""

import os
import glob
import argparse
import numpy as np
import trimesh
import nesting_core


PARTS_PER_DATASET = 20
SMALLEST_MAX_DIMENSION = 15.0
LARGEST_MAX_DIMENSION = 45.0


def finish_and_save(mesh, folder, file_name, rng):
    """Scale the part so its longest side is random in [15, 45] mm, center it, check it is a single watertight solid, and save it."""
    mesh = mesh.copy()
    mesh.merge_vertices()
    mesh.fix_normals()
    longest_side = float(np.max(mesh.extents))
    target_longest_side = rng.uniform(SMALLEST_MAX_DIMENSION, LARGEST_MAX_DIMENSION)
    mesh.apply_scale(target_longest_side / longest_side)
    mesh.apply_translation(-mesh.bounds.mean(axis=0))
    if not mesh.is_watertight:
        raise ValueError(file_name + " is not watertight")
    if len(mesh.split(only_watertight=False)) != 1:
        raise ValueError(file_name + " is not a single body")
    if mesh.volume <= 0:
        raise ValueError(file_name + " has non-positive volume")
    os.makedirs(folder, exist_ok=True)
    mesh.export(os.path.join(folder, file_name + ".stl"))
    return mesh


def make_cuboids(folder, rng):
    for index in range(PARTS_PER_DATASET):
        extents = rng.uniform(8.0, 45.0, 3)
        mesh = trimesh.creation.box(extents=extents)
        finish_and_save(mesh, folder, "cuboid_" + str(index).zfill(2), rng)


def make_simple_convex(folder, rng):
    shape_types = ["tetrahedron", "triangular_prism", "square_pyramid", "octahedron", "cylinder", "cone", "hexagonal_prism", "wedge"]
    for index in range(PARTS_PER_DATASET):
        shape_type = shape_types[index % len(shape_types)]
        if shape_type == "tetrahedron":
            mesh = trimesh.convex.convex_hull(rng.uniform(0.0, 1.0, (4, 3)))
            while mesh.volume < 0.03:
                mesh = trimesh.convex.convex_hull(rng.uniform(0.0, 1.0, (4, 3)))
        elif shape_type == "triangular_prism":
            triangle = rng.uniform(0.0, 1.0, (3, 2))
            height = rng.uniform(0.3, 1.5)
            points = np.vstack([np.column_stack([triangle, np.zeros(3)]), np.column_stack([triangle, np.full(3, height)])])
            mesh = trimesh.convex.convex_hull(points)
        elif shape_type == "square_pyramid":
            base = rng.uniform(0.5, 1.0)
            height = rng.uniform(0.4, 1.2)
            points = np.array([[0, 0, 0], [base, 0, 0], [0, base, 0], [base, base, 0], [base / 2, base / 2, height]])
            mesh = trimesh.convex.convex_hull(points)
        elif shape_type == "octahedron":
            mesh = trimesh.convex.convex_hull(np.vstack([np.eye(3), -np.eye(3)]) * rng.uniform(0.5, 1.0, 3))
        elif shape_type == "cylinder":
            mesh = trimesh.creation.cylinder(radius=rng.uniform(0.2, 0.6), height=rng.uniform(0.3, 1.5), sections=32)
        elif shape_type == "cone":
            mesh = trimesh.creation.cone(radius=rng.uniform(0.2, 0.6), height=rng.uniform(0.4, 1.5), sections=32)
        elif shape_type == "hexagonal_prism":
            angles = np.arange(6) * np.pi / 3.0
            hexagon = np.column_stack([np.cos(angles), np.sin(angles)]) * rng.uniform(0.3, 0.6)
            height = rng.uniform(0.2, 1.5)
            points = np.vstack([np.column_stack([hexagon, np.zeros(6)]), np.column_stack([hexagon, np.full(6, height)])])
            mesh = trimesh.convex.convex_hull(points)
        else:
            length = rng.uniform(0.5, 1.5)
            width = rng.uniform(0.3, 1.0)
            height = rng.uniform(0.2, 0.8)
            points = np.array([[0, 0, 0], [length, 0, 0], [0, width, 0], [length, width, 0], [0, 0, height], [0, width, height]])
            mesh = trimesh.convex.convex_hull(points)
        finish_and_save(mesh, folder, "simple_convex_" + str(index).zfill(2) + "_" + shape_type, rng)


def make_complex_convex(folder, rng):
    shape_types = ["random_point_hull", "ellipsoid_surface_hull", "clipped_box_hull", "ellipsoid", "capsule"]
    for index in range(PARTS_PER_DATASET):
        shape_type = shape_types[index % len(shape_types)]
        if shape_type == "random_point_hull":
            mesh = trimesh.convex.convex_hull(rng.normal(size=(int(rng.integers(40, 300)), 3)) * rng.uniform(0.4, 1.0, 3))
        elif shape_type == "ellipsoid_surface_hull":
            directions = rng.normal(size=(int(rng.integers(60, 300)), 3))
            directions = directions / np.linalg.norm(directions, axis=1, keepdims=True)
            mesh = trimesh.convex.convex_hull(directions * rng.uniform(0.3, 1.0, 3))
        elif shape_type == "clipped_box_hull":
            box_points = rng.uniform(-1.0, 1.0, (int(rng.integers(80, 300)), 3)) * rng.uniform(0.3, 1.0, 3)
            mesh = trimesh.convex.convex_hull(box_points)
        elif shape_type == "ellipsoid":
            mesh = trimesh.creation.icosphere(subdivisions=3)
            mesh.apply_scale(rng.uniform(0.3, 1.0, 3))
        else:
            mesh = trimesh.creation.capsule(height=rng.uniform(0.5, 1.5), radius=rng.uniform(0.2, 0.5), count=[24, 24])
        rotation = np.eye(4)
        rotation[:3, :3] = nesting_core.random_rotation(rng)
        mesh.apply_transform(rotation)
        finish_and_save(mesh, folder, "complex_convex_" + str(index).zfill(2) + "_" + shape_type, rng)


def make_simple_concave(folder, rng):
    shape_types = ["l_bracket", "t_block", "u_channel", "tube", "i_beam", "cross", "stepped_block", "plate_with_hole"]
    for index in range(PARTS_PER_DATASET):
        shape_type = shape_types[index % len(shape_types)]
        width = rng.uniform(0.6, 1.0)
        thickness = rng.uniform(0.15, 0.35)
        depth = rng.uniform(0.3, 1.2)
        if shape_type == "l_bracket":
            first = trimesh.creation.box(extents=[width, thickness, depth])
            first.apply_translation([width / 2, thickness / 2, 0])
            second = trimesh.creation.box(extents=[thickness, width, depth])
            second.apply_translation([thickness / 2, width / 2, 0])
            mesh = trimesh.boolean.union([first, second], engine="manifold")
        elif shape_type == "t_block":
            top = trimesh.creation.box(extents=[width, thickness, depth])
            top.apply_translation([0, width - thickness / 2, 0])
            stem = trimesh.creation.box(extents=[thickness, width, depth])
            stem.apply_translation([0, width / 2, 0])
            mesh = trimesh.boolean.union([top, stem], engine="manifold")
        elif shape_type == "u_channel":
            outer = trimesh.creation.box(extents=[width, width, depth])
            inner = trimesh.creation.box(extents=[width - 2 * thickness, width, depth * 1.1])
            inner.apply_translation([0, thickness, 0])
            mesh = trimesh.boolean.difference([outer, inner], engine="manifold")
        elif shape_type == "tube":
            outer = trimesh.creation.cylinder(radius=width / 2, height=depth, sections=48)
            inner = trimesh.creation.cylinder(radius=width / 2 - thickness / 2, height=depth * 1.1, sections=48)
            mesh = trimesh.boolean.difference([outer, inner], engine="manifold")
        elif shape_type == "i_beam":
            top = trimesh.creation.box(extents=[width, thickness, depth])
            top.apply_translation([0, width / 2 - thickness / 2, 0])
            bottom = trimesh.creation.box(extents=[width, thickness, depth])
            bottom.apply_translation([0, -width / 2 + thickness / 2, 0])
            web = trimesh.creation.box(extents=[thickness / 2, width, depth])
            mesh = trimesh.boolean.union([top, bottom, web], engine="manifold")
        elif shape_type == "cross":
            first = trimesh.creation.box(extents=[width, thickness, depth])
            second = trimesh.creation.box(extents=[thickness, width, depth])
            mesh = trimesh.boolean.union([first, second], engine="manifold")
        elif shape_type == "stepped_block":
            lower = trimesh.creation.box(extents=[width, width, depth / 2])
            upper = trimesh.creation.box(extents=[width / 2, width, depth / 2])
            upper.apply_translation([-width / 4, 0, depth / 2])
            mesh = trimesh.boolean.union([lower, upper], engine="manifold")
        else:
            plate = trimesh.creation.box(extents=[width, width, thickness])
            hole = trimesh.creation.cylinder(radius=width / 4, height=thickness * 2, sections=48)
            mesh = trimesh.boolean.difference([plate, hole], engine="manifold")
        finish_and_save(mesh, folder, "simple_concave_" + str(index).zfill(2) + "_" + shape_type, rng)


def make_complex_concave(folder, rng):
    """Random connected unions of 3 to 7 rotated primitives, sometimes with holes drilled through."""
    index = 0
    while index < PARTS_PER_DATASET:
        primitive_count = int(rng.integers(3, 8))
        mesh = None
        for primitive_number in range(primitive_count):
            primitive_type = rng.choice(["box", "cylinder", "sphere", "capsule"])
            if primitive_type == "box":
                primitive = trimesh.creation.box(extents=rng.uniform(0.15, 0.7, 3))
            elif primitive_type == "cylinder":
                primitive = trimesh.creation.cylinder(radius=rng.uniform(0.08, 0.3), height=rng.uniform(0.2, 0.8), sections=32)
            elif primitive_type == "sphere":
                primitive = trimesh.creation.icosphere(subdivisions=2, radius=rng.uniform(0.1, 0.3))
            else:
                primitive = trimesh.creation.capsule(height=rng.uniform(0.2, 0.7), radius=rng.uniform(0.07, 0.2), count=[16, 16])
            rotation = np.eye(4)
            rotation[:3, :3] = nesting_core.random_rotation(rng)
            primitive.apply_transform(rotation)
            if mesh is None:
                mesh = primitive
            else:
                # Center the new primitive on a random surface point of the current shape so the union stays connected.
                anchor_point, _ = trimesh.sample.sample_surface(mesh, 1, seed=int(rng.integers(0, 2 ** 31)))
                primitive.apply_translation(anchor_point[0] - primitive.bounds.mean(axis=0))
                mesh = trimesh.boolean.union([mesh, primitive], engine="manifold")
        hole_count = int(rng.integers(0, 3))
        for hole_number in range(hole_count):
            hole = trimesh.creation.cylinder(radius=rng.uniform(0.04, 0.1), height=3.0, sections=24)
            rotation = np.eye(4)
            rotation[:3, :3] = nesting_core.random_rotation(rng)
            hole.apply_transform(rotation)
            hole.apply_translation(mesh.bounds.mean(axis=0) + rng.uniform(-0.15, 0.15, 3))
            mesh = trimesh.boolean.difference([mesh, hole], engine="manifold")
        try:
            finish_and_save(mesh, folder, "complex_concave_" + str(index).zfill(2), rng)
            index += 1
        except ValueError as error:
            print("  retrying complex_concave: " + str(error))


def make_real_shapes(folder, rng, real_models_folder):
    """Public test models (cow, bunny, teapot, ...) remeshed into clean watertight solids of about 4000 triangles."""
    obj_paths = sorted(glob.glob(os.path.join(real_models_folder, "*.obj")))
    obj_paths = [path for path in obj_paths if "beetle-alt" not in path]
    for obj_path in obj_paths:
        model_name = os.path.splitext(os.path.basename(obj_path))[0].replace("-", "_")
        mesh = trimesh.load(obj_path, force="mesh")
        # Remesh through voxels (guarantees a closed solid), then decimate. Decimation sometimes breaks watertightness, so try several resolutions and target sizes and keep the first clean result. Last resort: the raw coarse remesh.
        found_clean_result = False
        for resolution in [80, 60, 45, 35]:
            voxel_pitch = float(np.max(mesh.extents)) / resolution
            solid = mesh.voxelized(voxel_pitch).fill().marching_cubes
            solid.apply_scale(voxel_pitch)
            bodies = solid.split(only_watertight=False)
            solid = max(bodies, key=lambda body: abs(body.volume))
            for target_face_count in [3000, 2500, 3500, 2000, 4000]:
                if target_face_count >= len(solid.faces):
                    continue
                simplified = solid.simplify_quadric_decimation(face_count=target_face_count)
                simplified.merge_vertices()
                if simplified.is_watertight and len(simplified.split(only_watertight=False)) == 1:
                    solid = simplified
                    found_clean_result = True
                    break
            if found_clean_result:
                break
        try:
            finish_and_save(solid, folder, "real_" + model_name, rng)
            print("  saved real_" + model_name + " (" + str(len(solid.faces)) + " faces)")
        except ValueError as error:
            print("  skipped " + model_name + ": " + str(error))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the nesting benchmark datasets.")
    parser.add_argument("--real_models_folder", default=None, help="data folder of a local clone of alecjacobson/common-3d-test-models")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--parts_per_dataset", type=int, default=20)
    parser.add_argument("--output_folder", default=nesting_core.DATASETS_FOLDER, help="where to write the category folders (default: datasets/)")
    arguments = parser.parse_args()
    PARTS_PER_DATASET = arguments.parts_per_dataset
    nesting_core.DATASETS_FOLDER = arguments.output_folder
    random_generator = np.random.default_rng(arguments.seed)
    print("cuboids")
    make_cuboids(os.path.join(nesting_core.DATASETS_FOLDER, "cuboids"), random_generator)
    print("simple_convex")
    make_simple_convex(os.path.join(nesting_core.DATASETS_FOLDER, "simple_convex"), random_generator)
    print("complex_convex")
    make_complex_convex(os.path.join(nesting_core.DATASETS_FOLDER, "complex_convex"), random_generator)
    print("simple_concave")
    make_simple_concave(os.path.join(nesting_core.DATASETS_FOLDER, "simple_concave"), random_generator)
    print("complex_concave")
    make_complex_concave(os.path.join(nesting_core.DATASETS_FOLDER, "complex_concave"), random_generator)
    if arguments.real_models_folder is not None:
        print("real_shapes")
        make_real_shapes(os.path.join(nesting_core.DATASETS_FOLDER, "real_shapes"), random_generator, arguments.real_models_folder)
    print("done")
