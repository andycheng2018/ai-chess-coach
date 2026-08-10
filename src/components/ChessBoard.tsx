import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react';

export type Arrow = { from: string; to: string; kind?: 'best' | 'danger' | 'idea' };

type Props = {
  fen: string;
  orientation: 'white' | 'black';
  movableColor?: 'white' | 'black';
  destinations: Map<string, string[]>;
  lastMove?: [string, string];
  coachArrows: Arrow[];
  coachHighlights: string[];
  rollbackSignal: number;
  onMove: (from: string, to: string) => void;
};

type DragState = {
  pointerId: number;
  from: string;
  pieceCode: string;
  x: number;
  y: number;
  startX: number;
  startY: number;
  hasMoved: boolean;
  snapping: boolean;
};

type PendingVisual = {
  from: string;
  to: string;
  pieceCode: string;
  sourceFen: string;
  started: boolean;
};

type RemoteAnimation = Omit<PendingVisual, 'sourceFen'>;

const PIECES: Record<string, { glyph: string; color: 'white' | 'black' }> = {
  K: { glyph: '♔', color: 'white' }, Q: { glyph: '♕', color: 'white' }, R: { glyph: '♖', color: 'white' },
  B: { glyph: '♗', color: 'white' }, N: { glyph: '♘', color: 'white' }, P: { glyph: '♙', color: 'white' },
  k: { glyph: '♚', color: 'black' }, q: { glyph: '♛', color: 'black' }, r: { glyph: '♜', color: 'black' },
  b: { glyph: '♝', color: 'black' }, n: { glyph: '♞', color: 'black' }, p: { glyph: '♟', color: 'black' },
};

function fenToPieces(fen: string): Map<string, string> {
  const result = new Map<string, string>();
  const rows = fen.split(' ')[0].split('/');
  rows.forEach((row, rowIndex) => {
    let file = 0;
    for (const char of row) {
      if (/\d/.test(char)) file += Number(char);
      else {
        result.set(`${String.fromCharCode(97 + file)}${8 - rowIndex}`, char);
        file += 1;
      }
    }
  });
  return result;
}

function gridPosition(square: string, orientation: 'white' | 'black') {
  const file = square.charCodeAt(0) - 97;
  const rank = Number(square[1]) - 1;
  return {
    col: orientation === 'white' ? file : 7 - file,
    row: orientation === 'white' ? 7 - rank : rank,
  };
}

function squareCenter(square: string, orientation: 'white' | 'black') {
  const { col, row } = gridPosition(square, orientation);
  return { x: col * 12.5 + 6.25, y: row * 12.5 + 6.25 };
}

function arrowGeometry(from: string, to: string, orientation: 'white' | 'black') {
  const start = squareCenter(from, orientation);
  const end = squareCenter(to, orientation);
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const distance = Math.hypot(dx, dy) || 1;
  const ux = dx / distance;
  const uy = dy / distance;
  const endInset = Math.min(2.5, distance * 0.11);
  return { x1: start.x, y1: start.y, x2: end.x - ux * endInset, y2: end.y - uy * endInset };
}

