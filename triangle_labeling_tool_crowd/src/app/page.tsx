'use client';

import { useCallback, useEffect, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';

import { MapView } from '~/app/_components/MapView';
import { VoteControls } from '~/app/_components/VoteControls';
import { api } from '~/trpc/react';

// GeoJSON geometry type
interface GeoJSONGeometry {
  type: string;
  coordinates: number[] | number[][] | number[][][] | number[][][][];
}

interface Park {
  id: number;
  sourceId: string;
  signname: string | null;
  name311: string | null;
  borough: string | null;
  typecategory: string | null;
  acres: string | null;
  geometry: GeoJSONGeometry;
  centroidLng: number;
  centroidLat: number;
  originalLabel: string | null;
}

const SESSION_KEY = 'triangle_session_id';
const SEEN_PARKS_KEY = 'triangle_seen_parks';

function getSessionId(): string {
  if (typeof window === 'undefined') return '';
  let sessionId = localStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = uuidv4();
    localStorage.setItem(SESSION_KEY, sessionId);
  }
  return sessionId;
}

function getSeenParkIds(): number[] {
  if (typeof window === 'undefined') return [];
  try {
    const stored = localStorage.getItem(SEEN_PARKS_KEY);
    return stored ? (JSON.parse(stored) as number[]) : [];
  } catch {
    return [];
  }
}

function addSeenParkId(parkId: number): void {
  if (typeof window === 'undefined') return;
  const seen = getSeenParkIds();
  if (!seen.includes(parkId)) {
    seen.push(parkId);
    localStorage.setItem(SEEN_PARKS_KEY, JSON.stringify(seen));
  }
}

function removeSeenParkId(parkId: number): void {
  if (typeof window === 'undefined') return;
  const seen = getSeenParkIds();
  const filtered = seen.filter((id) => id !== parkId);
  localStorage.setItem(SEEN_PARKS_KEY, JSON.stringify(filtered));
}

// Type for undo state
interface UndoState {
  park: Park;
  vote: boolean;
}

