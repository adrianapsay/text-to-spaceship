"""
Render 3 example parts per dataset to slide_images/dataset_<name>.png (used by make_slides.py). Needs pyvista; run it off screen.

    python render_examples.py
"""

import os
import numpy as np
import pyvista
import nesting_core

pyvista.OFF_SCREEN = True
output_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slide_images")
os.makedirs(output_folder, exist_ok=True)
colors = ["#2a78d6", "#eb6834", "#1baf7a"]
for dataset_name in nesting_core.list_datasets():
    parts = nesting_core.load_parts(dataset_name, 2.0, 1.0)
    picked = [parts[index] for index in np.random.default_rng(3).choice(len(parts), size=3, replace=False)]
    plotter = pyvista.Plotter(off_screen=True, window_size=[900, 360])
    plotter.set_background("white")
    cursor_x = 0.0
    for number, part in enumerate(picked):
        mesh = part["mesh"]
        extent = mesh.bounds[1] - mesh.bounds[0]
        offset = np.array([cursor_x - mesh.bounds[0][0], 0.0, 0.0])
        face_array = np.hstack([np.full((len(mesh.faces), 1), 3), mesh.faces]).ravel()
        plotter.add_mesh(pyvista.PolyData(np.asarray(mesh.vertices) + offset, face_array), color=colors[number], smooth_shading=True, split_sharp_edges=True)
        cursor_x = cursor_x + extent[0] * 1.35
    plotter.view_isometric()
    plotter.camera.zoom(1.5)
    plotter.screenshot(os.path.join(output_folder, "dataset_" + dataset_name + ".png"))
    plotter.close()
    print("rendered " + dataset_name)
