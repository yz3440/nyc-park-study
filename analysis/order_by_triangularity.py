"""
NYC Parks Triangularity Analysis
Load parks data and order by triangularity metric
"""

import json
import os
import matplotlib.pyplot as plt
import numpy as np

# Create output directory if it doesn't exist
os.makedirs("analysis/output", exist_ok=True)

print("Loading NYC Parks with Concave Hull Analysis...")
with open("output_data/2a_parks_concave_hull_analysis.geojson", "r") as f:
    data = json.load(f)

features = data["features"]
print(f"Loaded {len(features)} parks")

# Count parks with triangularity data (using new flat field: ta_triangularity)
print("\nCounting parks with triangularity data...")
parks_with_data = sum(
    1 for f in features if f["properties"].get("ta_triangularity") is not None
)
parks_without_data = len(features) - parks_with_data
print(f"Parks with triangularity data: {parks_with_data}")
print(f"Parks without triangularity data: {parks_without_data}")

# Filter and sort parks by triangularity in descending order (highest to lowest, closest to 1.0 first)
print("\nOrdering parks by triangularity (closest to 1.0 = most triangular)...")
parks_with_triangularity = [
    f for f in features if f["properties"].get("ta_triangularity") is not None
]
parks_ordered = sorted(
    parks_with_triangularity,
    key=lambda f: f["properties"]["ta_triangularity"],
    reverse=True,
)

# Display statistics
print(f"\nTotal parks ordered by triangularity: {len(parks_ordered)}")

if parks_ordered:
    triangularities = [f["properties"]["ta_triangularity"] for f in parks_ordered]
    print(f"\nTriangularity range:")
    print(f"  Most triangular (highest): {max(triangularities):.4f}")
    print(f"  Least triangular (highest): {max(triangularities):.4f}")
    print(f"  Mean: {sum(triangularities) / len(triangularities):.4f}")
    sorted_t = sorted(triangularities)
    median_idx = len(sorted_t) // 2
    median = (
        sorted_t[median_idx]
        if len(sorted_t) % 2 == 1
        else (sorted_t[median_idx - 1] + sorted_t[median_idx]) / 2
    )
    print(f"  Median: {median:.4f}")

    # Display the 10 most triangular parks
    print("\n" + "=" * 80)
    print("TOP 10 MOST TRIANGULAR PARKS (closest to 1.0)")
    print("=" * 80)

    for feature in parks_ordered[:10]:
        props = feature["properties"]
        triangularity = props["ta_triangularity"]
        diff = abs(triangularity - 1.0)
        print(f"\n{props['name311']} ({props['borough']})")
        print(f"  Triangularity: {triangularity:.4f} (diff from 1.0: {diff:.4f})")
        print(f"  Area: {props['area_sqm']:,.0f} m²")

# Create histogram of triangularity values
print("\n" + "=" * 80)
print("Creating histogram of triangularity values...")

if parks_ordered:
    triangularities = [f["properties"]["ta_triangularity"] for f in parks_ordered]

    # Create figure and axis
    fig, ax = plt.subplots(figsize=(12, 6))

    # Create histogram with appropriate bins
    # Use log scale for bins since data is likely skewed
    bins = np.logspace(
        np.log10(min(triangularities)), np.log10(max(triangularities)), 50
    )
    n, bins, patches = ax.hist(triangularities, bins=bins, edgecolor="black", alpha=0.7)

    # Set log scale on x-axis
    ax.set_xscale("log")

    # Add vertical line at 1.0 (perfect triangle)
    ax.axvline(
        x=1.0, color="red", linestyle="--", linewidth=2, label="Perfect Triangle (1.0)"
    )

    # Labels and title
    ax.set_xlabel("Triangularity (ta_triangularity)", fontsize=12)
    ax.set_ylabel("Number of Parks", fontsize=12)
    ax.set_title(
        "Distribution of Park Triangularity Values (Log Scale)",
        fontsize=14,
        fontweight="bold",
    )
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Save the plot
    histogram_file = "analysis/output/triangularity_histogram.png"
    plt.tight_layout()
    plt.savefig(histogram_file, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"Saved histogram to: {histogram_file}")

    # Also create a linear scale version focused on values near 1.0
    fig, ax = plt.subplots(figsize=(12, 6))

    # Filter values between 0 and 5 for better visualization
    filtered_triangularities = [t for t in triangularities if t <= 5]

    ax.hist(filtered_triangularities, bins=50, edgecolor="black", alpha=0.7)
    ax.axvline(
        x=1.0, color="red", linestyle="--", linewidth=2, label="Perfect Triangle (1.0)"
    )

    ax.set_xlabel("Triangularity (ta_triangularity)", fontsize=12)
    ax.set_ylabel("Number of Parks", fontsize=12)
    ax.set_title(
        "Distribution of Park Triangularity Values (0-5 range, Linear Scale)",
        fontsize=14,
        fontweight="bold",
    )
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Save the linear plot
    histogram_linear_file = "analysis/output/triangularity_histogram_linear.png"
    plt.tight_layout()
    plt.savefig(histogram_linear_file, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"Saved linear histogram to: {histogram_linear_file}")
    print(
        f"  (Filtered to values 0-5, {len(filtered_triangularities)}/{len(triangularities)} parks)"
    )

