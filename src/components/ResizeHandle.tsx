import { useRef } from 'react';

type Props = { label: string; axis: 'x' | 'y'; value: number; min: number; max: number; percent?: boolean; reversed?: boolean; onChange: (value: number) => void };
export function ResizeHandle({ label, axis, value, min, max, percent, reversed, onChange }: Props) {
  const drag = useRef<{ coordinate: number; value: number; scale: number } | null>(null);
  function change(next: number) { onChange(Math.round(Math.max(min, Math.min(max, next)))); }
  return <div className={`analysis-resize ${axis === 'x' ? 'vertical' : 'horizontal'}`} role="separator" tabIndex={0}
    aria-label={label} aria-orientation={axis === 'x' ? 'vertical' : 'horizontal'} aria-valuemin={min} aria-valuemax={max} aria-valuenow={value}
    title="Drag to resize, or use arrow keys" onPointerDown={event => {
      event.preventDefault(); event.currentTarget.focus(); event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { coordinate: axis === 'x' ? event.clientX : event.clientY, value, scale: percent ? 100 / (event.currentTarget.parentElement?.clientWidth || 1) : 1 };
    }} onPointerMove={event => {
      if (drag.current) change(drag.current.value + ((axis === 'x' ? event.clientX : event.clientY) - drag.current.coordinate) * drag.current.scale * (reversed ? -1 : 1));
    }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}
    onKeyDown={event => {
      const direction = axis === 'x' ? { ArrowLeft: -1, ArrowRight: 1 } : { ArrowUp: -1, ArrowDown: 1 };
      const amount = direction[event.key as keyof typeof direction];
      if (event.key === 'Home' || event.key === 'End' || amount) {
        event.preventDefault(); change(event.key === 'Home' ? min : event.key === 'End' ? max : value + amount! * (percent ? 2 : 20) * (reversed ? -1 : 1));
      }
    }}><span aria-hidden="true">{axis === 'x' ? '↔' : '↕'}</span></div>;
}
