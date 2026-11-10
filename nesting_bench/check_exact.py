"""
Exact verification of packings: for a few random part sets, run every algorithm and intersect every pair of placed meshes with manifold3d (exact boolean).
Reports the largest pairwise intersection volume per algorithm (should be 0) and compares with the voxel overlap estimate.

    python check_exact.py --datasets simple_concave real_shapes --trials 3 --k 8
"""

import argparse
import numpy as np
import trimesh
import manifold3d
import nesting_core
import algorithms


parser = argparse.ArgumentParser()
parser.add_argument("--algorithms", nargs="+", default=["all"])
parser.add_argument("--datasets", nargs="+", default=["simple_concave", "real_shapes", "cuboids"])
parser.add_argument("--k", type=int, default=8)
parser.add_argument("--trials", type=int, default=3)
parser.add_argument("--mode", default="open", choices=["open", "container"])
parser.add_argument("--container", type=float, nargs=3, default=[100.0, 100.0, 100.0])
parser.add_argument("--seed", type=int, default=0)
arguments = parser.parse_args()

algorithm_names = algorithms.BENCHMARK_ALGORITHMS if arguments.algorithms == ["all"] else arguments.algorithms
settings = dict(algorithms.DEFAULT_SETTINGS)
check_pitch = settings["voxel_pitch"] / 2.0
container_size = None if arguments.mode == "open" else np.array(arguments.container)


def to_manifold(mesh):
    mesh_data = manifold3d.Mesh(vert_properties=np.asarray(mesh.vertices, dtype=np.float32), tri_verts=np.asarray(mesh.faces, dtype=np.uint32))
    return manifold3d.Manifold(mesh_data)


print("dataset          algorithm             trial  valid(voxel)  voxel overlap %  exact overlap mm^3  min gap mm")
for dataset_name in arguments.datasets:
    all_parts = nesting_core.load_parts(dataset_name, check_pitch, 1.0)
    for algorithm_name in algorithm_names:
        worst_exact = 0.0
        for trial in range(arguments.trials):
            selection_generator = np.random.default_rng(arguments.seed + trial)
            selected_indices = selection_generator.choice(len(all_parts), size=arguments.k, replace=arguments.k > len(all_parts))
            selected_parts = [all_parts[index] for index in selected_indices]
            placements, result, run_seconds = algorithms.run_algorithm(algorithm_name, selected_parts, container_size, arguments.seed + trial, settings, check_pitch)
            world_manifolds = [to_manifold(nesting_core.world_mesh(selected_parts[placement["part_index"]], placement)) for placement in placements]
            exact_overlap = 0.0
            for first in range(len(world_manifolds)):
                for second in range(first + 1, len(world_manifolds)):
                    intersection = world_manifolds[first] ^ world_manifolds[second]
                    exact_overlap = max(exact_overlap, float(intersection.volume()))
            worst_exact = max(worst_exact, exact_overlap)
            print(dataset_name.ljust(17) + algorithm_name.ljust(22) + str(trial).rjust(5) + str(result["valid"]).rjust(14) + format(100 * result["overlap_fraction"], ".3f").rjust(17) + format(exact_overlap, ".4f").rjust(20) + format(result["minimum_gap"], ".2f").rjust(12), flush=True)
        print("  worst exact overlap for " + algorithm_name + " on " + dataset_name + ": " + format(worst_exact, ".4f") + " mm^3")
