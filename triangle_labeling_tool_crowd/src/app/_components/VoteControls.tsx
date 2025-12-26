'use client';

interface Park {
  id: number;
  signname: string | null;
  name311: string | null;
  borough: string | null;
  typecategory: string | null;
}

interface VoteControlsProps {
  park: Park;
  onVote: (isTriangle: boolean) => void;
  disabled?: boolean;
  canUndo?: boolean;
  onUndo?: () => void;
}

export function VoteControls({
  park,
  onVote,
  disabled,
  canUndo,
  onUndo,
}: VoteControlsProps) {
  return (
    <div className='absolute inset-4 z-20 flex flex-col justify-between pointer-events-none md:inset-8 rounded-lg border-2 border-white/40'>
      {/* Park info overlay - top */}
      <div className='flex items-start justify-between p-4 pointer-events-auto'>
        <div className='inline-block rounded bg-black/60 px-3 py-2'>
          <p className='text-xs uppercase tracking-wider text-white/70'>
            {park.borough} · {park.typecategory}
          </p>
          <h2 className='mt-1 truncate text-lg font-bold text-white'>
            {park.signname || park.name311 || 'Unnamed Park'}
          </h2>
        </div>

        {/* Undo button */}
        {canUndo && onUndo && (
          <button
            onClick={onUndo}
            className='flex items-center gap-2 rounded bg-black/60 px-3 py-2 text-sm text-white/70 transition-colors hover:bg-black/80 hover:text-white'
            aria-label='Undo last vote'
          >
            <UndoIcon className='h-4 w-4' />
            <span>Undo</span>
          </button>
        )}
      </div>

      {/* Action buttons - bottom */}
      <div className='flex flex-col items-center p-6 pb-8 pointer-events-auto'>
        <div className='mb-4 flex w-full justify-center gap-12 text-xs uppercase tracking-wider'>
          <span className='rounded bg-black/60 px-3 py-1 text-white/80'>
            Not Triangle
          </span>
          <span className='rounded bg-black/60 px-3 py-1 text-white/80'>
            Triangle
          </span>
        </div>

        <div className='flex items-center justify-center gap-8'>
          <button
            onClick={() => onVote(false)}
            disabled={disabled}
            className='group flex h-20 w-20 items-center justify-center rounded-full border-2 border-red-500 bg-black/50 text-red-500 transition-all hover:scale-110 hover:bg-red-500 hover:text-white active:scale-95 disabled:opacity-50 disabled:pointer-events-none'
            aria-label='Not a triangle'
          >
            <XIcon className='h-10 w-10 transition-transform group-hover:scale-110' />
          </button>

          <button
            onClick={() => onVote(true)}
            disabled={disabled}
            className='group flex h-20 w-20 items-center justify-center rounded-full border-2 border-green-500 bg-black/50 text-green-500 transition-all hover:scale-110 hover:bg-green-500 hover:text-white active:scale-95 disabled:opacity-50 disabled:pointer-events-none'
            aria-label='Triangle'
          >
            <CheckIcon className='h-10 w-10 transition-transform group-hover:scale-110' />
          </button>
        </div>
      </div>
    </div>
  );
}

// Icons
function XIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill='none'
      viewBox='0 0 24 24'
      stroke='currentColor'
      strokeWidth={3}
    >
      <path
        strokeLinecap='round'
        strokeLinejoin='round'
        d='M6 18L18 6M6 6l12 12'
      />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill='none'
      viewBox='0 0 24 24'
      stroke='currentColor'
      strokeWidth={3}
    >
      <path strokeLinecap='round' strokeLinejoin='round' d='M5 13l4 4L19 7' />
    </svg>
  );
}

function UndoIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill='none'
      viewBox='0 0 24 24'
      stroke='currentColor'
      strokeWidth={2}
    >
      <path
        strokeLinecap='round'
        strokeLinejoin='round'
        d='M3 10h10a5 5 0 015 5v2M3 10l4-4M3 10l4 4'
      />
    </svg>
  );
}
