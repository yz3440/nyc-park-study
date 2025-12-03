#!/usr/bin/env python3
"""
Apply Modifications - Merge modified park geometries into the main dataset.

This script takes the original Parks Properties GeoJSON and replaces
specific parks with their corrected geometries from modification files.
"""

from pathlib import Path

import geopandas as gpd
from rich.console import Console
from rich.table import Table

console = Console()

# File paths
SOURCE_DIR = Path(__file__).parent
ORIGINAL_FILE = SOURCE_DIR / "Parks_Properties_20251119.geojson"
OUTPUT_FILE = SOURCE_DIR / "Parks_Properties_20251119_modified.geojson"

# Modification files to apply (in order)
MODIFICATION_FILES = [
    SOURCE_DIR / "meredith_woods_modified.geojson",
    SOURCE_DIR / "small_parks_modified.geojson",
]


def main():
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════[/bold cyan]"
    )
    console.print(
        "[bold cyan]      Apply Modifications to Parks Properties          [/bold cyan]"
    )
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════[/bold cyan]\n"
    )

    # Load original data
    console.print(f"[cyan]Loading original data:[/cyan] {ORIGINAL_FILE.name}")
    gdf = gpd.read_file(ORIGINAL_FILE)
    console.print(f"[green]Loaded {len(gdf)} parks[/green]\n")

    # Track modifications
    modifications = []

    # Apply each modification file
    for mod_file in MODIFICATION_FILES:
        if not mod_file.exists():
            console.print(
                f"[yellow]Warning: Modification file not found:[/yellow] {mod_file.name}"
            )
            continue

        console.print(f"[cyan]Applying modifications from:[/cyan] {mod_file.name}")
        mod_gdf = gpd.read_file(mod_file)
        console.print(f"  Found {len(mod_gdf)} modified parks")

        # Replace each modified park in the main dataset
        for _, mod_row in mod_gdf.iterrows():
            park_id = mod_row[":id"]
            park_name = mod_row.get("name311", mod_row.get("signname", "Unknown"))

            # Find the park in the main dataset
            mask = gdf[":id"] == park_id
            match_count = mask.sum()

            if match_count == 0:
                console.print(
                    f"  [yellow]Warning: Park not found in original:[/yellow] {park_id}"
                )
                modifications.append(
                    {
                        "file": mod_file.name,
                        "park_id": park_id,
                        "park_name": park_name,
                        "status": "Not found",
                    }
                )
                continue

            if match_count > 1:
                console.print(
                    f"  [yellow]Warning: Multiple matches for:[/yellow] {park_id}"
                )

            # Replace the geometry (and optionally other fields)
            idx = gdf[mask].index[0]
            gdf.at[idx, "geometry"] = mod_row.geometry

            modifications.append(
                {
                    "file": mod_file.name,
                    "park_id": park_id,
                    "park_name": park_name,
                    "status": "Replaced",
                }
            )

        console.print(f"  [green]Applied {len(mod_gdf)} modifications[/green]\n")

    # Print summary table
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════[/bold cyan]"
    )
    console.print(
        "[bold cyan]                  Modification Summary                  [/bold cyan]"
    )
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════[/bold cyan]\n"
    )

    table = Table(title="Applied Modifications")
    table.add_column("Source File", style="dim", max_width=30)
    table.add_column("Park Name", style="cyan", max_width=35)
    table.add_column("Status", style="bold")

    for mod in modifications:
        status_style = (
            "[green]✓ Replaced[/green]"
            if mod["status"] == "Replaced"
            else "[red]✗ Not found[/red]"
        )
        table.add_row(
            mod["file"][:30],
            mod["park_name"][:35],
            status_style,
        )

    console.print(table)

    # Summary counts
    replaced = sum(1 for m in modifications if m["status"] == "Replaced")
    not_found = sum(1 for m in modifications if m["status"] == "Not found")
    console.print(f"\n[bold]Summary:[/bold] {replaced} replaced, {not_found} not found")

    # Save output
    console.print(f"\n[cyan]Saving modified dataset to:[/cyan] {OUTPUT_FILE.name}")
    gdf.to_file(OUTPUT_FILE, driver="GeoJSON")
    console.print(f"[bold green]Done! Saved {len(gdf)} parks.[/bold green]")


if __name__ == "__main__":
    main()
