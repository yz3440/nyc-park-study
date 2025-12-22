"""
NYC Parks Rectangularity Analysis
Load parks data and order by rotation degrees for highly rectangular parks (>0.9 rectangularity)
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

# Count parks with rectangularity data
print("\nCounting parks with rectangularity data...")
parks_with_data = sum(
    1 for f in features if f["properties"].get("ra_rectangularity") is not None
)
parks_without_data = len(features) - parks_with_data
print(f"Parks with rectangularity data: {parks_with_data}")
print(f"Parks without rectangularity data: {parks_without_data}")

# Filter parks by rectangularity > 0.9
print("\nFiltering parks with rectangularity > 0.9...")
rectangular_parks = [
    f
    for f in features
    if f["properties"].get("ra_rectangularity") is not None
    and f["properties"]["ra_rectangularity"] > 0.9
]
print(f"Parks with rectangularity > 0.9: {len(rectangular_parks)}")

# Sort by rotation degrees
print("\nOrdering rectangular parks by rotation degrees...")
parks_ordered = sorted(
    rectangular_parks,
    key=lambda f: f["properties"].get("ra_mrr_rotation_degrees", 0),
    reverse=False,  # Ascending order (0° to 90°)
)

# Display statistics
print(f"\nTotal rectangular parks (>0.9): {len(parks_ordered)}")

if parks_ordered:
    rectangularities = [f["properties"]["ra_rectangularity"] for f in parks_ordered]
    rotations = [f["properties"]["ra_mrr_rotation_degrees"] for f in parks_ordered]

    print(f"\nRectangularity range:")
    print(f"  Highest: {max(rectangularities):.4f}")
    print(f"  Lowest: {min(rectangularities):.4f}")
    print(f"  Mean: {sum(rectangularities) / len(rectangularities):.4f}")

    print(f"\nRotation degrees range:")
    print(f"  Minimum: {min(rotations):.2f}°")
    print(f"  Maximum: {max(rotations):.2f}°")
    print(f"  Mean: {sum(rotations) / len(rotations):.2f}°")
    sorted_r = sorted(rotations)
    median_idx = len(sorted_r) // 2
    median = (
        sorted_r[median_idx]
        if len(sorted_r) % 2 == 1
        else (sorted_r[median_idx - 1] + sorted_r[median_idx]) / 2
    )
    print(f"  Median: {median:.2f}°")

    # Display the first 20 parks ordered by rotation
    print("\n" + "=" * 80)
    print("FIRST 20 RECTANGULAR PARKS (ordered by rotation degrees)")
    print("=" * 80)

    for i, feature in enumerate(parks_ordered[:20], 1):
        props = feature["properties"]
        rectangularity = props["ra_rectangularity"]
        rotation = props.get("ra_mrr_rotation_degrees", 0)
        print(f"\n{i}. {props['name311']} ({props['borough']})")
        print(f"   Rectangularity: {rectangularity:.4f}")
        print(f"   Rotation: {rotation:.2f}°")
        print(f"   Area: {props['area_sqm']:,.0f} m²")

# Create histogram of rotation degrees
print("\n" + "=" * 80)
print("Creating histogram of rotation degrees...")

if parks_ordered:
    rotations = [f["properties"]["ra_mrr_rotation_degrees"] for f in parks_ordered]

    # Create figure and axis
    fig, ax = plt.subplots(figsize=(12, 6))

    # Create histogram
    n, bins, patches = ax.hist(rotations, bins=50, edgecolor="black", alpha=0.7)

    # Add vertical lines at key angles
    ax.axvline(x=0, color="red", linestyle="--", linewidth=1, alpha=0.5, label="0°")
    ax.axvline(x=45, color="green", linestyle="--", linewidth=1, alpha=0.5, label="45°")
    ax.axvline(x=90, color="blue", linestyle="--", linewidth=1, alpha=0.5, label="90°")

    # Labels and title
    ax.set_xlabel("Rotation Degrees (ra_mrr_rotation_degrees)", fontsize=12)
    ax.set_ylabel("Number of Parks", fontsize=12)
    ax.set_title(
        "Distribution of Rotation Degrees for Rectangular Parks (>0.9 rectangularity)",
        fontsize=14,
        fontweight="bold",
    )
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Save the plot
    histogram_file = "analysis/output/rotation_histogram.png"
    plt.tight_layout()
    plt.savefig(histogram_file, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"Saved histogram to: {histogram_file}")

    # Also create a scatter plot of rectangularity vs rotation
    fig, ax = plt.subplots(figsize=(12, 6))

    rectangularities = [f["properties"]["ra_rectangularity"] for f in parks_ordered]

    ax.scatter(rotations, rectangularities, alpha=0.5, s=20)

    ax.set_xlabel("Rotation Degrees (ra_mrr_rotation_degrees)", fontsize=12)
    ax.set_ylabel("Rectangularity (ra_rectangularity)", fontsize=12)
    ax.set_title(
        "Rectangularity vs. Rotation Degrees for Rectangular Parks (>0.9)",
        fontsize=14,
        fontweight="bold",
    )
    ax.grid(True, alpha=0.3)
    ax.axhline(
        y=0.9,
        color="red",
        linestyle="--",
        linewidth=1,
        alpha=0.5,
        label="0.9 threshold",
    )
    ax.legend()

    # Save the scatter plot
    scatter_file = "analysis/output/rectangularity_vs_rotation.png"
    plt.tight_layout()
    plt.savefig(scatter_file, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"Saved scatter plot to: {scatter_file}")

# Save ordered results to GeoJSON with one feature per line
print("\n" + "=" * 80)
print("Saving ordered results...")

output_file = "analysis/output/parks_ordered_by_rotation.geojson"

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

# Export simplified list with key stats
print("\n" + "=" * 80)
print("Exporting rectangular parks summary...")

summary_list = []
for feature in parks_ordered:
    props = feature["properties"]
    summary_list.append(
        {
            "name311": props.get("name311", ""),
            "borough": props.get("borough", ""),
            "ra_rectangularity": props["ra_rectangularity"],
            "ra_mrr_rotation_degrees": props.get("ra_mrr_rotation_degrees", 0),
            "area_sqm": props.get("area_sqm", 0),
            "ra_mrr_width": props.get("ra_mrr_width", 0),
            "ra_mrr_height": props.get("ra_mrr_height", 0),
        }
    )

summary_output_file = "analysis/output/rectangular_parks_summary.json"

# Write with one entry per line
with open(summary_output_file, "w") as f:
    f.write("[\n")
    for i, entry in enumerate(summary_list):
        entry_json = json.dumps(entry)
        if i < len(summary_list) - 1:
            f.write(f"  {entry_json},\n")
        else:
            f.write(f"  {entry_json}\n")
    f.write("]\n")

print(f"Saved to: {summary_output_file}")
print(f"Total entries saved: {len(summary_list)}")

# Export parks with high rectangularity (> 0.9) as GeoJSON
print("\n" + "=" * 80)
print("Exporting parks with high rectangularity (> 0.9)...")

if rectangular_parks:
    # Save as GeoJSON
    high_rectangularity_output = "analysis/output/parks_high_rectangularity.geojson"

    output_data = {"type": "FeatureCollection", "features": rectangular_parks}

    # Write with one feature per line
    with open(high_rectangularity_output, "w") as f:
        # Write header
        f.write("{\n")
        f.write(f'"type": "{output_data["type"]}",\n')

        # Write features array opening
        f.write('"features": [\n')

        # Write each feature on its own line
        for i, feature in enumerate(rectangular_parks):
            feature_json = json.dumps(feature)
            if i < len(rectangular_parks) - 1:
                f.write(f"{feature_json},\n")
            else:
                f.write(f"{feature_json}\n")

        # Close features array and main object
        f.write("]\n")
        f.write("}\n")

    print(f"Saved to: {high_rectangularity_output}")

    # Display top 5 from this subset
    print(f"\nTop 5 most rectangular parks:")
    # Sort by rectangularity for display
    top_rectangular = sorted(
        rectangular_parks,
        key=lambda f: f["properties"]["ra_rectangularity"],
        reverse=True,
    )[:5]
    for feature in top_rectangular:
        props = feature["properties"]
        print(
            f"  {props['name311']} ({props['borough']}): {props['ra_rectangularity']:.4f}"
        )

print("\nDone!")