export default function Home() {
  const [sessionId, setSessionId] = useState<string>('');
  const [seenParkIds, setSeenParkIds] = useState<number[]>([]);
  const [currentPark, setCurrentPark] = useState<Park | null>(null);
  const [parkQueue, setParkQueue] = useState<Park[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isComplete, setIsComplete] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const [undoState, setUndoState] = useState<UndoState | null>(null);

  // Initialize session
  useEffect(() => {
    setSessionId(getSessionId());
    setSeenParkIds(getSeenParkIds());
  }, []);

  // tRPC mutations and queries
  const submitVoteMutation = api.park.submitVote.useMutation();
  const undoVoteMutation = api.park.undoVote.useMutation();

  const { data: statsData } = api.park.getStats.useQuery(
    { userSession: sessionId },
    { enabled: !!sessionId, refetchInterval: 5000 }
  );

  const { data: remainingData, refetch: refetchRemaining } =
    api.park.getRemainingCount.useQuery(
      { votedParkIds: seenParkIds },
      { enabled: seenParkIds.length >= 0 }
    );

  // Fetch batch of parks
  const {
    data: batchData,
    refetch: refetchBatch,
    isFetching: isFetchingBatch,
  } = api.park.getNextBatch.useQuery(
    { excludeIds: seenParkIds, limit: 10 },
    { enabled: seenParkIds.length >= 0 }
  );

  // Manage park queue from batch data
  useEffect(() => {
    if (batchData && batchData.length > 0) {
      const unseenParks = batchData.filter(
        (p) => !seenParkIds.includes(p.id)
      ) as Park[];

      if (unseenParks.length > 0) {
        if (!currentPark) {
          setCurrentPark(unseenParks[0]!);
          setParkQueue(unseenParks.slice(1));
        } else {
          setParkQueue((prev) => {
            const existingIds = new Set([
              currentPark.id,
              ...prev.map((p) => p.id),
            ]);
            const newParks = unseenParks.filter((p) => !existingIds.has(p.id));
            return [...prev, ...newParks];
          });
        }
        setIsLoading(false);
      } else if (!isFetchingBatch && !currentPark) {
        setIsComplete(true);
        setIsLoading(false);
      }
    } else if (batchData && batchData.length === 0 && !isFetchingBatch) {
      if (!currentPark && parkQueue.length === 0) {
        setIsComplete(true);
      }
      setIsLoading(false);
    }
  }, [batchData, currentPark, seenParkIds, isFetchingBatch, parkQueue.length]);

  // Handle vote
  const handleVote = useCallback(
    (isTriangle: boolean) => {
      if (!currentPark || !sessionId) return;

      const votedPark = currentPark;

      // Save undo state before transitioning
      setUndoState({ park: votedPark, vote: isTriangle });

      // Update seen parks immediately
      addSeenParkId(votedPark.id);
      setSeenParkIds((prev) => [...prev, votedPark.id]);

      // Move to next park from queue
      if (parkQueue.length > 0) {
        const [nextPark, ...remainingQueue] = parkQueue;
        setCurrentPark(nextPark!);
        setParkQueue(remainingQueue);
      } else {
        setCurrentPark(null);
        setIsLoading(true);
      }

      // Submit vote in background
      submitVoteMutation.mutate({
        parkId: votedPark.id,
        userSession: sessionId,
        vote: isTriangle,
      });

      // Prefetch more parks when queue is low
      if (parkQueue.length < 5) {
        void refetchBatch();
      }
      void refetchRemaining();
    },
    [
      currentPark,
      parkQueue,
      sessionId,
      submitVoteMutation,
      refetchBatch,
      refetchRemaining,
    ]
  );

  // Handle undo
  const handleUndo = useCallback(() => {
    if (!undoState || !sessionId) return;

    const { park: undoPark } = undoState;

    // Remove from seen parks
    removeSeenParkId(undoPark.id);
    setSeenParkIds((prev) => prev.filter((id) => id !== undoPark.id));

    // Put current park back in queue and restore undo park as current
    if (currentPark) {
      setParkQueue((prev) => [currentPark, ...prev]);
    }
    setCurrentPark(undoPark);
    setIsLoading(false);
    setIsComplete(false);

    // Delete vote from database
    undoVoteMutation.mutate({
      parkId: undoPark.id,
      userSession: sessionId,
    });

    // Clear undo state (can only undo once)
    setUndoState(null);

    void refetchRemaining();
  }, [undoState, sessionId, currentPark, undoVoteMutation, refetchRemaining]);

  // Reset progress handler
  const handleReset = useCallback(() => {
    localStorage.removeItem(SEEN_PARKS_KEY);
    setSeenParkIds([]);
    setCurrentPark(null);
    setParkQueue([]);
    setIsComplete(false);
    setIsLoading(true);
    void refetchBatch();
  }, [refetchBatch]);

  const handleMapReady = useCallback(() => {
    setMapReady(true);
  }, []);

  // Complete state
  if (isComplete) {
    return (
      <main className='flex h-dvh flex-col items-center justify-center bg-black p-8 text-center'>
        <div className='space-y-6'>
          <div className='text-6xl'>🎉</div>
          <h1 className='text-2xl font-bold text-white'>All Done!</h1>
          <p className='text-white/60'>
            You&apos;ve reviewed all {seenParkIds.length} parks.
          </p>
          <p className='text-sm text-white/40'>
            Thank you for helping classify NYC park shapes!
          </p>
          <button
            onClick={handleReset}
            className='mt-4 rounded border border-white/30 px-6 py-2 text-sm text-white/80 transition-colors hover:bg-white/10'
          >
            Start Over
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className='relative h-dvh w-full overflow-hidden bg-black'>
      {/* Header stats */}
      <div className='absolute left-0 right-0 top-0 z-50 flex items-center justify-between p-4 pointer-events-none'>
        <div className='text-xs text-white/50'>
          <span className='font-bold text-white'>{seenParkIds.length}</span>
          {' reviewed'}
        </div>
        <div className='text-xs text-white/50'>
          {remainingData?.remaining ?? '...'} left
        </div>
      </div>

      {/* Single persistent map */}
      <div className='absolute inset-0'>
        <MapView park={currentPark} onMapReady={handleMapReady} />
      </div>

      {/* Loading state */}
      {(isLoading || !mapReady) && !currentPark && (
        <div className='absolute inset-0 z-30 flex items-center justify-center bg-black/80'>
          <div className='text-center'>
            <div className='mb-4 h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white' />
            <p className='text-sm text-white/50'>Loading parks...</p>
          </div>
        </div>
      )}

      {/* Vote controls overlay */}
      {currentPark && mapReady && (
        <VoteControls
          key={currentPark.id}
          park={currentPark}
          onVote={handleVote}
          canUndo={!!undoState}
          onUndo={handleUndo}
        />
      )}

      {/* Footer with global stats */}
      <div className='absolute bottom-0 left-0 right-0 z-50 flex items-center justify-center gap-6 p-3 text-xs text-white/30 pointer-events-none'>
        {statsData && (
          <>
            <span>
              <span className='text-green-500'>{statsData.triangleVotes}</span>{' '}
              triangles
            </span>
            <span>·</span>
            <span>
              <span className='text-red-500'>{statsData.notTriangleVotes}</span>{' '}
              not
            </span>
            <span>·</span>
            <span>{statsData.totalVotes} total votes</span>
          </>
        )}
      </div>

      {/* Instructions overlay - shown briefly */}
      <Instructions />
    </main>
  );
}

const INSTRUCTIONS_SEEN_KEY = 'triangle_instructions_seen';

function Instructions() {
  const [visible, setVisible] = useState(true);
  const [hasSeenBefore, setHasSeenBefore] = useState(false);

  useEffect(() => {
    const seen = localStorage.getItem(INSTRUCTIONS_SEEN_KEY);
    if (seen === 'true') {
      setHasSeenBefore(true);
    }
  }, []);

  const handleEnter = () => {
    localStorage.setItem(INSTRUCTIONS_SEEN_KEY, 'true');
    setVisible(false);
  };

  const handleSkip = () => {
    setVisible(false);
  };

  if (!visible) return null;

  // Short version for returning users
  if (hasSeenBefore) {
    return (
      <div className='absolute inset-0 z-40 flex items-center justify-center bg-black/90'>
        <div className='max-w-sm space-y-6 p-8 text-center'>
          <h1 className='text-xl font-bold tracking-tight text-white'>
            Welcome Back!
          </h1>
          <p className='text-sm text-white/70'>
            Tap <span className='text-green-500'>✓</span> for triangle,{' '}
            <span className='text-red-500'>✗</span> for not
          </p>
          <div className='flex justify-center gap-4 pt-2'>
            <button
              onClick={handleSkip}
              className='rounded-lg border border-white/30 px-6 py-3 text-sm font-medium text-white/70 transition-colors hover:bg-white/10'
            >
              Skip
            </button>
            <button
              onClick={handleEnter}
              className='rounded-lg bg-white px-6 py-3 text-sm font-medium text-black transition-colors hover:bg-white/90'
            >
              Start
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Full instructions for first-time users
  return (
    <div className='absolute inset-0 z-40 flex items-center justify-center bg-black/90 p-4'>
      <div className='flex max-h-[90vh] w-full max-w-md flex-col rounded-xl border border-white/20 bg-black/80'>
        {/* Scrollable content */}
        <div className='flex-1 overflow-y-auto p-6'>
          <div className='space-y-6'>
            <div className='text-center'>
              <div className='mb-4 text-4xl'>📐</div>
              <h1 className='text-2xl font-bold tracking-tight text-white'>
                Triangle or Not?
              </h1>
              <p className='mt-2 text-sm text-white/60'>
                Help us classify NYC park shapes
              </p>
            </div>

            <div className='space-y-4 text-sm text-white/80'>
              <div className='rounded-lg bg-white/5 p-4'>
                <h3 className='mb-2 font-semibold text-white'>What is this?</h3>
                <p>
                  NYC has hundreds of small parks created at street
                  intersections. Many of these are triangular in shape, but we
                  need human help to verify which ones actually look like
                  triangles.
                </p>
              </div>

              <div className='rounded-lg bg-white/5 p-4'>
                <h3 className='mb-2 font-semibold text-white'>How to vote</h3>
                <ul className='space-y-2'>
                  <li className='flex items-center gap-3'>
                    <span className='flex h-8 w-8 items-center justify-center rounded-full border-2 border-green-500 text-green-500'>
                      ✓
                    </span>
                    <span>
                      Tap if the highlighted shape looks like a{' '}
                      <strong>triangle</strong>
                    </span>
                  </li>
                  <li className='flex items-center gap-3'>
                    <span className='flex h-8 w-8 items-center justify-center rounded-full border-2 border-red-500 text-red-500'>
                      ✗
                    </span>
                    <span>
                      Tap if it does <strong>not</strong> look like a triangle
                    </span>
                  </li>
                </ul>
              </div>

              <div className='rounded-lg bg-white/5 p-4'>
                <h3 className='mb-2 font-semibold text-white'>Tips</h3>
                <ul className='list-inside list-disc space-y-1 text-white/70'>
                  <li>Look at the white outline on the satellite image</li>
                  <li>Triangles have 3 sides and 3 corners</li>
                  <li>
                    Don&apos;t worry about being perfect - we collect multiple
                    votes
                  </li>
                  <li>Vote quickly based on your first impression</li>
                </ul>
              </div>

              <div className='rounded-lg bg-white/5 p-4'>
                <h3 className='mb-2 font-semibold text-white'>
                  Why does this matter?
                </h3>
                <p className='text-white/70'>
                  This data helps urban researchers understand the distribution
                  and characteristics of triangular parks in NYC, which are
                  unique urban spaces created by the city&apos;s grid system
                  meeting older diagonal roads.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Fixed footer with button */}
        <div className='border-t border-white/10 p-4'>
          <button
            onClick={handleEnter}
            className='w-full rounded-lg bg-white py-4 text-base font-semibold text-black transition-colors hover:bg-white/90'
          >
            Got it, let&apos;s start!
          </button>
        </div>
      </div>
    </div>
  );
}
