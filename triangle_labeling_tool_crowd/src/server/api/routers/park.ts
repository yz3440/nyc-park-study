import { and, count, eq, notInArray, sql } from "drizzle-orm";
import { z } from "zod";

import { createTRPCRouter, publicProcedure } from "~/server/api/trpc";
import { parks, votes } from "~/server/db/schema";

export const parkRouter = createTRPCRouter({
  /**
   * Get a batch of parks for voting, excluding already-seen parks.
   * Returns parks with their geometry and centroid for map display.
   */
  getNextBatch: publicProcedure
    .input(
      z.object({
        excludeIds: z.array(z.number()).default([]),
        limit: z.number().min(1).max(50).default(10),
      }),
    )
    .query(async ({ ctx, input }) => {
      const query = ctx.db
        .select({
          id: parks.id,
          sourceId: parks.sourceId,
          signname: parks.signname,
          name311: parks.name311,
          borough: parks.borough,
          typecategory: parks.typecategory,
          acres: parks.acres,
          geometry: parks.geometry,
          centroidLng: parks.centroidLng,
          centroidLat: parks.centroidLat,
          originalLabel: parks.originalLabel,
        })
        .from(parks);

      // Build where clause
      const results =
        input.excludeIds.length > 0
          ? await query
              .where(notInArray(parks.id, input.excludeIds))
              .orderBy(sql`RANDOM()`)
              .limit(input.limit)
          : await query.orderBy(sql`RANDOM()`).limit(input.limit);

      return results;
    }),

  /**
   * Get a single park by ID.
   */
  getById: publicProcedure
    .input(z.object({ id: z.number() }))
    .query(async ({ ctx, input }) => {
      const park = await ctx.db
        .select()
        .from(parks)
        .where(eq(parks.id, input.id))
        .limit(1);

      return park[0] ?? null;
    }),

  /**
   * Submit a vote for a park.
   * vote: true = triangle, false = not triangle
   */
  submitVote: publicProcedure
    .input(
      z.object({
        parkId: z.number(),
        userSession: z.string().min(1),
        vote: z.boolean(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const result = await ctx.db
        .insert(votes)
        .values({
          parkId: input.parkId,
          userSession: input.userSession,
          vote: input.vote,
        })
        .returning({ id: votes.id });

      return { success: true, voteId: result[0]?.id };
    }),

  /**
   * Get voting statistics for the current session and overall.
   */
  getStats: publicProcedure
    .input(
      z.object({
        userSession: z.string().optional(),
      }),
    )
    .query(async ({ ctx, input }) => {
      // Total parks
      const totalParks = await ctx.db
        .select({ count: count() })
        .from(parks);

      // Total votes
      const totalVotes = await ctx.db
        .select({ count: count() })
        .from(votes);

      // Votes by this session
      let sessionVotes = 0;
      if (input.userSession) {
        const sessionResult = await ctx.db
          .select({ count: count() })
          .from(votes)
          .where(eq(votes.userSession, input.userSession));
        sessionVotes = sessionResult[0]?.count ?? 0;
      }

      // Vote breakdown (triangles vs not)
      const triangleVotes = await ctx.db
        .select({ count: count() })
        .from(votes)
        .where(eq(votes.vote, true));

      const notTriangleVotes = await ctx.db
        .select({ count: count() })
        .from(votes)
        .where(eq(votes.vote, false));

      return {
        totalParks: totalParks[0]?.count ?? 0,
        totalVotes: totalVotes[0]?.count ?? 0,
        sessionVotes,
        triangleVotes: triangleVotes[0]?.count ?? 0,
        notTriangleVotes: notTriangleVotes[0]?.count ?? 0,
      };
    }),

  /**
   * Get remaining parks count (not yet voted by this session).
   */
  getRemainingCount: publicProcedure
    .input(
      z.object({
        votedParkIds: z.array(z.number()).default([]),
      }),
    )
    .query(async ({ ctx, input }) => {
      const query = ctx.db.select({ count: count() }).from(parks);

      const result =
        input.votedParkIds.length > 0
          ? await query.where(notInArray(parks.id, input.votedParkIds))
          : await query;

      return { remaining: result[0]?.count ?? 0 };
    }),

  /**
   * Undo/delete a vote for a specific park by user session.
   * Returns the deleted vote info if found.
   */
  undoVote: publicProcedure
    .input(
      z.object({
        parkId: z.number(),
        userSession: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      const deleted = await ctx.db
        .delete(votes)
        .where(
          and(
            eq(votes.parkId, input.parkId),
            eq(votes.userSession, input.userSession)
          )
        )
        .returning({ id: votes.id, vote: votes.vote });

      if (deleted.length === 0) {
        return { success: false, message: "Vote not found" };
      }

      return { success: true, deletedVote: deleted[0] };
    }),
});


