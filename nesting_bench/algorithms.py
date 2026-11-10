"""
Packing algorithms. Every algorithm has the same signature:

    placements = algorithm(selected_parts, container_size, rng, settings)

selected_parts : list of part dicts from nesting_core.load_parts()
container_size : None = open mode (minimize the bounding box), or [x, y, z] in mm = container mode (fit as many parts as possible)
rng            : numpy random Generator (use it for all randomness so runs are reproducible)
settings       : dict, see DEFAULT_SETTINGS
returns        : list of {"part_index", "rotation", "translation"} in the order the parts were placed. Parts that could not be placed are left out.

Clearance: every packer keeps at least settings["clearance"] mm between parts (boxes are grown by the clearance; the voxel packer grows each part's voxels).
Orientation: random_scatter and random_rejection use any angle. The other packers first turn each part so its tightest (oriented) box is axis-aligned, then try that box's 6 face-down orientations.

To add an algorithm: write a function with this signature, add it to ALGORITHMS, and to RANDOMIZED_ALGORITHMS if it uses randomness.
"""

import time
import numpy as np
from scipy.signal import fftconvolve
import nesting_core


DEFAULT_SETTINGS = {"random_attempts": 300, "voxel_pitch": 2.0, "voxel_orientations": "faces", "clearance": 0.5, "restarts": 3, "force_iterations": 40, "search_seconds": 5.0, "search_decoder": "voxel", "population_size": 12, "order": "default"}


def part_convexity(part):
    """Mesh volume / convex hull volume (1 = convex)."""
    hull_volume = float(abs(part["mesh"].convex_hull.volume))
    return part["volume"] / hull_volume if hull_volume > 0 else 1.0


def part_flatness(part):
    """Shortest / longest oriented box side (1 = cube-like, small = plate or rod)."""
    extents = np.sort(part["obb_extents"])
    return float(extents[0] / extents[2]) if extents[2] > 0 else 1.0


def initial_order(selected_parts, rng, settings):
    """Placement order used by every constructive packer and as the starting point of the search packers.
    settings["order"]: "default" (largest box volume first, the original behaviour), "random" (a permutation from rng),
    "volume_desc", "convexity_desc" (most convex first), "combined" (volume x convexity, big simple parts first),
    "flatness_desc" (compact parts first, plates and rods last), "volume_asc" (smallest first), or an explicit list of indices."""
    order_spec = settings.get("order", "default")
    count = len(selected_parts)
    if isinstance(order_spec, (list, tuple)):
        return list(order_spec)
    if order_spec == "random":
        return [int(index) for index in rng.permutation(count)]
    if order_spec in ("default", "volume_desc"):
        return sorted(range(count), key=lambda index: -selected_parts[index]["obb_volume"])
    if order_spec == "volume_asc":
        return sorted(range(count), key=lambda index: selected_parts[index]["obb_volume"])
    if order_spec == "convexity_desc":
        return sorted(range(count), key=lambda index: (-part_convexity(selected_parts[index]), -selected_parts[index]["obb_volume"]))
    if order_spec == "combined":
        return sorted(range(count), key=lambda index: -part_convexity(selected_parts[index]) * selected_parts[index]["obb_volume"])
    if order_spec == "flatness_desc":
        return sorted(range(count), key=lambda index: (-part_flatness(selected_parts[index]), -selected_parts[index]["obb_volume"]))
    raise ValueError("unknown order " + str(order_spec))



def box_orientation_options(part, clearance):
    """Up to 6 ways to set the part's tightest box down axis-aligned. Each option: (rotation, rotated_minimum, padded_dimensions), where padded = real box + clearance. Cached on the part."""
    cache_key = ("box_options", clearance)
    if cache_key in part["occupancy_cache"]:
        return part["occupancy_cache"][cache_key]
    options = []
    seen_dimensions = set()
    for cube_rotation in nesting_core.cube_rotations():
        full_rotation = cube_rotation @ part["obb_rotation"]
        rotated_minimum, rotated_maximum = nesting_core.rotated_bounds(part, full_rotation)
        dimensions = rotated_maximum - rotated_minimum
        dimensions_key = tuple(np.round(dimensions, 4))
        if dimensions_key in seen_dimensions:
            continue
        seen_dimensions.add(dimensions_key)
        options.append((full_rotation, rotated_minimum, dimensions + clearance))
    part["occupancy_cache"][cache_key] = options
    return options


def footprint_side(selected_parts, clearance):
    """Side length of the square floor used by the layer packers: about a cube's worth of the total box volume, but never smaller than any part's middle dimension."""
    total_box_volume = 0.0
    largest_middle_dimension = 0.0
    for part in selected_parts:
        padded_extents = np.sort(part["obb_extents"] + clearance)
        total_box_volume = total_box_volume + float(np.prod(padded_extents))
        largest_middle_dimension = max(largest_middle_dimension, float(padded_extents[1]))
    return max(1.15 * total_box_volume ** (1.0 / 3.0), largest_middle_dimension)


def random_scatter(selected_parts, container_size, rng, settings):
    """Random angle, random position, overlaps allowed. Not a real packer: the "throw them in a box" picture. Always invalid when parts collide."""
    total_obb_volume = sum(part["obb_volume"] for part in selected_parts)
    if container_size is None:
        region_size = np.full(3, 1.5 * total_obb_volume ** (1.0 / 3.0))
    else:
        region_size = np.asarray(container_size, dtype=float)
    placements = []
    for part_index, part in enumerate(selected_parts):
        rotation = nesting_core.random_rotation(rng)
        rotated_minimum, rotated_maximum = nesting_core.rotated_bounds(part, rotation)
        rotated_size = rotated_maximum - rotated_minimum
        free_room = np.maximum(region_size - rotated_size, 0.0)
        corner = rng.uniform(0.0, 1.0, 3) * free_room
        placements.append({"part_index": part_index, "rotation": rotation, "translation": corner - rotated_minimum})
    return placements


def random_rejection(selected_parts, container_size, rng, settings):
    """Random angle and position; reject any try whose bounding box comes within the clearance of an already placed box. Open mode grows the region 10% when stuck."""
    attempts_per_round = settings["random_attempts"]
    clearance = settings["clearance"]
    total_obb_volume = sum(part["obb_volume"] for part in selected_parts)
    if container_size is None:
        region_size = np.full(3, total_obb_volume ** (1.0 / 3.0))
    else:
        region_size = np.asarray(container_size, dtype=float)
    order = initial_order(selected_parts, rng, settings)
    placed_minimums = np.zeros((0, 3))
    placed_maximums = np.zeros((0, 3))
    placements = []
    for part_index in order:
        part = selected_parts[part_index]
        placed = False
        while not placed:
            for attempt in range(attempts_per_round):
                rotation = nesting_core.random_rotation(rng)
                rotated_minimum, rotated_maximum = nesting_core.rotated_bounds(part, rotation)
                rotated_size = rotated_maximum - rotated_minimum
                if np.any(rotated_size > region_size):
                    continue
                box_minimum = rng.uniform(0.0, 1.0, 3) * (region_size - rotated_size)
                box_maximum = box_minimum + rotated_size
                hits = np.all(box_minimum < placed_maximums + clearance, axis=1) & np.all(placed_minimums < box_maximum + clearance, axis=1)
                if np.any(hits):
                    continue
                placed_minimums = np.vstack([placed_minimums, box_minimum])
                placed_maximums = np.vstack([placed_maximums, box_maximum])
                placements.append({"part_index": part_index, "rotation": rotation, "translation": box_minimum - rotated_minimum})
                placed = True
                break
            if placed or container_size is not None:
                break
            region_size = region_size * 1.1
    return placements


def shelf_packing(selected_parts, container_size, rng, settings):
    """Layer (shelf) packing. Lay each part flat, tallest first. Fill a row left to right; when the row is full start the next row; when the floor is full start a new layer on top."""
    clearance = settings["clearance"]
    if container_size is None:
        floor_x = footprint_side(selected_parts, clearance)
        floor_y = floor_x
        height_limit = np.inf
    else:
        floor_x = float(container_size[0])
        floor_y = float(container_size[1])
        height_limit = float(container_size[2])
    # Flat orientation: shortest side vertical, longest side along x.
    flat_options = []
    for part in selected_parts:
        options = box_orientation_options(part, clearance)
        flat_option = min(options, key=lambda option: (option[2][2], -option[2][0]))
        flat_options.append(flat_option)
    order = sorted(range(len(selected_parts)), key=lambda index: (-flat_options[index][2][2], -flat_options[index][2][0]))
    if settings.get("order", "default") != "default":
        order = initial_order(selected_parts, rng, settings)
    cursor_x = 0.0
    row_y = 0.0
    layer_z = 0.0
    row_depth = 0.0
    layer_height = 0.0
    placements = []
    for part_index in order:
        rotation, rotated_minimum, padded_dimensions = flat_options[part_index]
        if cursor_x > 0 and cursor_x + padded_dimensions[0] > floor_x:
            row_y = row_y + row_depth
            cursor_x = 0.0
            row_depth = 0.0
        if row_y > 0 and row_y + padded_dimensions[1] > floor_y:
            layer_z = layer_z + layer_height
            row_y = 0.0
            cursor_x = 0.0
            row_depth = 0.0
            layer_height = 0.0
        if layer_z + padded_dimensions[2] > height_limit + 1e-9:
            continue
        corner = np.array([cursor_x, row_y, layer_z])
        placements.append({"part_index": part_index, "rotation": rotation, "translation": corner + clearance / 2.0 - rotated_minimum})
        cursor_x = cursor_x + padded_dimensions[0]
        row_depth = max(row_depth, padded_dimensions[1])
        layer_height = max(layer_height, padded_dimensions[2])
    return placements