# Save ordered results to GeoJSON with one feature per line
print("\n" + "=" * 80)
print("Saving ordered results...")

output_file = "analysis/output/parks_ordered_by_triangularity.geojson"

# Create GeoJSON structure
output_data = {"type": "FeatureCollection", "features": parks_ordered}

# Write with one feature per line
with open(output_file, "w") as f:
    # Write header
    f.write("{\n")
    f.write(f'"type": "{output_data["type"]}",\n')

    # Write features array opening
    f.write('"features": [\n')

    # Write each feature on its own line
    for i, feature in enumerate(parks_ordered):
        feature_json = json.dumps(feature)
        if i < len(parks_ordered) - 1:
            f.write(f"{feature_json},\n")
        else:
            f.write(f"{feature_json}\n")

    # Close features array and main object
    f.write("]\n")
    f.write("}\n")

print(f"Saved to: {output_file}")
print(f"Total parks saved: {len(parks_ordered)}")

# Export simplified list for parks with "square" in eapply
print("\n" + "=" * 80)
print("Exporting squares list (eapply contains 'square')...")

squares_list = []
for feature in parks_ordered:
    props = feature["properties"]
    eapply = props.get("eapply", "")
    if eapply and "square" in eapply.lower():
        squares_list.append(
            {"eapply": eapply, "ta_triangularity": props["ta_triangularity"]}
        )

squares_output_file = "analysis/output/squares_by_triangularity.json"

# Write with one entry per line
with open(squares_output_file, "w") as f:
    f.write("[\n")
    for i, entry in enumerate(squares_list):
        entry_json = json.dumps(entry)
        if i < len(squares_list) - 1:
            f.write(f"{entry_json},\n")
        else:
            f.write(f"{entry_json}\n")
    f.write("]\n")

print(f"Saved to: {squares_output_file}")
print(f"Total squares saved: {len(squares_list)}")

# Export parks with high triangularity (> 0.6)
print("\n" + "=" * 80)
print("Exporting parks with high triangularity (> 0.6)...")

high_triangularity_threshold = 0.9
high_triangularity_parks = [
    f
    for f in parks_ordered
    if f["properties"]["ta_triangularity"] > high_triangularity_threshold
]

print(
    f"Found {len(high_triangularity_parks)} parks with triangularity > {high_triangularity_threshold}"
)

if high_triangularity_parks:
    # Save as GeoJSON
    high_triangularity_output = "analysis/output/parks_high_triangularity.geojson"

    output_data = {"type": "FeatureCollection", "features": high_triangularity_parks}

    # Write with one feature per line
    with open(high_triangularity_output, "w") as f:
        # Write header
        f.write("{\n")
        f.write(f'"type": "{output_data["type"]}",\n')

        # Write features array opening
        f.write('"features": [\n')

        # Write each feature on its own line
        for i, feature in enumerate(high_triangularity_parks):
            feature_json = json.dumps(feature)
            if i < len(high_triangularity_parks) - 1:
                f.write(f"{feature_json},\n")
            else:
                f.write(f"{feature_json}\n")

        # Close features array and main object
        f.write("]\n")
        f.write("}\n")

    print(f"Saved to: {high_triangularity_output}")

    # Display top 5 from this subset
    print(f"\nTop 5 parks from high triangularity subset:")
    for feature in high_triangularity_parks[:5]:
        props = feature["properties"]
        print(
            f"  {props['name311']} ({props['borough']}): {props['ta_triangularity']:.4f}"
        )

print("\nDone!")
