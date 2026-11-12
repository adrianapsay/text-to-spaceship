"""Explicit detail specs (shapes_detail.py) for parts whose detail is not derived from the envelope kind. Keys are part ids."""
DETAIL_SHAPES = {
    "aac_mtq800": {"kind": "rod_with_driver", "x": 250, "y": 67, "z": 35, "rod_diameter": 14, "board_x": 45, "board_y": 40, "board_z": 6},
    "gomspace_nanotorque_gsw600_pyramid": {"kind": "wheel_pyramid", "x": 95, "y": 95, "z": 61.6},
    "redwire_micro_sun_sensor": {"kind": "pc104_board", "x": 23, "y": 15.3, "z": 1.6, "components_height": 4.4, "hole_diameter": 1.0},
    "bradford_mini_fine_sun_sensor": {"kind": "box_with_ears", "x": 50, "y": 46, "z": 17, "ear_length": 8, "ear_thickness": 3},
    "nanoavionics_4rw0": {"kind": "wheel_pyramid_round", "x": 92.5, "y": 92.5, "z": 51.2},
    "needronix_eagle_fss": {"kind": "box_with_ears", "x": 15.0, "y": 15.5, "z": 4.6, "ear_length": 2.5, "ear_thickness": 1.2, "hole_diameter": 1.2, "color": [0.55, 0.56, 0.58]},
    "cgstl_cgudss01": {"kind": "box_with_ears", "x": 48.0, "y": 36.0, "z": 16.9, "ear_length": 7, "ear_thickness": 3, "color": [0.12, 0.12, 0.13]},
    "adcole_mai_smallsat_sun_sensor": {"kind": "pc104_board", "x": 50.8, "y": 19.05, "z": 1.6, "components_height": 0.43, "hole_diameter": 1.0},
    "leonardo_a_str": {"kind": "camera_box_lens", "x": 195, "y": 175, "z": 100, "lens_diameter": 80, "lens_length": 190.5, "baffle_diameter": 170},
    "terma_t1_baffle_30deg": {"kind": "baffle_cone", "diameter": 125, "length": 165},
    "terma_t1_baffle_26deg": {"kind": "baffle_cone", "diameter": 155, "length": 213},
}