def box_bottom_left(selected_parts, container_size, rng, settings):
    """Bottom-left-fill on boxes, largest first. Candidate spots are every combination of placed box edges; each part goes to the lowest, then frontmost, then leftmost spot that is free and inside the floor."""
    clearance = settings["clearance"]
    if container_size is None:
        floor_x = footprint_side(selected_parts, clearance)
        floor_y = floor_x
        height_limit = np.inf
    else:
        floor_x = float(container_size[0])
        floor_y = float(container_size[1])
        height_limit = float(container_size[2])
    order = initial_order(selected_parts, rng, settings)
    placed_minimums = np.zeros((0, 3))
    placed_maximums = np.zeros((0, 3))
    placements = []
    for part_index in order:
        part = selected_parts[part_index]
        x_values = np.unique(np.concatenate([[0.0], placed_maximums[:, 0]]))
        y_values = np.unique(np.concatenate([[0.0], placed_maximums[:, 1]]))
        z_values = np.unique(np.concatenate([[0.0], placed_maximums[:, 2]]))
        grid_x, grid_y, grid_z = np.meshgrid(x_values, y_values, z_values, indexing="ij")
        candidates = np.column_stack([grid_x.ravel(), grid_y.ravel(), grid_z.ravel()])
        best_key = None
        best_choice = None
        for rotation, rotated_minimum, padded_dimensions in box_orientation_options(part, clearance):
            candidate_maximums = candidates + padded_dimensions
            # A part longer than the floor may still start at x = 0 or y = 0 (otherwise it could never be placed in open mode).
            fits_x = (candidate_maximums[:, 0] <= floor_x + 1e-9) | ((candidates[:, 0] == 0) & (container_size is None))
            fits_y = (candidate_maximums[:, 1] <= floor_y + 1e-9) | ((candidates[:, 1] == 0) & (container_size is None))
            fits_z = candidate_maximums[:, 2] <= height_limit + 1e-9
            fits = fits_x & fits_y & fits_z
            if len(placed_minimums) > 0:
                overlaps = np.all((candidates[:, None, :] < placed_maximums[None, :, :] - 1e-9) & (placed_minimums[None, :, :] < candidate_maximums[:, None, :] - 1e-9), axis=2)
                fits = fits & ~np.any(overlaps, axis=1)
            free_candidates = candidates[fits]
            if len(free_candidates) == 0:
                continue
            ranking = np.lexsort((free_candidates[:, 0], free_candidates[:, 1], free_candidates[:, 2]))
            corner = free_candidates[ranking[0]]
            key = (corner[2], corner[1], corner[0])
            if best_key is None or key < best_key:
                best_key = key
                best_choice = (corner, rotation, rotated_minimum, padded_dimensions)
        if best_choice is None:
            continue
        corner, rotation, rotated_minimum, padded_dimensions = best_choice
        placed_minimums = np.vstack([placed_minimums, corner])
        placed_maximums = np.vstack([placed_maximums, corner + padded_dimensions])
        placements.append({"part_index": part_index, "rotation": rotation, "translation": corner + clearance / 2.0 - rotated_minimum})
    return placements


def box_extreme_points(selected_parts, container_size, rng, settings):
    """Extreme points on boxes, largest first. Only try spots at the corners of already placed boxes; open mode keeps the spot that keeps the overall box smallest, container mode the lowest one."""
    clearance = settings["clearance"]
    order = initial_order(selected_parts, rng, settings)
    candidate_points = [np.zeros(3)]
    placed_minimums = np.zeros((0, 3))
    placed_maximums = np.zeros((0, 3))
    overall_maximum = np.zeros(3)
    placements = []
    for part_index in order:
        part = selected_parts[part_index]
        best_score = None
        best_choice = None
        for point in candidate_points:
            for rotation, rotated_minimum, padded_dimensions in box_orientation_options(part, clearance):
                box_maximum = point + padded_dimensions
                if container_size is not None and np.any(box_maximum > np.asarray(container_size) + 1e-9):
                    continue
                hits = np.all(point < placed_maximums - 1e-9, axis=1) & np.all(placed_minimums < box_maximum - 1e-9, axis=1)
                if np.any(hits):
                    continue
                if container_size is None:
                    score = (float(np.prod(np.maximum(overall_maximum, box_maximum))), point[2], point[1], point[0])
                else:
                    score = (point[2], point[1], point[0])
                if best_score is None or score < best_score:
                    best_score = score
                    best_choice = (point, rotation, rotated_minimum, padded_dimensions)
        if best_choice is None:
            continue
        point, rotation, rotated_minimum, padded_dimensions = best_choice
        placed_minimums = np.vstack([placed_minimums, point])
        placed_maximums = np.vstack([placed_maximums, point + padded_dimensions])
        overall_maximum = np.maximum(overall_maximum, point + padded_dimensions)
        placements.append({"part_index": part_index, "rotation": rotation, "translation": point + clearance / 2.0 - rotated_minimum})
        candidate_points = [existing for existing in candidate_points if not np.allclose(existing, point)]
        candidate_points.append(point + np.array([padded_dimensions[0], 0.0, 0.0]))
        candidate_points.append(point + np.array([0.0, padded_dimensions[1], 0.0]))
        candidate_points.append(point + np.array([0.0, 0.0, padded_dimensions[2]]))
    return placements


def voxel_orientation_list(part, settings):
    """The part voxelized (grown by half the clearance) in each of its orientations: list of (rotation, occupancy, grid_origin). "faces" keeps one per distinct grid shape (up to 6), "all" keeps all 24. Cached on the part."""
    voxel_pitch = settings["voxel_pitch"]
    clearance = settings["clearance"]
    cache_key = ("voxels", voxel_pitch, settings["voxel_orientations"], clearance)
    if cache_key in part["occupancy_cache"]:
        return part["occupancy_cache"][cache_key]
    orientation_list = []
    seen_shapes = set()
    for cube_rotation in nesting_core.cube_rotations():
        full_rotation = cube_rotation @ part["obb_rotation"]
        occupancy, grid_origin = nesting_core.voxelize_rotated_part(part, full_rotation, voxel_pitch, clearance / 2.0)
        if settings["voxel_orientations"] == "faces":
            if occupancy.shape in seen_shapes:
                continue
            seen_shapes.add(occupancy.shape)
        orientation_list.append((full_rotation, occupancy, grid_origin))
    part["occupancy_cache"][cache_key] = orientation_list
    return orientation_list


def voxel_bottom_left(selected_parts, container_size, rng, settings):
    """Voxel bottom-left-fill. Parts are voxelized at their real shape (grown by the clearance), so concave parts can interlock; an FFT finds every collision-free position at once. Open mode keeps the position that keeps the overall box smallest, container mode the lowest one."""
    order = initial_order(selected_parts, rng, settings)
    placements = voxel_place_sequence(selected_parts, order, None, container_size, settings)
    return placements


def voxel_place_sequence(selected_parts, order, chosen_orientations, container_size, settings):
    """Place parts one by one in the given order on a voxel grid. chosen_orientations = None tries every orientation of each part and keeps the best spot (voxel_bottom_left);
    a list gives one orientation number per part (used by simulated annealing and the genetic algorithm, much faster). Each placement also records its orientation number."""
    voxel_pitch = settings["voxel_pitch"]
    if container_size is None:
        grid = np.zeros((1, 1, 1), dtype=bool)
    else:
        grid = np.zeros(np.ceil(np.asarray(container_size) / voxel_pitch).astype(np.int64), dtype=bool)
    occupied_maximum = np.zeros(3, dtype=np.int64)
    placements = []
    for part_index in order:
        part = selected_parts[part_index]
        orientation_list = voxel_orientation_list(part, settings)
        if chosen_orientations is None:
            orientation_numbers = range(len(orientation_list))
        else:
            orientation_numbers = [chosen_orientations[part_index] % len(orientation_list)]
        best_score = None
        best_choice = None
        for orientation_number in orientation_numbers:
            full_rotation, occupancy, grid_origin = orientation_list[orientation_number]
            part_shape = np.array(occupancy.shape)
            if container_size is None:
                needed_shape = occupied_maximum + part_shape
                padding = [(0, int(max(needed_shape[axis] - grid.shape[axis], 0))) for axis in range(3)]
                grid = np.pad(grid, padding)
                search_grid = grid[:needed_shape[0], :needed_shape[1], :needed_shape[2]]
            else:
                if np.any(part_shape > np.array(grid.shape)):
                    continue
                search_grid = grid
            overlap_counts = fftconvolve(search_grid.astype(np.float32), occupancy[::-1, ::-1, ::-1].astype(np.float32), mode="valid")
            free_positions = np.argwhere(overlap_counts < 0.5)
            if container_size is not None and len(free_positions) > 0:
                # Exact fit test in real units: the part's rotated hull must lie inside the container at that grid position.
                rotated_minimum, rotated_maximum = nesting_core.rotated_bounds(part, full_rotation)
                lowest_cell = np.ceil((grid_origin - rotated_minimum) / voxel_pitch - 1e-9)
                highest_cell = np.floor((np.asarray(container_size) - rotated_maximum + grid_origin) / voxel_pitch + 1e-9)
                free_positions = free_positions[np.all((free_positions >= lowest_cell) & (free_positions <= highest_cell), axis=1)]
            if len(free_positions) == 0:
                continue
            if container_size is None:
                new_maximums = np.maximum(occupied_maximum, free_positions + part_shape)
                new_volumes = np.prod(new_maximums, axis=1)
                ranking = np.lexsort((free_positions[:, 0], free_positions[:, 1], free_positions[:, 2], new_volumes))
                best_position = free_positions[ranking[0]]
                score = (int(new_volumes[ranking[0]]), int(best_position[2]), int(best_position[1]), int(best_position[0]))
            else:
                ranking = np.lexsort((free_positions[:, 0], free_positions[:, 1], free_positions[:, 2]))
                best_position = free_positions[ranking[0]]
                score = (int(best_position[2]), int(best_position[1]), int(best_position[0]))
            if best_score is None or score < best_score:
                best_score = score
                best_choice = (best_position, full_rotation, occupancy, grid_origin, orientation_number)
        if best_choice is None:
            continue
        position, full_rotation, occupancy, grid_origin, orientation_number = best_choice
        part_shape = np.array(occupancy.shape)
        grid[position[0]:position[0] + part_shape[0], position[1]:position[1] + part_shape[1], position[2]:position[2] + part_shape[2]] |= occupancy
        occupied_maximum = np.maximum(occupied_maximum, position + part_shape)
        placements.append({"part_index": part_index, "rotation": full_rotation, "translation": position * voxel_pitch - grid_origin, "orientation_number": orientation_number})
    return placements


