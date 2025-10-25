# NYC Park Study

This project is a study of the various shapes of NYC parks.

## Setup

### Python Environment

Set up the python environment with the following command:

```bash
uv sync
```

### C++ `geos` Library

Set up the C++ `geos` library with the following commands (macOS):

```bash
brew install geos
```

For other platforms, please refer to the [GEOS: Install Packages](https://libgeos.org/usage/install/) documentation.

## Scripts

These scripts take the `source_data/Parks_Properties_20251021_modified.geojson` as input and output files in the `output_data/` directory.

### `0a_analysis.py`

```bash
uv run 0a_analysis.py
```

Analyze the basic statistics and distributions of the original parks dataset. Mainly used to identify `typecategory` and `subcategory` distributions for later filtering.

### `0b_filter.py`

```bash
uv run 0b_filter.py
```

Filter the parks dataset based on specified criteria (e.g., typecategory whitelist). This make sure the dataset only contains what the public would consider "parks", excluding things like "lot", "strip", "parkway" etc.

### `0c_basic_augment.py`

```bash
uv run 0c_basic_augment.py
```

Add geometric calculations and analysis fields to the filtered parks dataset. This script enriches the data with 16 additional fields:

- Core Measurements
  - `area_sqm`: Area in square meters
  - `perimeter_m`: Perimeter in meters
  - `num_vertices`: Number of vertices in the geometry
  - `num_polygons`: Number of separate polygons
- Location
  - `centroid_lon`: Centroid longitude
  - `centroid_lat`: Centroid latitude
- Shape Characteristics:
  - `bbox_width`: Bounding box width in meters
  - `bbox_height`: Bounding box height in meters
  - `aspect_ratio`: Width/height ratio
  - `convex_hull_area`: Area of the convex hull in square meters
  - `convexity_ratio`: Ratio of actual area to convex hull area (1.0 = already convex)
  - `convex_hull_polygon`: Convex hull geometry as GeoJSON polygon
- Multi-Polygon Analysis
  - `polygon_areas_desc`: List of individual polygon areas (descending)
  - `largest_polygon_area`: Area of the largest polygon
  - `smallest_polygon_area`: Area of the smallest polygon
  - `polygon_area_ratio`: Ratio of largest to smallest polygon (indicates fragmentation)

### `1a_concave_hull.cpp`

Create concave hulls for the parks dataset. It's written in C++ to utilize the `ConcaveHullOfPolygons` class from the `geos` library. Traditionally, concave hulls are performed on points, rather than polygons (see this blog post for more details: [Concave Hull of Polygons](https://lin-ear-th-inking.blogspot.com/2022/05/concave-hulls-of-polygons.html)). Only `JTS` and `geos` ([doc](https://libgeos.org/doxygen/classgeos_1_1algorithm_1_1hull_1_1ConcaveHullOfPolygons.html)) implemented it.

```bash
make run
```

### `1b_concave_hull_analysis.py`
