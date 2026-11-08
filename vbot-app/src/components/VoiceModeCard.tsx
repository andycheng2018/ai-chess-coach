import { useEffect, useRef, useState } from 'react';

type Turn = { id: string; heard: string; understood: string; clarifying: boolean; reply: string; error?: string };
type Status = { available: boolean; reason?: string; enabled: boolean; state: string; message?: string; turns: Turn[] };

const BASE = '/api/app/voice';
const OFF_TEXT = 'Off. The dog’s built-in assistant is answering.';

/** Studio's switch for Qwen voice mode. This Mac's controller holds the cloud key. */
export function VoiceModeCard() {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const switching = useRef(false);

  useEffect(() => {
    let active = true;
    async function poll() {
      if (document.hidden || switching.current) return;
      try {
        const response = await fetch(BASE, { cache: 'no-store' });
        if (active && response.ok && !switching.current) setStatus(await response.json());
      } catch { /* Shown by the next successful poll or a toggle error. */ }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  async function toggle(enabled: boolean) {
    setBusy(true); setError(''); switching.current = true;
    try {
      const response = await fetch(BASE, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'The server refused that change.');
      setStatus(data);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not reach the cloud server.'); }
    finally { switching.current = false; setBusy(false); }
  }

  if (!status) return null;
  const recent = [...status.turns].reverse().slice(0, 3);
  return (
    <section className="card voice-card">
      <div className="voice-card-top">
        <h2>Qwen voice mode</h2>
        <button className={`btn ${status.enabled ? '' : 'btn-primary'}`} disabled={busy || (!status.available && !status.enabled)} onClick={() => void toggle(!status.enabled)}>
          {busy ? 'Working…' : status.enabled ? 'Turn off' : 'Turn on'}
        </button>
      </div>
      <p className={`voice-state ${status.state === 'error' ? 'is-error' : ''}`} role="status">{status.message || (status.enabled ? 'Connecting…' : OFF_TEXT)}</p>
      <p className="fine">{status.available ? 'Say the wake word and talk. Qwen answers instead of the dog’s built-in assistant, and it stays on after you close this app.' : status.reason}</p>
      {error && <p className="voice-state is-error" role="alert">{error}</p>}
      {recent.length > 0 && (
        <ul className="voice-turns">
          {recent.map(turn => (
            <li key={turn.id}>
              <span><b>Heard:</b> {turn.heard}</span>
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