def force_based(selected_parts, container_size, rng, settings):
    """Force-based separation on boxes. Start with every part at a random spot (overlapping). Repeat: squeeze all parts toward the middle, then push overlapping pairs apart along their shallowest overlap until nothing overlaps. Keep the tightest overlap-free state seen. No placement order (all parts move at once)."""
    clearance = settings["clearance"]
    part_count = len(selected_parts)
    rotations = []
    rotated_minimums = []
    padded_dimensions = []
    for part in selected_parts:
        options = box_orientation_options(part, clearance)
        chosen_option = options[int(rng.integers(0, len(options)))]
        rotations.append(chosen_option[0])
        rotated_minimums.append(chosen_option[1])
        padded_dimensions.append(chosen_option[2])
    padded_dimensions = np.array(padded_dimensions)
    half_sizes = padded_dimensions / 2.0
    starting_side = float(np.sum(np.prod(padded_dimensions, axis=1))) ** (1.0 / 3.0)
    centers = rng.uniform(-starting_side / 2.0, starting_side / 2.0, (part_count, 3))
    pair_index_first, pair_index_second = np.meshgrid(np.arange(part_count), np.arange(part_count), indexing="ij")
    tie_break_sign = np.where(pair_index_first > pair_index_second, 1.0, -1.0)
    not_same_part = pair_index_first != pair_index_second
    squeeze_fraction = 0.1
    best_volume = np.inf
    best_centers = None
    trace = settings.get("trace")
    for iteration in range(settings["force_iterations"]):
        centers = centers - squeeze_fraction * (centers - centers.mean(axis=0))
        if container_size is not None:
            centers = np.clip(centers, half_sizes, np.asarray(container_size) - half_sizes)
        overlap_free = False
        for push_pass in range(60):
            if trace is not None:
                trace.append([{"part_index": index, "rotation": rotations[index], "translation": centers[index] - half_sizes[index] + clearance / 2.0 - rotated_minimums[index]} for index in range(part_count)])
            differences = centers[:, None, :] - centers[None, :, :]
            penetrations = half_sizes[:, None, :] + half_sizes[None, :, :] - np.abs(differences)
            overlapping = np.all(penetrations > 1e-9, axis=2) & not_same_part
            if not np.any(overlapping):
                overlap_free = True
                break
            push_axis = np.argmin(penetrations, axis=2)
            push_amount = np.take_along_axis(penetrations, push_axis[:, :, None], axis=2)[:, :, 0]
            push_sign = np.sign(np.take_along_axis(differences, push_axis[:, :, None], axis=2)[:, :, 0])
            push_sign = np.where(push_sign == 0, tie_break_sign, push_sign)
            displacement = np.zeros((part_count, part_count, 3))
            np.put_along_axis(displacement, push_axis[:, :, None], (push_sign * push_amount / 2.0 * overlapping)[:, :, None], axis=2)
            centers = centers + displacement.sum(axis=1)
            if container_size is not None:
                centers = np.clip(centers, half_sizes, np.asarray(container_size) - half_sizes)
        if overlap_free:
            box_minimum = (centers - half_sizes).min(axis=0)
            box_maximum = (centers + half_sizes).max(axis=0)
            volume = float(np.prod(box_maximum - box_minimum))
            if volume < best_volume:
                best_volume = volume
                best_centers = centers.copy()
    if best_centers is None:
        # Never reached an overlap-free state: fall back to a simple row so the result is still valid (open mode) or drop parts that still collide (container mode).
        if container_size is None:
            row_x = np.cumsum(padded_dimensions[:, 0]) - half_sizes[:, 0]
            best_centers = np.column_stack([row_x, half_sizes[:, 1], half_sizes[:, 2]])
        else:
            best_centers = centers
    placements = []
    kept_minimums = np.zeros((0, 3))
    kept_maximums = np.zeros((0, 3))
    for part_index in range(part_count):
        box_minimum = best_centers[part_index] - half_sizes[part_index]
        box_maximum = best_centers[part_index] + half_sizes[part_index]
        hits = np.all(box_minimum < kept_maximums - 1e-9, axis=1) & np.all(kept_minimums < box_maximum - 1e-9, axis=1)
        if np.any(hits):
            continue
        kept_minimums = np.vstack([kept_minimums, box_minimum])
        kept_maximums = np.vstack([kept_maximums, box_maximum])
        placements.append({"part_index": part_index, "rotation": rotations[part_index], "translation": box_minimum + clearance / 2.0 - rotated_minimums[part_index]})
    return placements


def heightfield_part(part, orientation_number, settings):
    """Top and bottom surface of the part in one orientation, as integer heights per (x, y) grid column (voxel units), plus a mask of the columns the part occupies. Cached on the part."""
    cache_key = ("heightfield", settings["voxel_pitch"], settings["voxel_orientations"], settings["clearance"], orientation_number)
    if cache_key in part["occupancy_cache"]:
        return part["occupancy_cache"][cache_key]
    full_rotation, occupancy, grid_origin = voxel_orientation_list(part, settings)[orientation_number]
    column_mask = np.any(occupancy, axis=2)
    z_count = occupancy.shape[2]
    z_index = np.arange(z_count)
    top_surface = np.where(column_mask, (occupancy * (z_index + 1)).max(axis=2), 0)
    bottom_surface = np.where(column_mask, np.where(occupancy, z_index, z_count).min(axis=2), 0)
    part["occupancy_cache"][cache_key] = (full_rotation, grid_origin, column_mask, top_surface, bottom_surface)
    return part["occupancy_cache"][cache_key]


def heightfield_drop(selected_parts, container_size, rng, settings):
    """Exact-shape heightfield drop (Huai-Yi's method). The packed stack is a 2D height map. Each part, largest first, is dropped straight down at every (x, y) on the floor and in every orientation; it lands where its bottom surface first touches the stack's top surface: landing height = max over its columns of (stack top - part bottom). Overlap-free by construction, since every column is treated as solid from the part's bottom to its top. Open mode keeps the spot that keeps the overall box smallest, container mode the lowest spot."""
    order = initial_order(selected_parts, rng, settings)
    placements = heightfield_place_sequence(selected_parts, order, None, container_size, settings)
    return placements


