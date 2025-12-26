import {
  boolean,
  doublePrecision,
  index,
  integer,
  jsonb,
  pgTableCreator,
  serial,
  text,
  timestamp,
  uuid,
} from "drizzle-orm/pg-core";

/**
 * Multi-project schema prefix for Drizzle ORM.
 * @see https://orm.drizzle.team/docs/goodies#multi-project-schema
 */
export const createTable = pgTableCreator(
  (name) => `triangle_labeling_tool_crowd_${name}`,
);

/**
 * Parks table - seeded from triangle_labels.db
 * Contains only parks labeled "Most Likely a Triangle" or "Somewhat a Triangle"
 */
export const parks = createTable(
  "park",
  (d) => ({
    id: serial("id").primaryKey(),
    sourceId: text("source_id").notNull(),
    signname: text("signname"),
    name311: text("name311"),
    borough: text("borough"),
    typecategory: text("typecategory"),
    acres: text("acres"),
    geometry: jsonb("geometry").notNull(),
    centroidLng: doublePrecision("centroid_lng").notNull(),
    centroidLat: doublePrecision("centroid_lat").notNull(),
    originalLabel: text("original_label"), // "Most Likely a Triangle" or "Somewhat a Triangle"
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  }),
  (t) => [
    index("source_id_idx").on(t.sourceId),
    index("original_label_idx").on(t.originalLabel),
  ],
);

/**
 * Votes table - binary decisions from crowd
 * Each vote records whether a user thinks a park is a triangle or not
 */
export const votes = createTable(
  "vote",
  (d) => ({
    id: uuid("id").defaultRandom().primaryKey(),
    parkId: integer("park_id")
      .references(() => parks.id)
      .notNull(),
    userSession: text("user_session").notNull(),
    vote: boolean("vote").notNull(), // true = triangle, false = not triangle
    createdAt: timestamp("created_at", { withTimezone: true })
      .defaultNow()
      .notNull(),
  }),
  (t) => [
    index("park_id_idx").on(t.parkId),
    index("user_session_idx").on(t.userSession),
  ],
);

// Type exports for use in tRPC routers
export type Park = typeof parks.$inferSelect;
export type NewPark = typeof parks.$inferInsert;
export type Vote = typeof votes.$inferSelect;
export type NewVote = typeof votes.$inferInsert;
