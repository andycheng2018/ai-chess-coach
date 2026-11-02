/**
 * A stylised stand-in for the dog's screen. It is not a recording of the real
 * animation, and every place that shows it says so.
 */
type Mood = 'neutral' | 'happy' | 'sad' | 'wide' | 'think' | 'sleep' | 'wink';

const MOODS: readonly (readonly [RegExp, Mood])[] = [
  [/happy|happines|cheer|excited|proud|love|trust|rock|party|birthday|festival|year|fireworks|rhythm|swing/i, 'happy'],
  [/sad|regret|wronged|worry|fear|nervous|timid|displeased|dislike|angry|sign/i, 'sad'],
  [/surprise|astonished|dizzy|courage/i, 'wide'],
  [/think|doubt|search|look|confound|listen|loading/i, 'think'],
  [/sleep|rest|yawn|droway|breathe/i, 'sleep'],
  [/wink|blink|say hi|wave|high five/i, 'wink'],
];

export function moodFor(label: string): Mood {
  return MOODS.find(([pattern]) => pattern.test(label))?.[1] ?? 'neutral';
}

function Eye({ mood, side }: { mood: Mood; side: 'left' | 'right' }) {
  const cx = side === 'left' ? 58 : 142;
  const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 9, strokeLinecap: 'round' as const };
  if (mood === 'happy') return <path d={`M${cx - 20} 62 Q${cx} 32 ${cx + 20} 62`} {...stroke} />;
  if (mood === 'sleep') return <path d={`M${cx - 20} 52 Q${cx} 66 ${cx + 20} 52`} {...stroke} />;
  if (mood === 'sad') return <path d={side === 'left' ? `M${cx - 20} 42 Q${cx + 6} 44 ${cx + 20} 64` : `M${cx - 20} 64 Q${cx - 6} 44 ${cx + 20} 42`} {...stroke} />;
  if (mood === 'wink' && side === 'right') return <path d={`M${cx - 20} 52 H${cx + 20}`} {...stroke} />;
  if (mood === 'think' && side === 'right') return <rect x={cx - 18} y={46} width={36} height={14} rx={7} fill="currentColor" />;
  const size = mood === 'wide' ? 22 : 16;
  return <rect className="eye-blink" x={cx - size} y={50 - size} width={size * 2} height={size * 2} rx={size * .55} fill="currentColor" />;
}

export function FacePreview({ label, playing = true, size = 'large' }: { label: string; playing?: boolean; size?: 'large' | 'small' }) {
  const mood = moodFor(label);
  return (
    <figure className={`face-preview face-${size} ${playing ? 'is-playing' : ''}`}>
      <svg viewBox="0 0 200 100" role="img" aria-label={`Stylised face: ${label}`}>
        <rect x="2" y="2" width="196" height="96" rx="26" className="face-screen" />
        <g className="face-eyes"><Eye mood={mood} side="left" /><Eye mood={mood} side="right" /></g>
      </svg>
      {size === 'large' && <figcaption>Stylised stand-in, not the dog’s real animation</figcaption>}
    </figure>
  );
}