def heightfield_place_sequence(selected_parts, order, chosen_orientations, container_size, settings):
    """Heightfield drop in a given order. chosen_orientations = None tries every orientation (heightfield_drop); a list gives one orientation number per part (the decoder for genetic_heightfield)."""
    from numpy.lib.stride_tricks import sliding_window_view
    voxel_pitch = settings["voxel_pitch"]
    clearance = settings["clearance"]
    if container_size is None:
        floor_cells = int(np.ceil(footprint_side(selected_parts, clearance) / voxel_pitch))
        floor_shape = np.array([floor_cells, floor_cells])
        height_limit = np.inf
    else:
        floor_shape = np.ceil(np.asarray(container_size[:2]) / voxel_pitch).astype(np.int64)
        height_limit = int(np.ceil(container_size[2] / voxel_pitch))
    # Make sure every part fits on the floor in at least one orientation (open mode only).
    if container_size is None:
        for part in selected_parts:
            footprints = [heightfield_part(part, number, settings)[2].shape for number in range(len(voxel_orientation_list(part, settings)))]
            smallest_footprint = min(footprints, key=lambda shape: max(shape))
            floor_shape = np.maximum(floor_shape, np.array(smallest_footprint))
    stack_top = np.zeros(floor_shape, dtype=np.int64)
    occupied_maximum = np.zeros(3, dtype=np.int64)
    placements = []
    for part_index in order:
        part = selected_parts[part_index]
        best_score = None
        best_choice = None
        if chosen_orientations is None:
            orientation_numbers = range(len(voxel_orientation_list(part, settings)))
        else:
            orientation_numbers = [chosen_orientations[part_index] % len(voxel_orientation_list(part, settings))]
        for orientation_number in orientation_numbers:
            full_rotation, grid_origin, column_mask, top_surface, bottom_surface = heightfield_part(part, orientation_number, settings)
            footprint = np.array(column_mask.shape)
            if np.any(footprint > floor_shape):
                continue
            # windows[x, y, i, j] = stack_top[x + i, y + j] for every possible corner (x, y). Landing height at (x, y) = max over the part's columns of (stack top - part bottom).
            windows = sliding_window_view(stack_top, tuple(footprint))
            landing = np.where(column_mask, windows - bottom_surface, -1).max(axis=(2, 3))
            landing = np.maximum(landing, 0)
            part_height = int(top_surface.max())
            if container_size is not None:
                landing = np.where(landing + part_height <= height_limit, landing, -1)
                rotated_minimum, rotated_maximum = nesting_core.rotated_bounds(part, full_rotation)
                lowest_cell = np.ceil((grid_origin - rotated_minimum) / voxel_pitch - 1e-9)
                highest_cell = np.floor((np.asarray(container_size) - rotated_maximum + grid_origin) / voxel_pitch + 1e-9)
                column_x = np.arange(landing.shape[0])[:, None]
                column_y = np.arange(landing.shape[1])[None, :]
                column_ok = (column_x >= lowest_cell[0]) & (column_x <= highest_cell[0]) & (column_y >= lowest_cell[1]) & (column_y <= highest_cell[1])
                landing = np.where(column_ok & (landing >= lowest_cell[2]) & (landing <= highest_cell[2]), landing, -1)
            corners = np.argwhere(landing >= 0)
            if len(corners) == 0:
                continue
            landing_values = landing[corners[:, 0], corners[:, 1]]
            if container_size is None:
                new_maximums = np.maximum(occupied_maximum, np.column_stack([corners + footprint, landing_values + part_height]))
                new_volumes = np.prod(new_maximums, axis=1)
                ranking = np.lexsort((corners[:, 0], corners[:, 1], landing_values, new_volumes))
                score = (int(new_volumes[ranking[0]]), int(landing_values[ranking[0]]), int(corners[ranking[0], 1]), int(corners[ranking[0], 0]))
            else:
                ranking = np.lexsort((corners[:, 0], corners[:, 1], landing_values))
                score = (int(landing_values[ranking[0]]), int(corners[ranking[0], 1]), int(corners[ranking[0], 0]))
            if best_score is None or score < best_score:
                best_choice = (corners[ranking[0]], int(landing_values[ranking[0]]), orientation_number, full_rotation, grid_origin, column_mask, top_surface, footprint, part_height)
                best_score = score
        if best_choice is None:
            continue
        corner, landing_height, orientation_number, full_rotation, grid_origin, column_mask, top_surface, footprint, part_height = best_choice
        region = stack_top[corner[0]:corner[0] + footprint[0], corner[1]:corner[1] + footprint[1]]
        region[column_mask] = np.maximum(region[column_mask], landing_height + top_surface[column_mask])
        occupied_maximum = np.maximum(occupied_maximum, np.array([corner[0] + footprint[0], corner[1] + footprint[1], landing_height + part_height]))
        position = np.array([corner[0], corner[1], landing_height])
        placements.append({"part_index": part_index, "rotation": full_rotation, "translation": position * voxel_pitch - grid_origin, "orientation_number": orientation_number})
    return placements


def box_place_sequence(selected_parts, order, chosen_orientations, container_size, settings):
    """Extreme points on boxes in a given order with one chosen orientation per part (the fast decoder for the search algorithms)."""
    clearance = settings["clearance"]
    candidate_points = [np.zeros(3)]
    placed_minimums = np.zeros((0, 3))
    placed_maximums = np.zeros((0, 3))
    overall_maximum = np.zeros(3)
    placements = []
    for part_index in order:
        part = selected_parts[part_index]
        options = box_orientation_options(part, clearance)
        orientation_number = chosen_orientations[part_index] % len(options)
        rotation, rotated_minimum, padded_dimensions = options[orientation_number]
        best_score = None
        best_point = None
        for point in candidate_points:
            box_maximum = point + padded_dimensions
            if container_size is not None and np.any(box_maximum > np.asarray(container_size) + 1e-9):
                continue
            hits = np.all(point < placed_maximums - 1e-9, axis=1) & np.all(placed_minimums < box_maximum - 1e-9, axis=1)
            if np.any(hits):
                continue
            if container_size is None:
                score = (float(np.prod(np.maximum(overall_maximum, box_maximum))), point[2], point[1], point[0])
            else:
                score = (point[2], point[1], point[0])
            if best_score is None or score < best_score:
                best_score = score
                best_point = point
        if best_point is None:
            continue
        point = best_point
        placed_minimums = np.vstack([placed_minimums, point])
        placed_maximums = np.vstack([placed_maximums, point + padded_dimensions])
        overall_maximum = np.maximum(overall_maximum, point + padded_dimensions)
        placements.append({"part_index": part_index, "rotation": rotation, "translation": point + clearance / 2.0 - rotated_minimum, "orientation_number": orientation_number})
        candidate_points = [existing for existing in candidate_points if not np.allclose(existing, point)]
        candidate_points.append(point + np.array([padded_dimensions[0], 0.0, 0.0]))
        candidate_points.append(point + np.array([0.0, padded_dimensions[1], 0.0]))
        candidate_points.append(point + np.array([0.0, 0.0, padded_dimensions[2]]))
    return placements


def decode_and_score(selected_parts, order, chosen_orientations, container_size, settings):
    """Turn (order, orientations) into a packing with the chosen decoder and score it: higher is better. Score = parts placed first, then density (parts volume / bounding box volume), measured on the exact rotated hulls."""
    if settings["search_decoder"] == "box":
        placements = box_place_sequence(selected_parts, order, chosen_orientations, container_size, settings)
    elif settings["search_decoder"] == "heightfield":
        placements = heightfield_place_sequence(selected_parts, order, chosen_orientations, container_size, settings)
    else:
        placements = voxel_place_sequence(selected_parts, order, chosen_orientations, container_size, settings)
    if len(placements) == 0:
        return placements, (0, 0.0)
    minimums = []
    maximums = []
    placed_volume = 0.0
    for placement in placements:
        part = selected_parts[placement["part_index"]]
        rotated_minimum, rotated_maximum = nesting_core.rotated_bounds(part, placement["rotation"])
        minimums.append(rotated_minimum + placement["translation"])
        maximums.append(rotated_maximum + placement["translation"])
        placed_volume = placed_volume + part["volume"]
    bbox_dimensions = np.max(maximums, axis=0) - np.min(minimums, axis=0)
    density = placed_volume / float(np.prod(bbox_dimensions))
    return placements, (len(placements), density)


def orientation_counts(selected_parts, settings):
    """How many orientations each part has under the chosen decoder."""
    counts = []
    for part in selected_parts:
        if settings["search_decoder"] == "box":
            counts.append(len(box_orientation_options(part, settings["clearance"])))
        else:
            counts.append(len(voxel_orientation_list(part, settings)))
    return counts


def mutate(order, chosen_orientations, counts, rng):
    """One random change: swap two parts in the order, or re-orient one part."""
    new_order = list(order)
    new_orientations = list(chosen_orientations)
    if rng.uniform() < 0.5 and len(order) > 1:
        first, second = rng.choice(len(order), size=2, replace=False)
        new_order[first], new_order[second] = new_order[second], new_order[first]
    else:
        part_index = int(rng.integers(0, len(order)))
        new_orientations[part_index] = int(rng.integers(0, counts[part_index]))
    return new_order, new_orientations


def simulated_annealing(selected_parts, container_size, rng, settings):
    """Simulated annealing over placement order and orientation. Start from largest-first; each step swaps two parts or re-orients one, decodes the sequence with the voxel (or box) packer, and keeps the change if density improves, or with probability exp(gain / temperature) if it got worse. Temperature falls from 0.05 to 0.001 over the time cap (settings["search_seconds"])."""
    counts = orientation_counts(selected_parts, settings)
    order = initial_order(selected_parts, rng, settings)
    chosen_orientations = [0] * len(selected_parts)
    current_placements, current_score = decode_and_score(selected_parts, order, chosen_orientations, container_size, settings)
    best_placements = current_placements
    best_score = current_score
    start_time = time.perf_counter()
    time_cap = settings["search_seconds"]
    starting_temperature = 0.05
    ending_temperature = 0.001
    while True:
        elapsed_fraction = (time.perf_counter() - start_time) / time_cap
        if elapsed_fraction >= 1.0:
            break
        temperature = starting_temperature * (ending_temperature / starting_temperature) ** elapsed_fraction
        new_order, new_orientations = mutate(order, chosen_orientations, counts, rng)
        new_placements, new_score = decode_and_score(selected_parts, new_order, new_orientations, container_size, settings)
        gain = (new_score[0] - current_score[0]) + (new_score[1] - current_score[1])
        if gain >= 0 or rng.uniform() < np.exp(gain / temperature):
            order = new_order
            chosen_orientations = new_orientations
            current_placements = new_placements
            current_score = new_score
            if current_score > best_score:
                best_score = current_score
                best_placements = current_placements
    return best_placements


