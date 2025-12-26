#!/usr/bin/env bun
/**
 * Seed script to import parks from triangle_labels.db into Postgres.
 * Only imports parks labeled "Most Likely a Triangle" or "Somewhat a Triangle".
 *
 * Usage: bun run scripts/seed-from-sqlite.ts
 */

import { Database } from "bun:sqlite";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import * as schema from "../src/server/db/schema";

// Load environment variables
const DATABASE_URL = process.env.DATABASE_URL;
if (!DATABASE_URL) {
  console.error("❌ DATABASE_URL environment variable is required");
  process.exit(1);
}

// Assert DATABASE_URL is defined for TypeScript
const dbUrl: string = DATABASE_URL;

// Path to SQLite database
const SQLITE_PATH = new URL("../triangle_labels.db", import.meta.url).pathname;

// GeoJSON geometry type
interface GeoJSONGeometry {
  type: string;
  coordinates: number[] | number[][] | number[][][] | number[][][][];
}

// SQLite row type
interface ParkRow {
  source_id: string;
  signname: string | null;
  name311: string | null;
  borough: string | null;
  typecategory: string | null;
  acres: string | null;
  geometry: string;
  main_triangle_label: string;
}

/**
 * Calculate centroid of a GeoJSON geometry.
 * Handles Polygon and MultiPolygon types.
 */
function calculateCentroid(geometry: GeoJSONGeometry): [number, number] {
  const coords: number[][] = [];

  function extractCoords(arr: unknown): void {
    if (Array.isArray(arr)) {
      if (typeof arr[0] === "number" && typeof arr[1] === "number") {
        coords.push([arr[0] as number, arr[1] as number]);
      } else {
        for (const item of arr) {
          extractCoords(item);
        }
      }
    }
  }

  extractCoords(geometry.coordinates);

  if (coords.length === 0) {
    return [0, 0];
  }

  let sumLng = 0;
  let sumLat = 0;
  for (const [lng, lat] of coords) {
    sumLng += lng!;
    sumLat += lat!;
  }

  return [sumLng / coords.length, sumLat / coords.length];
}

async function main() {
  console.log("🔷 Triangle Crowd Labeling - Database Seeder");
  console.log("━".repeat(50));

  // Open SQLite database
  console.log(`\n📂 Opening SQLite database: ${SQLITE_PATH}`);
  const sqlite = new Database(SQLITE_PATH, { readonly: true });

  // Count total and filtered parks
  const totalCount = sqlite
    .query<{ count: number }, []>("SELECT COUNT(*) as count FROM parks")
    .get()?.count ?? 0;

  const filteredCount = sqlite
    .query<{ count: number }, []>(
      `SELECT COUNT(*) as count FROM parks 
       WHERE main_triangle_label IN ('Most Likely a Triangle', 'Somewhat a Triangle')`,
    )
    .get()?.count ?? 0;

  console.log(`   Total parks in SQLite: ${totalCount}`);
  console.log(`   Parks to import (ambiguous): ${filteredCount}`);

  // Fetch filtered parks
  const parks = sqlite
    .query<ParkRow, []>(
      `SELECT source_id, signname, name311, borough, typecategory, acres, 
              geometry, main_triangle_label
       FROM parks 
       WHERE main_triangle_label IN ('Most Likely a Triangle', 'Somewhat a Triangle')
       ORDER BY id`,
    )
    .all();

  sqlite.close();

  // Connect to Postgres
  console.log("\n🐘 Connecting to Postgres...");
  const client = postgres(dbUrl);
  const db = drizzle(client, { schema });

  // Clear existing parks (for re-seeding)
  console.log("   Clearing existing data...");
  await db.delete(schema.votes);
  await db.delete(schema.parks);

  // Insert parks in batches
  console.log(`\n📥 Inserting ${parks.length} parks...`);
  const batchSize = 100;
  let inserted = 0;

  for (let i = 0; i < parks.length; i += batchSize) {
    const batch = parks.slice(i, i + batchSize);
    const values = batch.map((park: ParkRow) => {
      const geometry = JSON.parse(park.geometry) as GeoJSONGeometry;
      const [lng, lat] = calculateCentroid(geometry);

      return {
        sourceId: park.source_id,
        signname: park.signname,
        name311: park.name311,
        borough: park.borough,
        typecategory: park.typecategory,
        acres: park.acres,
        geometry: geometry,
        centroidLng: lng,
        centroidLat: lat,
        originalLabel: park.main_triangle_label,
      };
    });

    await db.insert(schema.parks).values(values);
    inserted += batch.length;
    process.stdout.write(`\r   Progress: ${inserted}/${parks.length}`);
  }

  console.log("\n");

  // Verify
  const result = await db.select().from(schema.parks);
  console.log(`✅ Successfully seeded ${result.length} parks to Postgres`);

  // Show breakdown by label
  const mostLikely = result.filter(
    (p) => p.originalLabel === "Most Likely a Triangle",
  ).length;
  const somewhat = result.filter(
    (p) => p.originalLabel === "Somewhat a Triangle",
  ).length;
  console.log(`   - Most Likely a Triangle: ${mostLikely}`);
  console.log(`   - Somewhat a Triangle: ${somewhat}`);

  await client.end();
  console.log("\n🎉 Seeding complete!");
}

main().catch((err) => {
  console.error("❌ Seeding failed:", err);
  process.exit(1);
});