export function ChessBoard(props: Props) {
  const { fen, orientation, movableColor, destinations, lastMove, coachArrows, coachHighlights, rollbackSignal, onMove } = props;
  const [selected, setSelected] = useState<string | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [pending, setPending] = useState<PendingVisual | null>(null);
  const [remoteAnimation, setRemoteAnimation] = useState<RemoteAnimation | null>(null);
  const [userArrows, setUserArrows] = useState<Array<{ from: string; to: string }>>([]);
  const [userHighlights, setUserHighlights] = useState<string[]>([]);
  const [drawFrom, setDrawFrom] = useState<string | null>(null);
  const [drawTo, setDrawTo] = useState<string | null>(null);
  const boardRef = useRef<HTMLDivElement | null>(null);
  const pendingTimer = useRef<number | null>(null);
  const dragTimer = useRef<number | null>(null);
  const remoteTimer = useRef<number | null>(null);
  const localMoveRef = useRef<string | null>(null);

  const pieces = useMemo(() => fenToPieces(fen), [fen]);
  const files = orientation === 'white' ? ['a','b','c','d','e','f','g','h'] : ['h','g','f','e','d','c','b','a'];
  const ranks = orientation === 'white' ? ['8','7','6','5','4','3','2','1'] : ['1','2','3','4','5','6','7','8'];

  useEffect(() => {
    return () => {
      if (pendingTimer.current !== null) window.clearTimeout(pendingTimer.current);
      if (dragTimer.current !== null) window.clearTimeout(dragTimer.current);
      if (remoteTimer.current !== null) window.clearTimeout(remoteTimer.current);
    };
  }, []);

  // The game stream is authoritative. As soon as it advances away from the
  // position where the student started the move, stop showing the optimistic
  // piece. This also handles the bot replying so quickly that the stream skips
  // straight from "before student move" to "after bot reply".
  useEffect(() => {
    if (!pending || fen === pending.sourceFen) return;
    if (pendingTimer.current !== null) window.clearTimeout(pendingTimer.current);
    pendingTimer.current = null;
    setPending(null);
    setDrag(null);
  }, [fen, pending]);

  useEffect(() => {
    setSelected(null);
    setUserArrows([]);
    setUserHighlights([]);
  }, [fen]);

  useEffect(() => {
    if (!lastMove) return;
    const [from, to] = lastMove;
    const key = `${from}${to}`;
    if (localMoveRef.current === key) {
      localMoveRef.current = null;
      setRemoteAnimation(null);
      return;
    }
    // If the bot replied before the browser observed the student's intermediate
    // position, the last move is now the bot move. Do not let an old local move
    // key suppress a later animation.
    localMoveRef.current = null;
    const pieceCode = pieces.get(to);
    if (!pieceCode) return;
    setRemoteAnimation({ from, to, pieceCode, started: false });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      setRemoteAnimation((current) => current && current.from === from && current.to === to ? { ...current, started: true } : current);
    }));
    if (remoteTimer.current !== null) window.clearTimeout(remoteTimer.current);
    remoteTimer.current = window.setTimeout(() => {
      setRemoteAnimation(null);
      remoteTimer.current = null;
    }, 190);
  }, [lastMove?.[0], lastMove?.[1], fen, pieces]);

  useEffect(() => {
    setPending(null);
    setDrag(null);
    setSelected(null);
    localMoveRef.current = null;
  }, [rollbackSignal]);

  function pointToSquare(clientX: number, clientY: number): string | null {
    const board = boardRef.current;
    if (!board) return null;
    const rect = board.getBoundingClientRect();
    if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) return null;
    const col = Math.min(7, Math.max(0, Math.floor(((clientX - rect.left) / rect.width) * 8)));
    const row = Math.min(7, Math.max(0, Math.floor(((clientY - rect.top) / rect.height) * 8)));
    return `${files[col]}${ranks[row]}`;
  }

  function clientCenter(square: string) {
    const board = boardRef.current;
    if (!board) return null;
    const rect = board.getBoundingClientRect();
    const center = squareCenter(square, orientation);
    return { x: rect.left + center.x * rect.width / 100, y: rect.top + center.y * rect.height / 100 };
  }

  function canSelect(square: string) {
    const code = pieces.get(square);
    return Boolean(code && movableColor && PIECES[code]?.color === movableColor && destinations.has(square));
  }

  function clearUserAnnotations() {
    setUserArrows([]);
    setUserHighlights([]);
  }

  function beginPending(from: string, to: string, pieceCode: string, animate: boolean) {
    localMoveRef.current = `${from}${to}`;
    setPending({ from, to, pieceCode, sourceFen: fen, started: !animate });
    if (animate) requestAnimationFrame(() => requestAnimationFrame(() => {
      setPending((current) => current && current.from === from && current.to === to ? { ...current, started: true } : current);
    }));
    if (pendingTimer.current !== null) window.clearTimeout(pendingTimer.current);
    pendingTimer.current = window.setTimeout(() => {
      setPending(null);
      setDrag(null);
      localMoveRef.current = null;
      pendingTimer.current = null;
    }, 10000);
    onMove(from, to);
  }

  function clickSquare(square: string) {
    if (drag?.hasMoved) return;
    clearUserAnnotations();
    if (!movableColor) return;
    if (selected && destinations.get(selected)?.includes(square)) {
      const pieceCode = pieces.get(selected);
      if (pieceCode) beginPending(selected, square, pieceCode, true);
      setSelected(null);
      return;
    }
    setSelected(canSelect(square) ? square : null);
  }

  function beginDrag(event: PointerEvent<HTMLSpanElement>, square: string, pieceCode: string) {
    if (event.button !== 0 || !canSelect(square)) return;
    event.preventDefault();
    event.stopPropagation();
    const board = boardRef.current;
    if (!board) return;
    try { board.setPointerCapture(event.pointerId); } catch { /* Pointer capture is an enhancement, not a requirement. */ }
    clearUserAnnotations();
    setSelected(square);
    setDrag({
      pointerId: event.pointerId,
      from: square,
      pieceCode,
      x: event.clientX,
      y: event.clientY,
      startX: event.clientX,
      startY: event.clientY,
      hasMoved: false,
      snapping: false,
    });
  }

  function moveDrag(event: PointerEvent<HTMLDivElement>) {
    if (!drag || drag.snapping || event.pointerId !== drag.pointerId) return;
    const moved = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) > 4;
    setDrag((current) => current && current.pointerId === event.pointerId
      ? { ...current, x: event.clientX, y: event.clientY, hasMoved: current.hasMoved || moved }
      : current);
  }

  function finishDrag(event: PointerEvent<HTMLDivElement>) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    event.preventDefault();
    try { event.currentTarget.releasePointerCapture(event.pointerId); } catch { /* no-op */ }

    if (!drag.hasMoved) {
      setDrag(null);
      setSelected(drag.from);
      return;
    }

    const destination = pointToSquare(event.clientX, event.clientY);
    const legal = Boolean(destination && destinations.get(drag.from)?.includes(destination));
    const targetSquare = legal && destination ? destination : drag.from;
    const target = clientCenter(targetSquare);
    if (!target) {
      setDrag(null);
      return;
    }

    setDrag((current) => current ? { ...current, x: target.x, y: target.y, snapping: true } : null);
    if (legal && destination) {
      setSelected(null);
      beginPending(drag.from, destination, drag.pieceCode, false);
      if (dragTimer.current !== null) window.clearTimeout(dragTimer.current);
      dragTimer.current = window.setTimeout(() => {
        setDrag(null);
        dragTimer.current = null;
      }, 130);
    } else {
      if (dragTimer.current !== null) window.clearTimeout(dragTimer.current);
      dragTimer.current = window.setTimeout(() => {
        setDrag(null);
        setSelected(drag.from);
        dragTimer.current = null;
      }, 130);
    }
  }

  function cancelDrag(event?: PointerEvent<HTMLDivElement>) {
    if (!drag) return;
    if (event && event.pointerId !== drag.pointerId) return;
    if (event) {
      try { event.currentTarget.releasePointerCapture(event.pointerId); } catch { /* no-op */ }
    }
    const target = clientCenter(drag.from);
    if (!target) {
      setDrag(null);
      return;
    }
    setDrag((current) => current ? { ...current, x: target.x, y: target.y, snapping: true } : null);
    if (dragTimer.current !== null) window.clearTimeout(dragTimer.current);
    dragTimer.current = window.setTimeout(() => {
      setDrag(null);
      dragTimer.current = null;
    }, 130);
  }

  const pendingPiece = pending ? PIECES[pending.pieceCode] : undefined;
  const pendingPos = pending ? gridPosition(pending.started ? pending.to : pending.from, orientation) : null;
  const remotePiece = remoteAnimation ? PIECES[remoteAnimation.pieceCode] : undefined;
  const remotePos = remoteAnimation ? gridPosition(remoteAnimation.started ? remoteAnimation.to : remoteAnimation.from, orientation) : null;
  const coachGeometry = coachArrows.map((arrow) => ({ ...arrow, geometry: arrowGeometry(arrow.from, arrow.to, orientation) }));
  const preview = drawFrom && drawTo && drawFrom !== drawTo ? arrowGeometry(drawFrom, drawTo, orientation) : null;

  return <>
    <div
      ref={boardRef}
      className="custom-board"
      role="grid"
      aria-label="Chess board"
      onContextMenu={(event) => event.preventDefault()}
      onPointerDown={(event) => {
        if (event.button !== 2 || drag) return;
        event.preventDefault();
        const from = pointToSquare(event.clientX, event.clientY);
        if (!from) return;
        try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* no-op */ }
        setDrawFrom(from);
        setDrawTo(from);
      }}
      onPointerMove={(event) => {
        if (drag) {
          moveDrag(event);
          return;
        }
        if (!drawFrom || (event.buttons & 2) === 0) return;
        const square = pointToSquare(event.clientX, event.clientY);
        if (square) setDrawTo(square);
      }}
      onPointerUp={(event) => {
        if (drag && event.button === 0) {
          finishDrag(event);
          return;
        }
        if (!drawFrom || event.button !== 2) return;
        event.preventDefault();
        try { event.currentTarget.releasePointerCapture(event.pointerId); } catch { /* no-op */ }
        const to = pointToSquare(event.clientX, event.clientY) ?? drawTo;
        if (!to || to === drawFrom) {
          setUserHighlights((current) => current.includes(drawFrom) ? current.filter((sq) => sq !== drawFrom) : [...current, drawFrom]);
        } else {
          setUserArrows((current) => current.some((a) => a.from === drawFrom && a.to === to)
            ? current.filter((a) => !(a.from === drawFrom && a.to === to))
            : [...current, { from: drawFrom, to }]);
        }
        setDrawFrom(null);
        setDrawTo(null);
      }}
      onPointerCancel={(event) => {
        if (drag) cancelDrag(event);
        setDrawFrom(null);
        setDrawTo(null);
      }}
    >
      {ranks.flatMap((rank, row) => files.map((file, col) => {
        const square = `${file}${rank}`;
        const pieceCode = pieces.get(square);
        const piece = pieceCode ? PIECES[pieceCode] : undefined;
        const isDestination = Boolean(selected && destinations.get(selected)?.includes(square));
        const hideStatic = Boolean(
          (pending && (pending.from === square || (pending.to === square && pending.started))) ||
          (drag && drag.from === square) ||
          (remoteAnimation && remoteAnimation.to === square)
        );
        return <button
          type="button"
          key={square}
          className={`square ${(row + col) % 2 === 0 ? 'light' : 'dark'} ${lastMove?.includes(square) ? 'last' : ''} ${selected === square ? 'selected' : ''} ${userHighlights.includes(square) ? 'user-highlighted' : ''} ${coachHighlights.includes(square) ? 'coach-highlighted' : ''}`}
          onClick={() => clickSquare(square)}
          aria-label={square}
        >
          {piece && pieceCode && !hideStatic && <span
            className={`piece ${piece.color} ${
              pieceCode.toLowerCase() === 'k'
                ? 'king-piece'
                : pieceCode.toLowerCase() === 'q'
                  ? 'queen-piece'
                  : ''
            }`}
            onPointerDown={(event) => beginDrag(event, square, pieceCode)}
          >{piece.glyph}</span>}
          {isDestination && <span className={piece ? 'destination capture' : 'destination'} />}
          {col === 0 && <small className="rank-label">{rank}</small>}
          {row === 7 && <small className="file-label">{file}</small>}
        </button>;
      }))}

      {pending && pendingPiece && pendingPos && !drag && <span
        className={`moving-board-piece ${pendingPiece.color}`}
        style={{ left: `${pendingPos.col * 12.5}%`, top: `${pendingPos.row * 12.5}%` }}
        aria-hidden="true"
      >{pendingPiece.glyph}</span>}

      {remoteAnimation && remotePiece && remotePos && <span
        className={`moving-board-piece remote ${remotePiece.color}`}
        style={{ left: `${remotePos.col * 12.5}%`, top: `${remotePos.row * 12.5}%` }}
        aria-hidden="true"
      >{remotePiece.glyph}</span>}

      {(coachGeometry.length > 0 || userArrows.length > 0 || preview) && <svg className="arrow-layer" viewBox="0 0 100 100" aria-hidden="true">
        <defs>
          <marker id="best-head" markerUnits="userSpaceOnUse" markerWidth="5.2" markerHeight="5.2" refX="4.7" refY="2.6" orient="auto"><path d="M0,0 L5.2,2.6 L0,5.2 Z" fill="rgba(105,183,73,.92)" /></marker>
          <marker id="danger-head" markerUnits="userSpaceOnUse" markerWidth="5.2" markerHeight="5.2" refX="4.7" refY="2.6" orient="auto"><path d="M0,0 L5.2,2.6 L0,5.2 Z" fill="rgba(225,87,72,.92)" /></marker>
          <marker id="idea-head" markerUnits="userSpaceOnUse" markerWidth="5.2" markerHeight="5.2" refX="4.7" refY="2.6" orient="auto"><path d="M0,0 L5.2,2.6 L0,5.2 Z" fill="rgba(79,151,214,.92)" /></marker>
          <marker id="user-head" markerUnits="userSpaceOnUse" markerWidth="5.5" markerHeight="5.5" refX="5" refY="2.75" orient="auto"><path d="M0,0 L5.5,2.75 L0,5.5 Z" fill="rgba(42,137,55,.84)" /></marker>
        </defs>
        {userArrows.map((arrow) => { const g = arrowGeometry(arrow.from, arrow.to, orientation); return <line key={`${arrow.from}-${arrow.to}`} {...g} stroke="rgba(42,137,55,.84)" strokeWidth="2.35" strokeLinecap="round" markerEnd="url(#user-head)" />; })}
        {preview && <line {...preview} stroke="rgba(42,137,55,.62)" strokeWidth="2.35" strokeLinecap="round" markerEnd="url(#user-head)" />}
        {coachGeometry.map((arrow, index) => {
          const kind = arrow.kind || 'idea';
          const stroke = kind === 'best' ? 'rgba(105,183,73,.92)' : kind === 'danger' ? 'rgba(225,87,72,.92)' : 'rgba(79,151,214,.92)';
          return <line key={`${arrow.from}-${arrow.to}-${index}`} {...arrow.geometry} stroke={stroke} strokeWidth="2.05" strokeLinecap="round" opacity=".9" markerEnd={`url(#${kind}-head)`} />;
        })}
      </svg>}
    </div>

    {drag && PIECES[drag.pieceCode] && <div
      className={`floating-chess-piece ${PIECES[drag.pieceCode].color} ${drag.snapping ? 'snapping' : ''}`}
      style={{
        left: drag.x,
        top: drag.y,
        '--drag-piece-size': `${(boardRef.current?.getBoundingClientRect().width ?? 640) / 8}px`,
      } as CSSProperties}
      aria-hidden="true"
    >{PIECES[drag.pieceCode].glyph}</div>}
  </>;
}