def genetic_algorithm(selected_parts, container_size, rng, settings):
    """Genetic algorithm over placement order and orientation. A population of (order, orientations) genomes; each generation keeps the best half, and fills the rest with children made by order crossover (a slice of one parent's order, the rest in the other parent's order; orientations picked per part from either parent) plus one mutation. Runs until the time cap (settings["search_seconds"])."""
    counts = orientation_counts(selected_parts, settings)
    part_count = len(selected_parts)
    population_size = settings["population_size"]
    population = []
    largest_first = initial_order(selected_parts, rng, settings)
    for member in range(population_size):
        if member == 0:
            order = list(largest_first)
            chosen_orientations = [0] * part_count
        else:
            order = list(rng.permutation(part_count))
            chosen_orientations = [int(rng.integers(0, counts[index])) for index in range(part_count)]
        placements, score = decode_and_score(selected_parts, order, chosen_orientations, container_size, settings)
        population.append((score, order, chosen_orientations, placements))
    start_time = time.perf_counter()
    while time.perf_counter() - start_time < settings["search_seconds"]:
        population.sort(key=lambda member: member[0], reverse=True)
        parents = population[:max(population_size // 2, 2)]
        children = []
        while len(parents) + len(children) < population_size:
            first_parent = parents[int(rng.integers(0, len(parents)))]
            second_parent = parents[int(rng.integers(0, len(parents)))]
            cut_start, cut_end = sorted(rng.choice(part_count + 1, size=2, replace=False))
            slice_of_first = first_parent[1][cut_start:cut_end]
            rest_from_second = [part_index for part_index in second_parent[1] if part_index not in slice_of_first]
            child_order = rest_from_second[:cut_start] + list(slice_of_first) + rest_from_second[cut_start:]
            child_orientations = [first_parent[2][index] if rng.uniform() < 0.5 else second_parent[2][index] for index in range(part_count)]
            child_order, child_orientations = mutate(child_order, child_orientations, counts, rng)
            placements, score = decode_and_score(selected_parts, child_order, child_orientations, container_size, settings)
            children.append((score, child_order, child_orientations, placements))
        population = parents + children
    population.sort(key=lambda member: member[0], reverse=True)
    return population[0][3]


def force_based_v2(selected_parts, container_size, rng, settings):
    """Force-based separation, second version. Same idea as force_based (random overlapping start, squeeze, push overlapping pairs apart) with three changes: the squeeze is anisotropic (each axis is pulled in by how far it exceeds a target cube, so no long rows form), every overlap-free state is then compacted (each box slides toward the origin along x, y and z as far as it can without touching), and the best orientation per part is re-picked from all 6 between squeezes."""
    clearance = settings["clearance"]
    part_count = len(selected_parts)
    options_per_part = [box_orientation_options(part, clearance) for part in selected_parts]
    chosen = [int(rng.integers(0, len(options))) for options in options_per_part]
    padded_dimensions = np.array([options_per_part[index][chosen[index]][2] for index in range(part_count)])
    half_sizes = padded_dimensions / 2.0
    total_box_volume = float(np.sum(np.prod(padded_dimensions, axis=1)))
    if container_size is None:
        target_extent = np.full(3, total_box_volume ** (1.0 / 3.0))
    else:
        target_extent = np.asarray(container_size, dtype=float)
    starting_side = target_extent.mean()
    centers = rng.uniform(-starting_side / 2.0, starting_side / 2.0, (part_count, 3)) + target_extent / 2.0
    pair_index_first, pair_index_second = np.meshgrid(np.arange(part_count), np.arange(part_count), indexing="ij")
    tie_break_sign = np.where(pair_index_first > pair_index_second, 1.0, -1.0)
    not_same_part = pair_index_first != pair_index_second
    best_volume = np.inf
    best_state = None
    trace = settings.get("trace")
    for iteration in range(settings["force_iterations"]):
        if trace is not None:
            trace.append([{"part_index": index, "rotation": options_per_part[index][chosen[index]][0], "translation": centers[index] - half_sizes[index] + clearance / 2.0 - options_per_part[index][chosen[index]][1]} for index in range(part_count)])
        # Anisotropic squeeze: an axis that is wider than the target is pulled in harder.
        extent = (centers + half_sizes).max(axis=0) - (centers - half_sizes).min(axis=0)
        squeeze = 0.05 + 0.15 * np.clip((extent - target_extent) / extent, 0.0, 1.0)
        centers = centers - squeeze * (centers - centers.mean(axis=0))
        if container_size is not None:
            centers = np.clip(centers, half_sizes, np.asarray(container_size) - half_sizes)
        overlap_free = False
        for push_pass in range(60):
            differences = centers[:, None, :] - centers[None, :, :]
            penetrations = half_sizes[:, None, :] + half_sizes[None, :, :] - np.abs(differences)
            overlapping = np.all(penetrations > 1e-9, axis=2) & not_same_part
            if not np.any(overlapping):
                overlap_free = True
                break
            push_axis = np.argmin(penetrations, axis=2)
            push_amount = np.take_along_axis(penetrations, push_axis[:, :, None], axis=2)[:, :, 0]
            push_sign = np.sign(np.take_along_axis(differences, push_axis[:, :, None], axis=2)[:, :, 0])
            push_sign = np.where(push_sign == 0, tie_break_sign, push_sign)
            displacement = np.zeros((part_count, part_count, 3))
            np.put_along_axis(displacement, push_axis[:, :, None], (push_sign * push_amount / 2.0 * overlapping)[:, :, None], axis=2)
            centers = centers + displacement.sum(axis=1)
            if container_size is not None:
                centers = np.clip(centers, half_sizes, np.asarray(container_size) - half_sizes)
        if not overlap_free:
            continue
        # Compaction: slide each box toward the origin along z, then y, then x, as far as the others allow.
        minimums = centers - half_sizes
        maximums = centers + half_sizes
        origin = minimums.min(axis=0)
        minimums = minimums - origin
        maximums = maximums - origin
        for compaction_pass in range(3):
            for part_index in np.argsort(minimums.sum(axis=1)):
                for axis in (2, 1, 0):
                    other_axes = [other for other in range(3) if other != axis]
                    overlapping_in_other_axes = np.all((minimums[:, other_axes] < maximums[part_index, other_axes] - 1e-9) & (minimums[part_index, other_axes] < maximums[:, other_axes] - 1e-9), axis=1)
                    below = overlapping_in_other_axes & (maximums[:, axis] <= minimums[part_index, axis] + 1e-9)
                    below[part_index] = False
                    floor_level = maximums[below, axis].max() if np.any(below) else 0.0
                    shift = minimums[part_index, axis] - floor_level
                    minimums[part_index, axis] = minimums[part_index, axis] - shift
                    maximums[part_index, axis] = maximums[part_index, axis] - shift
        volume = float(np.prod(maximums.max(axis=0) - minimums.min(axis=0)))
        if trace is not None:
            trace.append([{"part_index": index, "rotation": options_per_part[index][chosen[index]][0], "translation": minimums[index] + clearance / 2.0 - options_per_part[index][chosen[index]][1]} for index in range(part_count)])
        if volume < best_volume:
            best_volume = volume
            best_state = (minimums.copy(), list(chosen))
        centers = (minimums + maximums) / 2.0
        # Re-pick each part's orientation: the one whose box would overlap the others least where it sits now (ties keep the current one).
        for part_index in range(part_count):
            best_option = chosen[part_index]
            best_overlap = np.inf
            for option_number, option in enumerate(options_per_part[part_index]):
                trial_half = option[2] / 2.0
                penetration = trial_half + half_sizes - np.abs(centers - centers[part_index])
                penetration[part_index] = 0.0
                overlap_volume = float(np.sum(np.prod(np.clip(penetration, 0.0, None), axis=1)))
                if overlap_volume < best_overlap - 1e-9:
                    best_overlap = overlap_volume
                    best_option = option_number
            chosen[part_index] = best_option
            padded_dimensions[part_index] = options_per_part[part_index][best_option][2]
        half_sizes = padded_dimensions / 2.0
    if best_state is None:
        # Never overlap-free (typical in container mode with too many parts): keep the last state and drop the boxes that still collide, as force_based does.
        best_state = (centers - half_sizes - (centers - half_sizes).min(axis=0) * (container_size is None), list(chosen))
    minimums, chosen = best_state
    placements = []
    kept_minimums = np.zeros((0, 3))
    kept_maximums = np.zeros((0, 3))
    for part_index in range(part_count):
        rotation, rotated_minimum, dimensions = options_per_part[part_index][chosen[part_index]]
        box_minimum = minimums[part_index]
        box_maximum = box_minimum + dimensions
        if container_size is not None and np.any(box_maximum > np.asarray(container_size) + 1e-9):
            continue
        hits = np.all(box_minimum < kept_maximums - 1e-9, axis=1) & np.all(kept_minimums < box_maximum - 1e-9, axis=1)
        if np.any(hits):
            continue
        kept_minimums = np.vstack([kept_minimums, box_minimum])
        kept_maximums = np.vstack([kept_maximums, box_maximum])
        placements.append({"part_index": part_index, "rotation": rotation, "translation": box_minimum + clearance / 2.0 - rotated_minimum, "orientation_number": chosen[part_index]})
    return placements


def genetic_heightfield(selected_parts, container_size, rng, settings):
    """genetic_algorithm with the heightfield drop as decoder instead of the voxel packer: each decode is about 10x cheaper, so the same 5 s budget evaluates about 10x more orders and orientations."""
    heightfield_settings = dict(settings)
    heightfield_settings["search_decoder"] = "heightfield"
    placements = genetic_algorithm(selected_parts, container_size, rng, heightfield_settings)
    return placements


def genetic_box(selected_parts, container_size, rng, settings):
    """genetic_algorithm with the extreme-points box decoder: exact box geometry (no grid rounding) and about 50x cheaper decodes than voxel, so the 5 s budget covers far more orders. Boxes only."""
    box_settings = dict(settings)
    box_settings["search_decoder"] = "box"
    placements = genetic_algorithm(selected_parts, container_size, rng, box_settings)
    return placements


def empty_maximal_spaces(selected_parts, container_size, rng, settings):
    """Empty maximal spaces (EMS) box packing. The free space is kept as a list of maximal empty boxes. Each part (largest box first) is placed at the minimum corner of the empty box, in the orientation, that keeps the overall bounding box smallest (container mode: lowest, then frontmost, then leftmost); every empty box that the part cuts is split into the up to 6 boxes around it, and boxes contained in others are dropped."""
    clearance = settings["clearance"]
    if container_size is None:
        side = 4.0 * footprint_side(selected_parts, clearance) + 2.0 * max(max(part["obb_extents"]) for part in selected_parts) + 2.0 * clearance
        empty_boxes = [(np.zeros(3), np.full(3, side))]
    else:
        empty_boxes = [(np.zeros(3), np.asarray(container_size, dtype=float))]
    order = initial_order(selected_parts, rng, settings)
    overall_maximum = np.zeros(3)
    placements = []
    for part_index in order:
        part = selected_parts[part_index]
        best_score = None
        best_choice = None
        for rotation, rotated_minimum, padded_dimensions in box_orientation_options(part, clearance):
            for empty_minimum, empty_maximum in empty_boxes:
                if np.any(empty_maximum - empty_minimum < padded_dimensions - 1e-9):
                    continue
                box_maximum = empty_minimum + padded_dimensions
                if container_size is None:
                    score = (float(np.prod(np.maximum(overall_maximum, box_maximum))), empty_minimum[2], empty_minimum[1], empty_minimum[0])
                else:
                    score = (empty_minimum[2], empty_minimum[1], empty_minimum[0])
                if best_score is None or score < best_score:
                    best_score = score
                    best_choice = (empty_minimum.copy(), rotation, rotated_minimum, padded_dimensions)
        if best_choice is None:
            continue
        box_minimum, rotation, rotated_minimum, padded_dimensions = best_choice
        box_maximum = box_minimum + padded_dimensions
        overall_maximum = np.maximum(overall_maximum, box_maximum)
        placements.append({"part_index": part_index, "rotation": rotation, "translation": box_minimum + clearance / 2.0 - rotated_minimum})
        new_empty_boxes = []
        for empty_minimum, empty_maximum in empty_boxes:
            if np.any(box_minimum >= empty_maximum - 1e-9) or np.any(box_maximum <= empty_minimum + 1e-9):
                new_empty_boxes.append((empty_minimum, empty_maximum))
                continue
            for axis in range(3):
                if box_minimum[axis] > empty_minimum[axis] + 1e-9:
                    piece_maximum = empty_maximum.copy()
                    piece_maximum[axis] = box_minimum[axis]
                    new_empty_boxes.append((empty_minimum.copy(), piece_maximum))
                if box_maximum[axis] < empty_maximum[axis] - 1e-9:
                    piece_minimum = empty_minimum.copy()
                    piece_minimum[axis] = box_maximum[axis]
                    new_empty_boxes.append((piece_minimum, empty_maximum.copy()))
        smallest_part_side = min(min(options[0][2]) for options in [box_orientation_options(other, clearance) for other in selected_parts])
        new_empty_boxes = [(low, high) for low, high in new_empty_boxes if np.all(high - low >= smallest_part_side - 1e-9)]
        kept = []
        for number, (low, high) in enumerate(new_empty_boxes):
            contained = False
            for other_number, (other_low, other_high) in enumerate(new_empty_boxes):
                if other_number == number:
                    continue
                if np.all(other_low <= low + 1e-9) and np.all(other_high >= high - 1e-9):
                    if not (np.allclose(other_low, low) and np.allclose(other_high, high) and other_number > number):
                        contained = True
                        break
            if not contained:
                kept.append((low, high))
        empty_boxes = kept
    return placements


def best_of_fast(selected_parts, container_size, rng, settings):
    """Runs every fast constructive packer (shelf, bottom-left, extreme points, empty maximal spaces, voxel, heightfield) on the same parts and keeps the densest result (most parts placed first). This is the "let the tool pick the algorithm" option; its cost is the sum of the six."""
    best_placements = []
    best_score = None
    for name in ["shelf_packing", "box_bottom_left", "box_extreme_points", "empty_maximal_spaces", "voxel_bottom_left", "heightfield_drop"]:
        placements = ALGORITHMS[name](selected_parts, container_size, rng, settings)
        if len(placements) == 0:
            continue
        minimums = []
        maximums = []
        placed_volume = 0.0
        for placement in placements:
            part = selected_parts[placement["part_index"]]
            rotated_minimum, rotated_maximum = nesting_core.rotated_bounds(part, placement["rotation"])
            minimums.append(rotated_minimum + placement["translation"])
            maximums.append(rotated_maximum + placement["translation"])
            placed_volume = placed_volume + part["volume"]
        density = placed_volume / float(np.prod(np.max(maximums, axis=0) - np.min(minimums, axis=0)))
        score = (len(placements), density)
        if best_score is None or score > best_score:
            best_score = score
            best_placements = placements
    return best_placements



# ---------------------------------------------------------------------------------------------------------------------
# Algorithms added 2026-11-10 (order study week): skyline_3d, wall_building, dblf_24, beam_search, grasp_ems.


def skyline_3d(selected_parts, container_size, rng, settings):
    """Skyline (2.5D heightmap of boxes). A square floor carries a heightmap at 1 mm resolution; each part's box, in each of its 6 orientations, is tried at every corner of the placed boxes (2D extreme points) and rests on the highest point under its footprint. Keep the spot with the lowest resulting top, then the least wasted volume under the box, then lowest y, x. Open mode tries floor sides of 1.0, 1.25, 1.5 and 2.0 x footprint_side and keeps the densest packing that places every part. Container mode uses the container floor and height."""
    if container_size is not None:
        return skyline_3d_on_floor(selected_parts, container_size, rng, settings, None)
    best_placements = []
    best_key = None
    for factor in (1.0, 1.25, 1.5, 2.0):
        placements = skyline_3d_on_floor(selected_parts, None, rng, settings, factor)
        key = (len(placements), packing_density(selected_parts, placements))
        if best_key is None or key > best_key:
            best_key = key
            best_placements = placements
    return best_placements


def packing_density(selected_parts, placements):
    """Parts volume / bounding box volume of a placement list (0 for an empty list)."""
    if not placements:
        return 0.0
    minimums = []
    maximums = []
    placed_volume = 0.0
    for placement in placements:
        part = selected_parts[placement["part_index"]]
        rotated_minimum, rotated_maximum = nesting_core.rotated_bounds(part, placement["rotation"])
        minimums.append(rotated_minimum + placement["translation"])
        maximums.append(rotated_maximum + placement["translation"])
        placed_volume = placed_volume + part["volume"]
    return placed_volume / max(float(np.prod(np.max(maximums, axis=0) - np.min(minimums, axis=0))), 1e-9)


def skyline_3d_on_floor(selected_parts, container_size, rng, settings, floor_factor):
    clearance = settings["clearance"]
    resolution = 1.0
    if container_size is None:
        side_x = floor_factor * footprint_side(selected_parts, clearance)
        side_y = side_x
        height_limit = None
    else:
        side_x = float(container_size[0])
        side_y = float(container_size[1])
        height_limit = float(container_size[2])
    cells_x = int(np.ceil(side_x / resolution))
    cells_y = int(np.ceil(side_y / resolution))
    heightmap = np.zeros((cells_x, cells_y))
    order = initial_order(selected_parts, rng, settings)
    candidate_points = [np.zeros(2)]
    placements = []
    for part_index in order:
        part = selected_parts[part_index]
        best_score = None
        best_choice = None
        for rotation, rotated_minimum, padded_dimensions in box_orientation_options(part, clearance):
            span_x = int(np.ceil(padded_dimensions[0] / resolution))
            span_y = int(np.ceil(padded_dimensions[1] / resolution))
            if span_x > cells_x or span_y > cells_y:
                continue
            for point in candidate_points:
                start_x = int(round(point[0] / resolution))
                start_y = int(round(point[1] / resolution))
                if start_x + span_x > cells_x or start_y + span_y > cells_y:
                    continue
                window = heightmap[start_x:start_x + span_x, start_y:start_y + span_y]
                base = float(window.max())
                top = base + padded_dimensions[2]
                if height_limit is not None and top > height_limit + 1e-9:
                    continue
                wasted = float((base - window).sum()) * resolution * resolution
                score = (top, wasted, point[1], point[0])
                if best_score is None or score < best_score:
                    best_score = score
                    best_choice = (point, start_x, start_y, span_x, span_y, base, rotation, rotated_minimum, padded_dimensions)
        if best_choice is None:
            continue
        point, start_x, start_y, span_x, span_y, base, rotation, rotated_minimum, padded_dimensions = best_choice
        heightmap[start_x:start_x + span_x, start_y:start_y + span_y] = base + padded_dimensions[2]
        corner = np.array([point[0], point[1], base])
        placements.append({"part_index": part_index, "rotation": rotation, "translation": corner + clearance / 2.0 - rotated_minimum})
        candidate_points = [existing for existing in candidate_points if not np.allclose(existing, point)]
        candidate_points.append(point + np.array([padded_dimensions[0], 0.0]))
        candidate_points.append(point + np.array([0.0, padded_dimensions[1]]))
    return placements


def wall_building(selected_parts, container_size, rng, settings):
    """Wall building (George and Robinson style). Parts are packed in vertical slices ("walls") along x: the first part of a wall sets its depth; the wall's y-z face is filled with 2D maximal empty rectangles, taking any remaining part (in order) whose box depth fits the wall in some orientation. When nothing fits, a new wall starts behind it. Open mode uses a square y-z face from footprint_side."""
    if container_size is not None:
        return wall_building_on_face(selected_parts, container_size, rng, settings, None)
    best_placements = []
    best_key = None
    for factor in (1.0, 1.25, 1.5, 2.0):
        placements = wall_building_on_face(selected_parts, None, rng, settings, factor)
        key = (len(placements), packing_density(selected_parts, placements))
        if best_key is None or key > best_key:
            best_key = key
            best_placements = placements
    return best_placements


def wall_building_on_face(selected_parts, container_size, rng, settings, face_factor):
    clearance = settings["clearance"]
    if container_size is None:
        face_y = face_factor * footprint_side(selected_parts, clearance)
        face_z = face_y
        depth_limit = None
    else:
        face_y = float(container_size[1])
        face_z = float(container_size[2])
        depth_limit = float(container_size[0])
    order = initial_order(selected_parts, rng, settings)
    remaining = list(order)
    placements = []
    wall_start = 0.0
    while remaining:
        wall_depth = None
        free_rectangles = [(np.zeros(2), np.array([face_y, face_z]))]
        placed_in_wall = False
        progress = True
        while progress:
            progress = False
            for part_index in list(remaining):
                part = selected_parts[part_index]
                best_score = None
                best_choice = None
                for rotation, rotated_minimum, padded_dimensions in box_orientation_options(part, clearance):
                    depth = padded_dimensions[0]
                    if wall_depth is not None and depth > wall_depth + 1e-9:
                        continue
                    if depth_limit is not None and wall_start + depth > depth_limit + 1e-9:
                        continue
                    for rectangle_minimum, rectangle_maximum in free_rectangles:
                        if np.any(rectangle_maximum - rectangle_minimum < padded_dimensions[1:] - 1e-9):
                            continue
                        score = (rectangle_minimum[1], rectangle_minimum[0], -depth)
                        if best_score is None or score < best_score:
                            best_score = score
                            best_choice = (rectangle_minimum.copy(), rotation, rotated_minimum, padded_dimensions)
                if best_choice is None:
                    continue
                rectangle_minimum, rotation, rotated_minimum, padded_dimensions = best_choice
                if wall_depth is None:
                    wall_depth = padded_dimensions[0]
                corner = np.array([wall_start, rectangle_minimum[0], rectangle_minimum[1]])
                placements.append({"part_index": part_index, "rotation": rotation, "translation": corner + clearance / 2.0 - rotated_minimum})
                remaining.remove(part_index)
                placed_in_wall = True
                progress = True
                box_minimum = rectangle_minimum
                box_maximum = rectangle_minimum + padded_dimensions[1:]
                new_rectangles = []
                for low, high in free_rectangles:
                    if np.any(box_minimum >= high - 1e-9) or np.any(box_maximum <= low + 1e-9):
                        new_rectangles.append((low, high))
                        continue
                    for axis in range(2):
                        if box_minimum[axis] > low[axis] + 1e-9:
                            piece_high = high.copy()
                            piece_high[axis] = box_minimum[axis]
                            new_rectangles.append((low.copy(), piece_high))
                        if box_maximum[axis] < high[axis] - 1e-9:
                            piece_low = low.copy()
                            piece_low[axis] = box_maximum[axis]
                            new_rectangles.append((piece_low, high.copy()))
                kept = []
                for number, (low, high) in enumerate(new_rectangles):
                    contained = False
                    for other_number, (other_low, other_high) in enumerate(new_rectangles):
                        if other_number != number and np.all(other_low <= low + 1e-9) and np.all(other_high >= high - 1e-9) and not (np.allclose(other_low, low) and np.allclose(other_high, high) and other_number > number):
                            contained = True
                            break
                    if not contained:
                        kept.append((low, high))
                free_rectangles = kept
                break
        if not placed_in_wall:
            break
        wall_start = wall_start + wall_depth
    return placements


def dblf_24(selected_parts, container_size, rng, settings):
    """Deep-bottom-left-fill on voxels with all 24 axis-aligned orientations. Like voxel_bottom_left but every orientation is tried (not only the 6 distinct box shapes) and the position is chosen deepest (lowest z), then bottom (y), then left (x) inside a fixed square footprint (footprint_side), instead of smallest bounding box. Container mode is the same with the real container."""
    run_settings = dict(settings)
    run_settings["voxel_orientations"] = "all"
    clearance = settings["clearance"]
    order = initial_order(selected_parts, rng, settings)
    if container_size is not None:
        return voxel_place_sequence(selected_parts, order, None, np.asarray(container_size, dtype=float), run_settings)
    best_placements = []
    best_key = None
    for factor in (1.0, 1.4):
        side = factor * footprint_side(selected_parts, clearance) + 2.0 * clearance + 2.0 * settings["voxel_pitch"]
        tall = 6.0 * side
        placements = voxel_place_sequence(selected_parts, order, None, np.array([side, side, tall]), run_settings)
        key = (len(placements), packing_density(selected_parts, placements))
        if best_key is None or key > best_key:
            best_key = key
            best_placements = placements
        if len(placements) == len(selected_parts) and factor == 1.0:
            break
    return best_placements


def extreme_point_state_new(selected_parts):
    return {"points": [np.zeros(3)], "minimums": np.zeros((0, 3)), "maximums": np.zeros((0, 3)), "overall": np.zeros(3), "placements": [], "placed_volume": 0.0}


def extreme_point_state_extend(state, selected_parts, part_index, orientation_number, container_size, clearance):
    """Place one part with one orientation at the best extreme point of a state; returns the new state or None if it does not fit."""
    part = selected_parts[part_index]
    rotation, rotated_minimum, padded_dimensions = box_orientation_options(part, clearance)[orientation_number]
    best_score = None
    best_point = None
    for point in state["points"]:
        box_maximum = point + padded_dimensions
        if container_size is not None and np.any(box_maximum > np.asarray(container_size) + 1e-9):
            continue
        hits = np.all(point < state["maximums"] - 1e-9, axis=1) & np.all(state["minimums"] < box_maximum - 1e-9, axis=1)
        if np.any(hits):
            continue
        if container_size is None:
            score = (float(np.prod(np.maximum(state["overall"], box_maximum))), point[2], point[1], point[0])
        else:
            score = (point[2], point[1], point[0])
        if best_score is None or score < best_score:
            best_score = score
            best_point = point
    if best_point is None:
        return None
    point = best_point
    new_state = {}
    new_state["minimums"] = np.vstack([state["minimums"], point])
    new_state["maximums"] = np.vstack([state["maximums"], point + padded_dimensions])
    new_state["overall"] = np.maximum(state["overall"], point + padded_dimensions)
    new_state["placements"] = state["placements"] + [{"part_index": part_index, "rotation": rotation, "translation": point + clearance / 2.0 - rotated_minimum, "orientation_number": orientation_number}]
    new_state["placed_volume"] = state["placed_volume"] + part["volume"]
    new_state["points"] = [existing for existing in state["points"] if not np.allclose(existing, point)] + [point + np.array([padded_dimensions[0], 0.0, 0.0]), point + np.array([0.0, padded_dimensions[1], 0.0]), point + np.array([0.0, 0.0, padded_dimensions[2]])]
    return new_state


def beam_search(selected_parts, container_size, rng, settings):
    """Beam search over placement sequences with the extreme-points box decoder. Keeps the best settings["beam_width"] (default 8) partial packings; each step extends every one of them by every remaining part in every orientation and keeps the best children. Children are scored by the density the packing would reach if the remaining parts fit perfectly: (placed + remaining volume) / max(current box volume, placed + remaining volume). Deterministic; stops early at the time cap settings["search_seconds"] and finishes greedily."""
    clearance = settings["clearance"]
    beam_width = int(settings.get("beam_width", 8))
    part_count = len(selected_parts)
    total_volume = sum(part["volume"] for part in selected_parts)
    start_time = time.perf_counter()
    beam = [(extreme_point_state_new(selected_parts), frozenset(range(part_count)))]
    for step in range(part_count):
        children = []
        out_of_time = time.perf_counter() - start_time > settings["search_seconds"]
        for state, remaining in beam:
            candidate_parts = sorted(remaining, key=lambda index: -selected_parts[index]["obb_volume"])
            if out_of_time:
                candidate_parts = candidate_parts[:1]
            for part_index in candidate_parts:
                option_count = len(box_orientation_options(selected_parts[part_index], clearance))
                for orientation_number in range(option_count):
                    new_state = extreme_point_state_extend(state, selected_parts, part_index, orientation_number, container_size, clearance)
                    if new_state is None:
                        continue
                    remaining_volume = total_volume - new_state["placed_volume"]
                    box_volume = float(np.prod(new_state["overall"]))
                    estimate = (new_state["placed_volume"] + remaining_volume) / max(box_volume, new_state["placed_volume"] + remaining_volume, 1e-9)
                    children.append((estimate, len(new_state["placements"]), new_state, remaining - {part_index}))
        if not children:
            break
        children.sort(key=lambda child: (-child[1], -child[0]))
        beam = [(child[2], child[3]) for child in children[:beam_width]]
    best_state = max(beam, key=lambda item: (len(item[0]["placements"]), item[0]["placed_volume"] / max(float(np.prod(item[0]["overall"])), 1e-9)))[0]
    return best_state["placements"]


def grasp_ems(selected_parts, container_size, rng, settings):
    """GRASP on empty maximal spaces: repeated randomized greedy constructions within the time cap settings["search_seconds"]. Each construction perturbs the largest-first order (swaps of neighbours with probability 0.3) and, for every part, picks at random among the 3 best (orientation, empty box) choices instead of the single best. The densest valid construction is kept. Randomness lets EMS escape the ties and local traps of pure greedy."""
    start_time = time.perf_counter()
    base_order = initial_order(selected_parts, rng, settings)
    best_placements = []
    best_key = None
    construction = 0
    while True:
        order = list(base_order)
        if construction > 0:
            for position in range(len(order) - 1):
                if rng.uniform() < 0.3:
                    order[position], order[position + 1] = order[position + 1], order[position]
        placements = ems_construct(selected_parts, order, container_size, settings, rng if construction > 0 else None, 3)
        if placements:
            minimums = []
            maximums = []
            placed_volume = 0.0
            for placement in placements:
                part = selected_parts[placement["part_index"]]
                rotated_minimum, rotated_maximum = nesting_core.rotated_bounds(part, placement["rotation"])
                minimums.append(rotated_minimum + placement["translation"])
                maximums.append(rotated_maximum + placement["translation"])
                placed_volume = placed_volume + part["volume"]
            density = placed_volume / float(np.prod(np.max(maximums, axis=0) - np.min(minimums, axis=0)))
            key = (len(placements), density)
            if best_key is None or key > best_key:
                best_key = key
                best_placements = placements
        construction = construction + 1
        if time.perf_counter() - start_time > settings["search_seconds"]:
            break
    return best_placements


def ems_construct(selected_parts, order, container_size, settings, rng, candidate_list_size):
    """One empty-maximal-spaces construction in a given order. rng = None picks the best (orientation, box) for each part (plain EMS); otherwise a random pick among the candidate_list_size best."""
    clearance = settings["clearance"]
    if container_size is None:
        side = 4.0 * footprint_side(selected_parts, clearance) + 2.0 * max(max(part["obb_extents"]) for part in selected_parts) + 2.0 * clearance
        empty_boxes = [(np.zeros(3), np.full(3, side))]
    else:
        empty_boxes = [(np.zeros(3), np.asarray(container_size, dtype=float))]
    smallest_part_side = min(min(options[0][2]) for options in [box_orientation_options(other, clearance) for other in selected_parts])
    overall_maximum = np.zeros(3)
    placements = []
    for part_index in order:
        part = selected_parts[part_index]
        choices = []
        for rotation, rotated_minimum, padded_dimensions in box_orientation_options(part, clearance):
            for empty_minimum, empty_maximum in empty_boxes:
                if np.any(empty_maximum - empty_minimum < padded_dimensions - 1e-9):
                    continue
                box_maximum = empty_minimum + padded_dimensions
                if container_size is None:
                    score = (float(np.prod(np.maximum(overall_maximum, box_maximum))), empty_minimum[2], empty_minimum[1], empty_minimum[0])
                else:
                    score = (empty_minimum[2], empty_minimum[1], empty_minimum[0])
                choices.append((score, empty_minimum.copy(), rotation, rotated_minimum, padded_dimensions))
        if not choices:
            continue
        choices.sort(key=lambda choice: choice[0])
        if rng is None:
            chosen = choices[0]
        else:
            chosen = choices[int(rng.integers(0, min(candidate_list_size, len(choices))))]
        score, box_minimum, rotation, rotated_minimum, padded_dimensions = chosen
        box_maximum = box_minimum + padded_dimensions
        overall_maximum = np.maximum(overall_maximum, box_maximum)
        placements.append({"part_index": part_index, "rotation": rotation, "translation": box_minimum + clearance / 2.0 - rotated_minimum})
        new_empty_boxes = []
        for empty_minimum, empty_maximum in empty_boxes:
            if np.any(box_minimum >= empty_maximum - 1e-9) or np.any(box_maximum <= empty_minimum + 1e-9):
                new_empty_boxes.append((empty_minimum, empty_maximum))
                continue
            for axis in range(3):
                if box_minimum[axis] > empty_minimum[axis] + 1e-9:
                    piece_maximum = empty_maximum.copy()
                    piece_maximum[axis] = box_minimum[axis]
                    new_empty_boxes.append((empty_minimum.copy(), piece_maximum))
                if box_maximum[axis] < empty_maximum[axis] - 1e-9:
                    piece_minimum = empty_minimum.copy()
                    piece_minimum[axis] = box_maximum[axis]
                    new_empty_boxes.append((piece_minimum, empty_maximum.copy()))
        new_empty_boxes = [(low, high) for low, high in new_empty_boxes if np.all(high - low >= smallest_part_side - 1e-9)]
        kept = []
        for number, (low, high) in enumerate(new_empty_boxes):
            contained = False
            for other_number, (other_low, other_high) in enumerate(new_empty_boxes):
                if other_number == number:
                    continue
                if np.all(other_low <= low + 1e-9) and np.all(other_high >= high - 1e-9):
                    if not (np.allclose(other_low, low) and np.allclose(other_high, high) and other_number > number):
                        contained = True
                        break
            if not contained:
                kept.append((low, high))
        empty_boxes = kept
    return placements


ALGORITHMS = {"random_scatter": random_scatter, "random_rejection": random_rejection, "shelf_packing": shelf_packing, "box_bottom_left": box_bottom_left, "box_extreme_points": box_extreme_points, "voxel_bottom_left": voxel_bottom_left, "force_based": force_based, "heightfield_drop": heightfield_drop, "simulated_annealing": simulated_annealing, "genetic_algorithm": genetic_algorithm, "force_based_v2": force_based_v2, "empty_maximal_spaces": empty_maximal_spaces, "genetic_heightfield": genetic_heightfield, "best_of_fast": best_of_fast, "genetic_box": genetic_box, "skyline_3d": skyline_3d, "wall_building": wall_building, "dblf_24": dblf_24, "beam_search": beam_search, "grasp_ems": grasp_ems}

# The thirteen compared in the benchmark ("all"). random_scatter is only for pictures.
BENCHMARK_ALGORITHMS = ["random_rejection", "shelf_packing", "box_bottom_left", "box_extreme_points", "empty_maximal_spaces", "voxel_bottom_left", "force_based", "heightfield_drop", "simulated_annealing", "genetic_algorithm", "force_based_v2", "genetic_heightfield", "best_of_fast", "genetic_box", "skyline_3d", "wall_building", "dblf_24", "beam_search", "grasp_ems"]
NEW_ALGORITHMS_2026_11_10 = ["skyline_3d", "wall_building", "dblf_24", "beam_search", "grasp_ems"]

# Algorithms with randomness get several tries per trial; the best valid result (highest density) is kept. The two search algorithms already spend their time budget on one try.
RANDOMIZED_ALGORITHMS = ["random_scatter", "random_rejection", "force_based", "force_based_v2"]

# Algorithms where placement order means something (the force-based ones move all parts at once).
ORDERED_ALGORITHMS = ["random_rejection", "shelf_packing", "box_bottom_left", "box_extreme_points", "empty_maximal_spaces", "voxel_bottom_left", "heightfield_drop", "simulated_annealing", "genetic_algorithm", "genetic_heightfield", "best_of_fast", "genetic_box", "skyline_3d", "wall_building", "dblf_24", "beam_search", "grasp_ems"]


def run_algorithm(algorithm_name, selected_parts, container_size, seed, settings, check_pitch):
    """Run one algorithm on one part set. Randomized algorithms get settings["restarts"] tries and keep the best (valid first, then highest density). Returns (placements, result, total_seconds)."""
    try_count = settings["restarts"] if algorithm_name in RANDOMIZED_ALGORITHMS else 1
    best_placements = None
    best_result = None
    best_key = None
    start_time = time.perf_counter()
    for try_number in range(try_count):
        algorithm_generator = np.random.default_rng(seed * 1009 + try_number + 1000003)
        placements = ALGORITHMS[algorithm_name](selected_parts, container_size, algorithm_generator, settings)
        result = nesting_core.evaluate_packing(selected_parts, placements, container_size, check_pitch, settings["clearance"])
        key = (result["valid"], result["placed_fraction"], result["density"])
        if best_key is None or key > best_key:
            best_key = key
            best_placements = placements
            best_result = result
    total_seconds = time.perf_counter() - start_time
    if algorithm_name not in ORDERED_ALGORITHMS:
        best_result["placement_order"] = []
    return best_placements, best_result, total_seconds
