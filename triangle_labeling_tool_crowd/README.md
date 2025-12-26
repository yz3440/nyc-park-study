# Tinder for Triangles

A crowd-sourced voting app to classify NYC park shapes. Users swipe right if a park is a triangle, left if not.

## Stack

- **Framework**: Next.js 15 (App Router) via T3 Stack
- **Runtime**: Bun
- **Database**: Postgres 17 via Drizzle ORM
- **Maps**: Mapbox GL JS (satellite tiles)
- **UI**: Tailwind CSS + Framer Motion
- **API**: tRPC

## Setup

### 1. Environment Variables

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Required variables:

```env
DATABASE_URL="postgresql://user:password@host:5432/database"
NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN="pk.your_mapbox_token_here"
```

### 2. Install Dependencies

```bash
bun install
```

### 3. Push Database Schema

```bash
bun run db:push
```

### 4. Seed the Database

This imports parks from the SQLite database (`triangle_labels.db`). Only parks labeled "Most Likely a Triangle" or "Somewhat a Triangle" are imported.

```bash
bun run db:seed
```

### 5. Start Development Server

```bash
bun run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Usage

### Voting Flow

1. Users see a satellite map centered on a park with its boundary highlighted
2. **Swipe Right** (or tap ✓) = This IS a triangle
3. **Swipe Left** (or tap ✗) = This is NOT a triangle
4. No skip option - users must decide

### Session Management

- Anonymous sessions are tracked via `localStorage`
- Each user gets a unique `session_id`
- Seen parks are stored locally to prevent repeat voting

## Database Schema

### Parks Table

| Column         | Type   | Description                                |
| -------------- | ------ | ------------------------------------------ |
| id             | serial | Primary key                                |
| source_id      | text   | Original park ID from source data          |
| signname       | text   | Park sign name                             |
| name311        | text   | 311 system name                            |
| borough        | text   | NYC borough                                |
| typecategory   | text   | Park type category                         |
| acres          | text   | Park size in acres                         |
| geometry       | jsonb  | GeoJSON geometry                           |
| centroid_lng   | float  | Centroid longitude                         |
| centroid_lat   | float  | Centroid latitude                          |
| original_label | text   | Original label from triangle_labels.db    |
| created_at     | timestamp | Record creation time                    |

### Votes Table

| Column       | Type      | Description                    |
| ------------ | --------- | ------------------------------ |
| id           | uuid      | Primary key                    |
| park_id      | integer   | Foreign key to parks           |
| user_session | text      | Anonymous session ID           |
| vote         | boolean   | true=triangle, false=not       |
| created_at   | timestamp | Vote submission time           |

## API Endpoints (tRPC)

| Procedure              | Type     | Description                         |
| ---------------------- | -------- | ----------------------------------- |
| `park.getNextBatch`    | Query    | Fetch parks for voting              |
| `park.getById`         | Query    | Get single park by ID               |
| `park.submitVote`      | Mutation | Submit a binary vote                |
| `park.getStats`        | Query    | Get voting statistics               |
| `park.getRemainingCount` | Query  | Count remaining unvoted parks       |

## Deployment (Vercel)

1. Connect your repository to Vercel
2. Set environment variables in Vercel dashboard:
   - `DATABASE_URL`
   - `NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN`
3. Deploy

## Export Votes

Use Drizzle Studio to view/export data:

```bash
bun run db:studio
```

Or connect directly to your Postgres database and run:

```sql
SELECT 
  v.id,
  p.source_id as park_id,
  v.user_session,
  v.vote,
  v.created_at
FROM triangle_labeling_tool_crowd_vote v
JOIN triangle_labeling_tool_crowd_park p ON v.park_id = p.id
ORDER BY v.created_at;
```

## Data Source

Parks are imported from `triangle_labels.db`, which contains NYC Parks data filtered to parks categorized as:
- "Most Likely a Triangle"
- "Somewhat a Triangle"

These are ambiguous shapes that need human consensus to classify.
