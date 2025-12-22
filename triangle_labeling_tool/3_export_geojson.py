#!/usr/bin/env python3
"""
Export labeled parks data back to GeoJSON format.
Adds main_triangle_label and triangle_note fields to the original properties.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from rich.console import Console

console = Console()

# Paths
DB_PATH = Path(__file__).parent / "triangle_labels.db"
OUTPUT_DIR = Path(__file__).parent.parent / "output_data"


def get_db():
    """Get database connection."""
    if not DB_PATH.exists():
        console.print("[red]✗ Database not found. Run 1_init_db.py first.[/red]")
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def export_geojson(output_path: Path, only_labeled: bool = False) -> int:
    """Export parks to GeoJSON with label fields."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Build query
    where_clause = "WHERE main_triangle_label IS NOT NULL" if only_labeled else ""
    
    cursor.execute(f"""
        SELECT 
            source_id, version, created_at, updated_at,
            acquisitiondate, acres, address, borough, class,
            communityboard, councildistrict, department, eapply,
            gisobjid, gispropnum, globalid, jurisdiction, location,
            mapped, name311, nys_assembly, nys_senate, objectid,
            omppropid, parentid, permit, permitdistrict, permitparent,
            pip_ratable, precinct, retired, signname, subcategory,
            typecategory, us_congress, waterfront, zipcode, geometry,
            main_triangle_label, triangle_note
        FROM parks
        {where_clause}
        ORDER BY id
    """)
    
    features = []
    for row in cursor.fetchall():
        # Build properties dict
        properties = {
            ":id": row["source_id"],
            ":version": row["version"],
            ":created_at": row["created_at"],
            ":updated_at": row["updated_at"],
            "acquisitiondate": row["acquisitiondate"],
            "acres": row["acres"],
            "address": row["address"],
            "borough": row["borough"],
            "class": row["class"],
            "communityboard": row["communityboard"],
            "councildistrict": row["councildistrict"],
            "department": row["department"],
            "eapply": row["eapply"],
            "gisobjid": row["gisobjid"],
            "gispropnum": row["gispropnum"],
            "globalid": row["globalid"],
            "jurisdiction": row["jurisdiction"],
            "location": row["location"],
            "mapped": row["mapped"],
            "name311": row["name311"],
            "nys_assembly": row["nys_assembly"],
            "nys_senate": row["nys_senate"],
            "objectid": row["objectid"],
            "omppropid": row["omppropid"],
            "parentid": row["parentid"],
            "permit": row["permit"],
            "permitdistrict": row["permitdistrict"],
            "permitparent": row["permitparent"],
            "pip_ratable": row["pip_ratable"],
            "precinct": row["precinct"],
            "retired": bool(row["retired"]),
            "signname": row["signname"],
            "subcategory": row["subcategory"],
            "typecategory": row["typecategory"],
            "us_congress": row["us_congress"],
            "waterfront": bool(row["waterfront"]),
            "zipcode": row["zipcode"],
            # New label fields
            "main_triangle_label": row["main_triangle_label"],
            "triangle_note": row["triangle_note"]
        }
        
        feature = {
            "type": "Feature",
            "properties": properties,
            "geometry": json.loads(row["geometry"])
        }
        features.append(feature)
    
    conn.close()
    
    # Create GeoJSON structure
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    # Write to file
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f)
    
    return len(features)


def main():
    console.print("[bold cyan]╔══════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║   Triangle Labeling Tool - Export        ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════╝[/bold cyan]")
    console.print()
    
    # Get stats first
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM parks")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM parks WHERE main_triangle_label IS NOT NULL")
    labeled = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT main_triangle_label, COUNT(*) as count
        FROM parks
        WHERE main_triangle_label IS NOT NULL
        GROUP BY main_triangle_label
    """)
    label_counts = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    
    console.print(f"[cyan]Total parks:[/cyan] {total}")
    console.print(f"[cyan]Labeled parks:[/cyan] {labeled}")
    for label, count in label_counts.items():
        console.print(f"  [dim]{label}:[/dim] {count}")
    console.print()
    
    # Export all parks with labels
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Export all parks (includes label fields, NULL if not labeled)
    all_output = OUTPUT_DIR / "parks_with_triangle_labels.geojson"
    count = export_geojson(all_output, only_labeled=False)
    console.print(f"[green]✓[/green] Exported all {count} parks to:")
    console.print(f"  [dim]{all_output}[/dim]")
    
    # Export only labeled parks
    if labeled > 0:
        labeled_output = OUTPUT_DIR / "parks_labeled_triangles_only.geojson"
        count = export_geojson(labeled_output, only_labeled=True)
        console.print(f"[green]✓[/green] Exported {count} labeled parks to:")
        console.print(f"  [dim]{labeled_output}[/dim]")
    
    console.print("\n[green]✓ Export complete![/green]")


if __name__ == "__main__":
    main()



