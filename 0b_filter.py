"""
NYC Parks Data Filter
Filter the parks dataset based on specified criteria (e.g., typecategory whitelist)
"""

import geopandas as gpd
import os

print("Loading NYC Parks GeoJSON...")
SOURCE_DATA_FILE = "./source_data/Parks_Properties_20251021_modified.geojson"
OUTPUT_DATA_FILE = "./output_data/0b_parks_filtered.geojson"
OUTPUT_DATA_FILE_REMOVED = "./output_data/0b_parks_filtered_removed.geojson"

gdf = gpd.read_file(SOURCE_DATA_FILE)

print(f"Total parks before filtering: {len(gdf)}")

# Exluced typecategories are:
# "Lot", "Strip", 'Operations", "Retired N/A", "Parkway", "Mall", "Undeveloped"
# Filter by typecategory whitelist
TYPECATEGORY_WHITELIST = [
    "Triangle/Plaza",
    "Garden",
    "Neighborhood Park",
    "Jointly Operated Playground",
    "Playground",
    "Community Park",
    "Nature Area",
    "Recreational Field/Courts",
    "Waterfront Facility",
    "Flagship Park",
    "Managed Sites",
    "Historic House Park",
    "Cemetery",
]


filter_mask = gdf["typecategory"].isin(TYPECATEGORY_WHITELIST)

gdf_filtered = gdf[filter_mask]
gdf_filtered_out = gdf[~gdf.index.isin(gdf_filtered.index)]

print(f"Total parks after filtering (kept): {len(gdf_filtered)}")
print(f"Total parks filtered out (removed): {len(gdf_filtered_out)}")

# Create data directory if it doesn't exist
os.makedirs("data", exist_ok=True)

# Save filtered data (kept)
print(f"\nSaving filtered data to {OUTPUT_DATA_FILE}...")
gdf_filtered.to_file(OUTPUT_DATA_FILE, driver="GeoJSON")

# Save filtered-out data (removed)
print(f"Saving filtered-out data to {OUTPUT_DATA_FILE_REMOVED}...")
gdf_filtered_out.to_file(OUTPUT_DATA_FILE_REMOVED, driver="GeoJSON")

print("\nDone!")
