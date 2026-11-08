import { useEffect, useRef, useState } from 'react';
import { backendUrl } from '../backendUrl';
import { VOICE_STATE_TEXT, type VoiceStatus } from '../voiceMode';

const POLL_MS = 3000;

/** On/off for Qwen voice mode, plus what the dog heard and said. Hidden on servers without it. */
export function VoiceModeControl() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const url = `${backendUrl()}/api/vbot/voice`;
  const switching = useRef(false);

  useEffect(() => {
    let active = true;
    async function poll() {
      if (document.hidden || switching.current) return;
      try {
        const response = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(8000) });
        if (active && response.ok && !switching.current) setStatus(await response.json());
      } catch { /* The rest of the panel already reports a lost server. */ }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), POLL_MS);
    return () => { active = false; window.clearInterval(timer); };
  }, [url]);

  async function toggle(enabled: boolean) {
    setBusy(true); setError(''); switching.current = true;
    try {
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }), signal: AbortSignal.timeout(25000) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'The server refused that change.');
      setStatus(data);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not reach the server.'); }
    finally { switching.current = false; setBusy(false); }
  }

  if (!status) return null;
  const recent = [...status.turns].reverse().slice(0, 3);
  const session = status.sessions?.find(item => item.id === status.activeSession);
  return <div className="voice-mode">
    <div className="voice-mode-top">
      <strong>Qwen voice mode</strong>
      <button className={status.enabled ? 'ghost' : 'primary'} disabled={busy || (!status.available && !status.enabled)} onClick={() => void toggle(!status.enabled)}>
        {busy ? 'Working…' : status.enabled ? 'Turn off' : 'Turn on'}
      </button>
    </div>
    <p className={`voice-mode-state ${status.state === 'error' ? 'error' : ''}`} role="status">{status.message || VOICE_STATE_TEXT[status.state]}</p>
    <p>{status.available ? 'Say the wake word and talk. Qwen answers instead of the dog’s built-in assistant, and it stays on after you close this app.' : status.reason}</p>
    {session && <p>Session: {session.title || 'New session'} · {session.turnCount} {session.turnCount === 1 ? 'turn' : 'turns'}</p>}
    {error && <p className="voice-mode-state error" role="alert">{error}</p>}
    {recent.length > 0 && <ul className="voice-mode-turns">
      {recent.map(turn => <li key={turn.id}>
        <span><b>{turn.source === 'typed' ? 'Typed:' : 'Heard:'}</b> {turn.heard}</span>
        {turn.understood && turn.understood !== turn.heard && <span><b>Understood:</b> {turn.understood}</span>}
        {turn.reply && <span><b>{turn.clarifying ? 'Asked:' : 'Qwen:'}</b> {turn.reply}</span>}
        {turn.error && <span>{turn.error}</span>}
      </li>)}
    </ul>}
  </div>;
}
