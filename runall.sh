#!/bin/bash

# Run data fixes
uv run source_data/0_fix_small_parks.py
uv run source_data/99_apply_mod.py

# Run analysis
uv run 0a_analysis.py
uv run 0b_filter.py
uv run 0c_basic_augment.py
make run
uv run 2a_concave_hull_analysis.py

# Run image generation
uv run 3_generate_park_images.py