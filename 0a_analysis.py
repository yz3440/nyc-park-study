"""
NYC Parks Basic Statistics
Analyze basic statistics and distributions of the original parks dataset
"""

import geopandas as gpd
import pandas as pd
from rich.console import Console
from rich.table import Table

SOURCE_DATA_FILE = "./source_data/Parks_Properties_20251021_modified.geojson"

DIVIDER_STR = "[bold yellow]═" * 40 + "[/bold yellow]"

console = Console()

console.print("[bold cyan]Loading NYC Parks GeoJSON...[/bold cyan]")
gdf = gpd.read_file(SOURCE_DATA_FILE)

console.print("\n" + DIVIDER_STR)
console.print("[bold yellow]BASIC DATASET INFORMATION[/bold yellow]")
console.print(DIVIDER_STR + "\n")

console.print(f"\n[bold]Total number of parks:[/bold] {len(gdf)}")
console.print(f"[bold]Columns:[/bold] {list(gdf.columns)}")

console.print("\n" + DIVIDER_STR)
console.print("[bold yellow]TYPECATEGORY DISTRIBUTION[/bold yellow]")
console.print(DIVIDER_STR + "\n")

if "typecategory" in gdf.columns:
    typecategory_counts = gdf["typecategory"].value_counts()

    table = Table(title="Park Types", show_header=True, header_style="bold magenta")
    table.add_column("Type Category", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right", style="green")

    for type_cat, count in typecategory_counts.items():
        table.add_row(str(type_cat), str(count))

    console.print(table)
    console.print(
        f"\n[bold]Total unique typecategories:[/bold] {gdf['typecategory'].nunique()}"
    )
    console.print(
        f"[bold]Missing typecategory values:[/bold] {gdf['typecategory'].isna().sum()}"
    )

console.print("\n" + DIVIDER_STR)
console.print("[bold yellow]SUBCATEGORY DISTRIBUTION[/bold yellow]")
console.print(DIVIDER_STR + "\n")

if "subcategory" in gdf.columns:
    subcategory_counts = gdf["subcategory"].value_counts().head(20)

    table = Table(
        title="Park Subcategories (Top 20)",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Subcategory", style="cyan")
    table.add_column("Count", justify="right", style="green")

    for subcat, count in subcategory_counts.items():
        table.add_row(str(subcat), str(count))

    console.print(table)
    console.print(
        f"\n[bold]Total unique subcategories:[/bold] {gdf['subcategory'].nunique()}"
    )
    console.print(
        f"[bold]Missing subcategory values:[/bold] {gdf['subcategory'].isna().sum()}"
    )

console.print("\n" + DIVIDER_STR)
console.print("[bold yellow]BOROUGH DISTRIBUTION[/bold yellow]")
console.print(DIVIDER_STR + "\n")

if "borough" in gdf.columns:
    borough_counts = gdf["borough"].value_counts()

    if "acres" in gdf.columns:
        gdf["acres_numeric"] = pd.to_numeric(gdf["acres"], errors="coerce")
        borough_acres = (
            gdf.groupby("borough")["acres_numeric"].sum().sort_values(ascending=False)
        )

        table = Table(
            title="Parks by Borough", show_header=True, header_style="bold magenta"
        )
        table.add_column("Borough", style="cyan")
        table.add_column("Park Count", justify="right", style="green")
        table.add_column("Total Acres", justify="right", style="yellow")

        for borough in borough_acres.index:
            count = borough_counts.get(borough, 0)
            acres = borough_acres.get(borough, 0)
            table.add_row(str(borough), str(count), f"{acres:,.2f}")

        console.print(table)
    else:
        table = Table(
            title="Parks by Borough", show_header=True, header_style="bold magenta"
        )
        table.add_column("Borough", style="cyan")
        table.add_column("Count", justify="right", style="green")

        for borough, count in borough_counts.items():
            table.add_row(str(borough), str(count))

        console.print(table)

console.print("\n" + DIVIDER_STR)
console.print("[bold yellow]GEOMETRY TYPE DISTRIBUTION[/bold yellow]")
console.print(DIVIDER_STR + "\n")

geom_counts = gdf.geometry.geom_type.value_counts()

table = Table(title="Geometry Types", show_header=True, header_style="bold magenta")
table.add_column("Geometry Type", style="cyan")
table.add_column("Count", justify="right", style="green")

for geom_type, count in geom_counts.items():
    table.add_row(str(geom_type), str(count))

console.print(table)
