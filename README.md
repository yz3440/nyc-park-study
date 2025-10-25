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

### `1a_concave_hull.cpp`

Create concave hulls for the parks dataset.

```bash
make run
```
