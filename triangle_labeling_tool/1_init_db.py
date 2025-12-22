#!/usr/bin/env python3
"""
Initialize the triangle labeling database from source GeoJSON.
Creates SQLite database with all park properties and geometry.
"""

import json
import sqlite3
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

console = Console()

# Paths
SOURCE_GEOJSON = (
    Path(__file__).parent.parent
    / "source_data"
    / "Parks_Properties_20251119_modified.geojson"
)
DB_PATH = Path(__file__).parent / "triangle_labels.db"


def create_database():
    """Create the SQLite database and parks table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS parks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT,
            version INTEGER,
            created_at TEXT,
            updated_at TEXT,
            acquisitiondate TEXT,
            acres TEXT,
            address TEXT,
            borough TEXT,
            class TEXT,
            communityboard TEXT,
            councildistrict TEXT,
            department TEXT,
            eapply TEXT,
            gisobjid TEXT,
            gispropnum TEXT,
            globalid TEXT,
            jurisdiction TEXT,
            location TEXT,
            mapped TEXT,
            name311 TEXT,
            nys_assembly TEXT,
            nys_senate TEXT,
            objectid TEXT,
            omppropid TEXT,
            parentid TEXT,
            permit TEXT,
            permitdistrict TEXT,
            permitparent TEXT,
            pip_ratable TEXT,
            precinct TEXT,
            retired INTEGER,
            signname TEXT,
            subcategory TEXT,
            typecategory TEXT,
            us_congress TEXT,
            waterfront INTEGER,
            zipcode TEXT,
            geometry TEXT,
            main_triangle_label TEXT,
            triangle_note TEXT,
            labeled_at TEXT
        )
    """
    )

    # Create indexes for common queries
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_main_triangle_label ON parks(main_triangle_label)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signname ON parks(signname)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gispropnum ON parks(gispropnum)")

    conn.commit()
    return conn


def load_geojson(path: Path) -> list:
    """Load GeoJSON file and return features."""
    console.print(f"[cyan]Loading GeoJSON from:[/cyan] {path}")

    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    console.print(f"[cyan]Found {len(features)} features[/cyan]")
    return features


def insert_parks(conn: sqlite3.Connection, features: list):
    """Insert park features into the database."""
    cursor = conn.cursor()

    inserted = 0
    for feature in features:
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})

        cursor.execute(
            """
            INSERT INTO parks (
                source_id, version, created_at, updated_at,
                acquisitiondate, acres, address, borough, class,
                communityboard, councildistrict, department, eapply,
                gisobjid, gispropnum, globalid, jurisdiction, location,
                mapped, name311, nys_assembly, nys_senate, objectid,
                omppropid, parentid, permit, permitdistrict, permitparent,
                pip_ratable, precinct, retired, signname, subcategory,
                typecategory, us_congress, waterfront, zipcode, geometry
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
        """,
            (
                props.get(":id"),
                props.get(":version"),
                props.get(":created_at"),
                props.get(":updated_at"),
                props.get("acquisitiondate"),
                props.get("acres"),
                props.get("address"),
                props.get("borough"),
                props.get("class"),
                props.get("communityboard"),
                props.get("councildistrict"),
                props.get("department"),
                props.get("eapply"),
                props.get("gisobjid"),
                props.get("gispropnum"),
                props.get("globalid"),
                props.get("jurisdiction"),
                props.get("location"),
                props.get("mapped"),
                props.get("name311"),
                props.get("nys_assembly"),
                props.get("nys_senate"),
                props.get("objectid"),
                props.get("omppropid"),
                props.get("parentid"),
                props.get("permit"),
                props.get("permitdistrict"),
                props.get("permitparent"),
                props.get("pip_ratable"),
                props.get("precinct"),
                1 if props.get("retired") else 0,
                props.get("signname"),
                props.get("subcategory"),
                props.get("typecategory"),
                props.get("us_congress"),
                1 if props.get("waterfront") else 0,
                props.get("zipcode"),
                json.dumps(geometry),
            ),
        )
        inserted += 1

    conn.commit()
    return inserted


def main():
    console.print("[bold cyan]╔══════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║   Triangle Labeling Tool - DB Init       ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════╝[/bold cyan]")
    console.print()

    # Check if database exists with data
    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM parks")
            count = cursor.fetchone()[0]
            conn.close()

            if count > 0:
                console.print(
                    f"[yellow]⚠ Database already exists with {count} parks.[/yellow]"
                )
                if not Confirm.ask("Do you want to overwrite it?"):
                    console.print("[dim]Aborted.[/dim]")
                    return
                # Delete existing database
                DB_PATH.unlink()
        except sqlite3.OperationalError:
            conn.close()
            # Table doesn't exist, delete and recreate
            DB_PATH.unlink()

    # Load source data
    try:
        features = load_geojson(SOURCE_GEOJSON)
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        return

    # Create database and insert data
    console.print(f"[cyan]Creating database:[/cyan] {DB_PATH}")
    conn = create_database()

    console.print("[cyan]Inserting parks...[/cyan]")
    inserted = insert_parks(conn, features)

    conn.close()

    console.print()
    console.print(
        f"[green]✓ Successfully initialized database with {inserted} parks[/green]"
    )
    console.print(f"[dim]Database saved to: {DB_PATH}[/dim]")


if __name__ == "__main__":
    main()
