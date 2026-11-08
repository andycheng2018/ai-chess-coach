import { useEffect, useRef, useState } from 'react';

type Turn = { id: string; heard: string; understood: string; clarifying: boolean; reply: string; error?: string; source?: 'voice' | 'typed' };
type Session = { id: string; title: string; startedAt: number; updatedAt: number; turnCount: number };
type Status = { available: boolean; reason?: string; enabled: boolean; state: string; message?: string; activeSession?: string | null; sessions?: Session[]; turns: Turn[] };

const BASE = '/api/app/voice';
const OFF_TEXT = 'Off. The dog’s built-in assistant is answering.';

function sessionLabel(session: Session) {
  const when = new Date(session.updatedAt * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  return `${session.title || 'New session'} · ${when} · ${session.turnCount} ${session.turnCount === 1 ? 'turn' : 'turns'}`;
}

/** Studio's controls for Qwen voice mode and its sessions. This Mac's controller holds the cloud key. */
export function VoiceModeCard() {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [text, setText] = useState('');
  const working = useRef(false);

  useEffect(() => {
    let active = true;
    async function poll() {
      if (document.hidden || working.current) return;
      try {
        const response = await fetch(BASE, { cache: 'no-store' });
        if (active && response.ok && !working.current) setStatus(await response.json());
      } catch { /* Shown by the next successful poll or an action error. */ }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  async function send(path: string, body: object): Promise<boolean> {
    setBusy(true); setError(''); working.current = true;
    try {
      const response = await fetch(BASE + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'The server refused that change.');
      setStatus(data);
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not reach the cloud server.');
      return false;
    } finally { working.current = false; setBusy(false); }
  }

  if (!status) return null;
  const recent = [...status.turns].reverse();
  const sessions = status.sessions ?? [];
  return (
    <section className="card voice-card">
      <div className="voice-card-top">
        <h2>Qwen voice mode</h2>
        <button className={`btn ${status.enabled ? '' : 'btn-primary'}`} disabled={busy || (!status.available && !status.enabled)} onClick={() => void send('', { enabled: !status.enabled })}>
          {busy ? 'Working…' : status.enabled ? 'Turn off' : 'Turn on'}
        </button>
      </div>
      <p className={`voice-state ${status.state === 'error' ? 'is-error' : ''}`} role="status">{status.message || (status.enabled ? 'Connecting…' : OFF_TEXT)}</p>
      <p className="fine">{status.available ? 'Say the wake word and talk. Qwen answers instead of the dog’s built-in assistant, and it stays on after you close this app.' : status.reason}</p>
      {status.available && <>
        <div className="voice-sessions">
          <label>Session
            <select value={status.activeSession ?? ''} disabled={busy || !sessions.length} onChange={event => void send('/session/continue', { id: event.target.value })}>
              {!sessions.length && <option value="">No sessions yet</option>}
              {sessions.map(session => <option key={session.id} value={session.id}>{sessionLabel(session)}</option>)}
            </select>
          </label>
          <button className="btn" disabled={busy} onClick={() => void send('/session/new', {})}>New session</button>
        </div>
        <form className="voice-input" onSubmit={event => {
          event.preventDefault();
          const message = text.trim();
          if (message && !busy) void send('/message', { text: message }).then(sent => { if (sent) setText(''); });
        }}>
          <input aria-label="Type a message to Qwen" maxLength={1000} value={text} onChange={event => setText(event.target.value)} placeholder="Type to continue this session" autoComplete="off" />
          <button className="btn" disabled={busy || !text.trim()}>Send</button>
        </form>
      </>}
      {error && <p className="voice-state is-error" role="alert">{error}</p>}
      {recent.length > 0 && (
        <ul className="voice-turns">
          {recent.map(turn => (
            <li key={turn.id}>
              <span><b>{turn.source === 'typed' ? 'Typed:' : 'Heard:'}</b> {turn.heard}</span>
              {turn.understood && turn.understood !== turn.heard && <span><b>Understood:</b> {turn.understood}</span>}
              {turn.reply && <span><b>{turn.clarifying ? 'Asked:' : 'Qwen:'}</b> {turn.reply}</span>}
              {turn.error && <span>{turn.error}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
