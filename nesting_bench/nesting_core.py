"""
Shared code for the nesting benchmark: loading parts, rotations, voxelizing, and scoring a packing.

Units are millimeters everywhere.

A "part" is a dict made by load_parts():
    name, mesh (trimesh, centered on its bounding box), volume, obb_rotation, obb_extents, obb_volume,
    density (g/cm^3), mass (g), center_of_mass_local, inertia_local (g*mm^2), cloud_points
A "placement" is a dict made by an algorithm:
    part_index (index into the selected parts list), rotation (3x3), translation (3,)
    world position of a vertex v is: rotation @ v + translation
"""

import os
import glob
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation


DATASETS_FOLDER = os.environ.get("NESTING_DATASETS_FOLDER", os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets"))


def list_datasets():
    dataset_names = [name for name in sorted(os.listdir(DATASETS_FOLDER)) if os.path.isdir(os.path.join(DATASETS_FOLDER, name))]
    return dataset_names


def load_parts(dataset_name, cloud_spacing, default_density):
    """Load every STL in one dataset folder and precompute what the algorithms and checks need.
    Density is in g/cm^3. Every part gets default_density, unless the dataset folder has a densities.csv with lines "part_name,density" (no header) to override single parts."""
    stl_paths = sorted(glob.glob(os.path.join(DATASETS_FOLDER, dataset_name, "*.stl")))
    if len(stl_paths) == 0:
        raise FileNotFoundError("No STL files found in " + os.path.join(DATASETS_FOLDER, dataset_name))
    density_overrides = {}
    density_file_path = os.path.join(DATASETS_FOLDER, dataset_name, "densities.csv")
    if os.path.exists(density_file_path):
        with open(density_file_path) as density_file:
            for line in density_file:
                if line.strip() == "":
                    continue
                part_name, density_text = line.strip().split(",")
                density_overrides[part_name.strip()] = float(density_text)
    parts = []
    for stl_path in stl_paths:
        mesh = trimesh.load(stl_path, force="mesh")
        mesh.apply_translation(-mesh.bounds.mean(axis=0))
        # Dense point cloud (filled interior voxels + surface samples + vertices). Rotating and binning this cloud is how we voxelize a part at any angle quickly.
        interior_points = mesh.voxelized(cloud_spacing).fill().points
        surface_point_count = int(mesh.area / (cloud_spacing * cloud_spacing)) + 200
        surface_points, _ = trimesh.sample.sample_surface(mesh, surface_point_count, seed=0)
        cloud_points = np.vstack([interior_points, surface_points, mesh.vertices])
        # Minimum volume oriented bounding box: obb_rotation turns the part so its tightest box lines up with the x, y, z axes.
        obb_transform, obb_extents = trimesh.bounds.oriented_bounds(mesh)
        part = {}
        part["name"] = os.path.splitext(os.path.basename(stl_path))[0]
        part["mesh"] = mesh
        part["volume"] = float(abs(mesh.volume))
        part["obb_rotation"] = np.array(obb_transform[:3, :3])
        part["obb_extents"] = np.array(obb_extents)
        part["obb_volume"] = float(np.prod(obb_extents))
        # Mass properties. Volume is mm^3 and density g/cm^3, so mass in grams = volume * density / 1000. Inertia is in g*mm^2, about the part's own center of mass, in the part's own axes.
        part["density"] = density_overrides.get(part["name"], default_density)
        part["mass"] = part["volume"] * part["density"] / 1000.0
        part["center_of_mass_local"] = np.array(mesh.center_mass)
        part["inertia_local"] = np.array(mesh.moment_inertia) * part["density"] / 1000.0
        part["cloud_points"] = cloud_points
        # Convex hull vertices give the exact same rotated bounding box as the full mesh, but with far fewer points (fast).
        part["hull_vertices"] = np.array(mesh.convex_hull.vertices)
        # Dense surface samples (about every 0.5 mm) used to measure the gap between parts.
        gap_point_count = int(mesh.area / 0.25) + 200
        gap_surface_points, _ = trimesh.sample.sample_surface(mesh, gap_point_count, seed=1)
        part["gap_points"] = np.vstack([gap_surface_points, mesh.vertices])
        part["occupancy_cache"] = {}
        parts.append(part)
    return parts


def random_rotation(rng):
    """Uniformly random 3D rotation (random unit quaternion)."""
    quaternion = rng.normal(size=4)
    quaternion = quaternion / np.linalg.norm(quaternion)
    rotation_matrix = Rotation.from_quat(quaternion).as_matrix()
    return rotation_matrix


def cube_rotations():
    """The 24 rotations that map a cube onto itself (all ways to set a box down axis-aligned)."""
    rotation_matrices = np.rint(Rotation.create_group("O").as_matrix())
    return rotation_matrices


def rotated_bounds(part, rotation_matrix):
    """Axis-aligned bounds (min corner, max corner) of the part after rotation, before translation."""
    rotated_vertices = part["hull_vertices"] @ rotation_matrix.T
    return rotated_vertices.min(axis=0), rotated_vertices.max(axis=0)


def voxelize_rotated_part(part, rotation_matrix, voxel_pitch, clearance):
    """Occupancy grid of the rotated part, grown by the clearance (points are copied +/- clearance along x, y, z, so cells within the clearance of the surface are also marked).
    Cell (i, j, k) covers grid_origin + [i, j, k] * pitch. Returns (occupancy, grid_origin)."""
    rotated_minimum, rotated_maximum = rotated_bounds(part, rotation_matrix)
    grid_origin = rotated_minimum - clearance
    rotated_points = part["cloud_points"] @ rotation_matrix.T
    if clearance > 0:
        shifted_copies = [rotated_points]
        for axis in range(3):
            offset = np.zeros(3)
            offset[axis] = clearance
            shifted_copies.append(rotated_points + offset)
            shifted_copies.append(rotated_points - offset)
        rotated_points = np.vstack(shifted_copies)
    cell_indices = np.floor((rotated_points - grid_origin) / voxel_pitch).astype(np.int64)
    grid_shape = np.floor((rotated_maximum + clearance - grid_origin) / voxel_pitch).astype(np.int64) + 1
    cell_indices = np.clip(cell_indices, 0, grid_shape - 1)
    occupancy = np.zeros(grid_shape, dtype=bool)
    occupancy[cell_indices[:, 0], cell_indices[:, 1], cell_indices[:, 2]] = True
    return occupancy, grid_origin


def world_vertices(part, placement):
    return part["mesh"].vertices @ placement["rotation"].T + placement["translation"]


def world_mesh(part, placement):
    transform = np.eye(4)
    transform[:3, :3] = placement["rotation"]
    transform[:3, 3] = placement["translation"]
    moved_mesh = part["mesh"].copy()
    moved_mesh.apply_transform(transform)
    return moved_mesh


def evaluate_packing(selected_parts, placements, container_size, check_pitch, clearance):
    """Deterministic scoring of one packing. Overlap is estimated on a voxel grid of size check_pitch, only for pairs whose bounding boxes actually intersect."""
    result = {}
    result["parts_requested"] = len(selected_parts)
    result["parts_placed"] = len(placements)
    result["placed_fraction"] = len(placements) / max(len(selected_parts), 1)
    # Placement order = the order the algorithm put the parts down (the order of the placements list).
    result["placement_order"] = [selected_parts[placement["part_index"]]["name"] for placement in placements]
    result["total_mass"] = 0.0
    result["center_of_mass"] = np.zeros(3)
    result["bbox_center"] = np.zeros(3)
    result["com_offset"] = 0.0
    result["com_offset_normalized"] = 0.0
    result["com_offset_from_container_center"] = 0.0
    result["inertia_tensor"] = np.zeros((3, 3))
    result["principal_moments"] = np.zeros(3)
    result["aspect_ratio"] = 0.0
    result["minimum_gap"] = 0.0
    result["clearance_ok"] = False
    result["contacts"] = 0
    result["contacts_per_part"] = 0.0
    result["isolated_parts"] = 0
    result["contact_band"] = clearance + 0.5
    if len(placements) == 0:
        result["bbox_x"] = 0.0
        result["bbox_y"] = 0.0
        result["bbox_z"] = 0.0
        result["bbox_volume"] = 0.0
        result["placed_volume"] = 0.0
        result["density"] = 0.0
        result["container_fill"] = 0.0
        result["inside_container"] = True
        result["overlap_volume"] = 0.0
        result["overlap_fraction"] = 0.0
        result["valid"] = False
        return result

    part_minimums = []
    part_maximums = []
    for placement in placements:
        vertices_in_world = world_vertices(selected_parts[placement["part_index"]], placement)
        part_minimums.append(vertices_in_world.min(axis=0))
        part_maximums.append(vertices_in_world.max(axis=0))
    part_minimums = np.array(part_minimums)
    part_maximums = np.array(part_maximums)
    bbox_minimum = part_minimums.min(axis=0)
    bbox_maximum = part_maximums.max(axis=0)
    bbox_dimensions = bbox_maximum - bbox_minimum
    bbox_volume = float(np.prod(bbox_dimensions))
    placed_volume = float(sum(selected_parts[placement["part_index"]]["volume"] for placement in placements))

    # Center of mass of the whole packing, and its distance from the center of the bounding box (the "center of volume").
    total_mass = float(sum(selected_parts[placement["part_index"]]["mass"] for placement in placements))
    weighted_position_sum = np.zeros(3)
    for placement in placements:
        part = selected_parts[placement["part_index"]]
        part_center_of_mass_world = placement["rotation"] @ part["center_of_mass_local"] + placement["translation"]
        weighted_position_sum = weighted_position_sum + part["mass"] * part_center_of_mass_world
    center_of_mass = weighted_position_sum / total_mass
    bbox_center = (bbox_minimum + bbox_maximum) / 2.0
    com_offset = float(np.linalg.norm(center_of_mass - bbox_center))
    bbox_diagonal = float(np.linalg.norm(bbox_dimensions))

    # Inertia tensor of the whole packing about its center of mass, along the box (world) x, y, z axes. Each part: rotate its own tensor into world axes, then shift it with the parallel axis theorem.
    inertia_tensor = np.zeros((3, 3))
    for placement in placements:
        part = selected_parts[placement["part_index"]]
        part_center_of_mass_world = placement["rotation"] @ part["center_of_mass_local"] + placement["translation"]
        rotated_part_inertia = placement["rotation"] @ part["inertia_local"] @ placement["rotation"].T
        shift = part_center_of_mass_world - center_of_mass
        parallel_axis_term = part["mass"] * (np.dot(shift, shift) * np.eye(3) - np.outer(shift, shift))
        inertia_tensor = inertia_tensor + rotated_part_inertia + parallel_axis_term

    result["total_mass"] = total_mass
    result["center_of_mass"] = center_of_mass
    result["bbox_center"] = bbox_center
    result["com_offset"] = com_offset
    result["com_offset_normalized"] = com_offset / bbox_diagonal if bbox_diagonal > 0 else 0.0
    result["inertia_tensor"] = inertia_tensor
    # Principal moments = inertia about the packing's own natural axes (eigenvalues of the tensor), smallest first.
    result["principal_moments"] = np.linalg.eigvalsh(inertia_tensor)
    result["aspect_ratio"] = float(bbox_dimensions.max() / bbox_dimensions.min()) if bbox_dimensions.min() > 0 else 0.0

    # Minimum gap between any two parts (approximate: nearest distance between dense surface samples, so it can read a little high). 0 if parts overlap.
    from scipy.spatial import cKDTree
    pair_list = []
    for first in range(len(placements)):
        for second in range(first + 1, len(placements)):
            box_separation = np.maximum(0.0, np.maximum(part_minimums[first] - part_maximums[second], part_minimums[second] - part_maximums[first]))
            pair_list.append((float(np.linalg.norm(box_separation)), first, second))
    pair_list.sort()
    minimum_gap = np.inf
    gap_points_cache = {}
    gap_tree_cache = {}
    for box_separation_distance, first, second in pair_list:
        # Pairs are sorted by how far apart their boxes are, so once a box gap exceeds the best gap found, no later pair can beat it.
        if box_separation_distance >= minimum_gap:
            break
        for index in (first, second):
            if index not in gap_points_cache:
                placement = placements[index]
                part = selected_parts[placement["part_index"]]
                gap_points_cache[index] = part["gap_points"] @ placement["rotation"].T + placement["translation"]
        if second not in gap_tree_cache:
            gap_tree_cache[second] = cKDTree(gap_points_cache[second])
        # Search outward in growing shells (nearest-neighbour search is slow for far-away points, fast for close ones).
        first_points = gap_points_cache[first]
        search_margin = max(2.0 * box_separation_distance, 2.0)
        while True:
            used_margin = min(search_margin, minimum_gap)
            near_mask = np.all((first_points >= part_minimums[second] - used_margin) & (first_points <= part_maximums[second] + used_margin), axis=1)
            if np.any(near_mask):
                nearest_distances, _ = gap_tree_cache[second].query(first_points[near_mask], k=1, distance_upper_bound=used_margin)
                closest_distance = float(nearest_distances.min())
                if np.isfinite(closest_distance):
                    minimum_gap = min(minimum_gap, closest_distance)
                    break
            if search_margin >= minimum_gap:
                break
            search_margin = search_margin * 2.0
    if len(placements) < 2:
        minimum_gap = 0.0
    result["minimum_gap"] = minimum_gap
    result["clearance_ok"] = bool(minimum_gap >= 0.9 * clearance)

    # Contacts: a pair of parts is "in contact" when their surfaces come within the contact band (clearance t + 0.5 mm), i.e. they touch through the clearance padding.
    contact_band = clearance + 0.5
    contact_count = 0
    contacts_per_placement = np.zeros(len(placements), dtype=np.int64)
    for box_separation_distance, first, second in pair_list:
        if box_separation_distance > contact_band:
            break
        for index in (first, second):
            if index not in gap_points_cache:
                placement = placements[index]
                part = selected_parts[placement["part_index"]]
                gap_points_cache[index] = part["gap_points"] @ placement["rotation"].T + placement["translation"]
        if second not in gap_tree_cache:
            gap_tree_cache[second] = cKDTree(gap_points_cache[second])
        first_points = gap_points_cache[first]
        near_mask = np.all((first_points >= part_minimums[second] - contact_band) & (first_points <= part_maximums[second] + contact_band), axis=1)
        if not np.any(near_mask):
            continue
        nearest_distances, _ = gap_tree_cache[second].query(first_points[near_mask], k=1, distance_upper_bound=contact_band)
        if np.isfinite(nearest_distances.min()):
            contact_count = contact_count + 1
            contacts_per_placement[first] = contacts_per_placement[first] + 1
            contacts_per_placement[second] = contacts_per_placement[second] + 1
    result["contacts"] = int(contact_count)
    result["contacts_per_part"] = float(2.0 * contact_count / len(placements)) if len(placements) > 0 else 0.0
    result["isolated_parts"] = int(np.sum(contacts_per_placement == 0)) if len(placements) > 1 else len(placements)
    result["contact_band"] = contact_band
    if container_size is not None:
        result["com_offset_from_container_center"] = float(np.linalg.norm(center_of_mass - np.asarray(container_size, dtype=float) / 2.0))

    # Overlap estimate: cells are aligned to world integer multiples of check_pitch.
    cell_offset = np.floor(bbox_minimum / check_pitch).astype(np.int64) - 2
    cell_span = np.floor(bbox_maximum / check_pitch).astype(np.int64) - cell_offset + 3
    cell_keys_cache = {}
    overlap_cell_count = 0
    tolerance = 1e-6
    for first in range(len(placements)):
        for second in range(first + 1, len(placements)):
            boxes_intersect = np.all(part_minimums[first] < part_maximums[second] - tolerance) and np.all(part_minimums[second] < part_maximums[first] - tolerance)
            if not boxes_intersect:
                continue
            for index in (first, second):
                if index not in cell_keys_cache:
                    placement = placements[index]
                    part = selected_parts[placement["part_index"]]
                    points_in_world = part["cloud_points"] @ placement["rotation"].T + placement["translation"]
                    cells = np.floor(points_in_world / check_pitch).astype(np.int64) - cell_offset
                    keys = cells[:, 0] * (cell_span[1] * cell_span[2]) + cells[:, 1] * cell_span[2] + cells[:, 2]
                    cell_keys_cache[index] = np.unique(keys)
            overlap_cell_count += np.intersect1d(cell_keys_cache[first], cell_keys_cache[second], assume_unique=True).size
    overlap_volume = overlap_cell_count * check_pitch ** 3

    result["bbox_x"] = float(bbox_dimensions[0])
    result["bbox_y"] = float(bbox_dimensions[1])
    result["bbox_z"] = float(bbox_dimensions[2])
    result["bbox_volume"] = bbox_volume
    result["placed_volume"] = placed_volume
    result["density"] = placed_volume / bbox_volume if bbox_volume > 0 else 0.0
    result["overlap_volume"] = overlap_volume
    result["overlap_fraction"] = overlap_volume / placed_volume if placed_volume > 0 else 0.0
    if container_size is None:
        result["container_fill"] = 0.0
        result["inside_container"] = True
    else:
        container_size = np.asarray(container_size, dtype=float)
        result["container_fill"] = placed_volume / float(np.prod(container_size))
        result["inside_container"] = bool(np.all(bbox_minimum >= -1e-6) and np.all(bbox_maximum <= container_size + 1e-6))
    # Valid = essentially no overlap (under 0.5% of part volume, which absorbs voxel rounding) and inside the container if there is one.
    result["valid"] = bool(result["overlap_fraction"] < 0.005 and result["inside_container"])
    if not result["valid"]:
        result["minimum_gap"] = 0.0
        result["clearance_ok"] = False
        result["contacts"] = 0
        result["contacts_per_part"] = 0.0
        result["isolated_parts"] = 0
        result["contact_band"] = clearance + 0.5
    return result
