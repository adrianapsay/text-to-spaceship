# Order study findings

Same part sets as the benchmark; every algorithm packed each set under its default order (largest box volume first), five fixed heuristic orders and random permutations. Numbers are density (parts volume / bounding box volume). Paired differences are per part set, pooled over categories and k, with 99% confidence intervals (Student t).

| algorithm | sets | random spread (best-worst, same set) | default | best other fixed order | gain vs default (99% CI) | random mean vs default | best of the random orders vs default (99% CI) |
|---|---|---|---|---|---|---|---|
| random_rejection | 120 | 0.044 | 0.130 | big+convex first | -0.002 (-0.005 to -0.000) | -0.027 | -0.004 (-0.008 to +0.000) |
| shelf_packing | 120 | 0.083 | 0.287 | compact first | -0.012 (-0.021 to -0.004) | -0.033 | +0.012 (+0.001 to +0.022) |
| box_bottom_left | 120 | 0.104 | 0.332 | big+convex first | -0.003 (-0.008 to +0.003) | -0.032 | +0.016 (+0.008 to +0.024) |
| box_extreme_points | 120 | 0.124 | 0.402 | big+convex first | -0.002 (-0.004 to +0.001) | -0.052 | -0.002 (-0.008 to +0.004) |
| empty_maximal_spaces | 120 | 0.101 | 0.407 | big+convex first | -0.001 (-0.004 to +0.001) | -0.041 | +0.001 (-0.005 to +0.006) |
| skyline_3d | 120 | 0.091 | 0.205 | compact first | +0.002 (-0.006 to +0.010) | -0.013 | +0.037 (+0.026 to +0.048) |
| wall_building | 120 | 0.120 | 0.351 | big+convex first | +0.003 (+0.001 to +0.005) significant | -0.043 | +0.015 (+0.009 to +0.022) |
| voxel_bottom_left | 120 | 0.095 | 0.411 | big+convex first | -0.001 (-0.004 to +0.003) | -0.036 | +0.005 (-0.001 to +0.011) |
| heightfield_drop | 120 | 0.108 | 0.389 | big+convex first | +0.000 (-0.004 to +0.004) | -0.035 | +0.015 (+0.009 to +0.020) |
| dblf_24 | 120 | 0.093 | 0.352 | big+convex first | -0.004 (-0.008 to +0.000) | -0.039 | +0.008 (-0.001 to +0.016) |
| best_of_fast | 120 | 0.089 | 0.427 | big+convex first | -0.001 (-0.004 to +0.001) | -0.036 | +0.004 (-0.001 to +0.010) |
| simulated_annealing | 120 | 0.051 | 0.403 | big+convex first | -0.001 (-0.005 to +0.002) | -0.010 | +0.015 (+0.010 to +0.020) |
| genetic_algorithm | 120 | 0.025 | 0.409 | big+convex first | -0.000 (-0.003 to +0.002) | -0.010 | +0.004 (-0.001 to +0.009) |
| genetic_heightfield | 120 | 0.034 | 0.418 | big+convex first | +0.002 (-0.001 to +0.005) | -0.009 | +0.009 (+0.004 to +0.013) |
| genetic_box | 120 | 0.031 | 0.416 | big+convex first | +0.001 (-0.001 to +0.003) | -0.014 | +0.002 (-0.003 to +0.006) |
| beam_search (partial, still running) | 13 | 0.002 | 0.220 | convex first | +0.001 (-0.002 to +0.003) | +0.000 | +0.001 (-0.003 to +0.005) |
| grasp_ems (partial, still running) | 10 | 0.029 | 0.288 | big+convex first | -0.001 (-0.006 to +0.005) | -0.015 | -0.001 (-0.008 to +0.005) |

volume desc is the default order itself (same sort key), so it is left out of 'best other fixed order'.

The last column is what a cheap order search buys: run the packer under the 20 (8 for search methods) random orders of the same parts and keep the best. For constructive packers that is 20 runs of 0.1 s.

Reading: spread is how much the same parts can change density by order alone (large = order matters). A gain whose 99% interval excludes 0 means that fixed order beats largest-first on average. Random mean vs default below 0 means largest-first is better than a typical random order.
