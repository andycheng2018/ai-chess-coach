import { useEffect, useState } from 'react';
import { studioBackend } from '../transport/native';

/**
 * One-time pairing on the app. The operator supplies the fingerprint from a device
 * that already trusts the dog, so the app never trusts a key because a dog offered it.
 */
export function PairingCard({ target, locked }: { target: string; locked: boolean }) {
  const [paired, setPaired] = useState('');
  const [fingerprint, setFingerprint] = useState('');
  const [password, setPassword] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    void studioBackend.pairing().then(saved => { if (current) setPaired(saved.fingerprint); }).catch(() => undefined);
    return () => { current = false; };
  }, []);

  const pair = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const saved = await studioBackend.pair({ target: target.trim(), fingerprint: fingerprint.trim(), password, confirmed });
      setPaired(saved.fingerprint);
      setFingerprint('');
      setConfirmed(false);
      setMessage('Paired. You can connect now.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Pairing failed.');
    } finally {
      setPassword('');
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>Pair this app</h2>
      {paired
        ? <p className="fine">Paired with <span className="mono">{paired}</span>. Pair again only for a different dog, or if its key really changed.</p>
        : <p className="fine">Do this once per dog, on the same Wi-Fi. It adds this app’s SSH key to the dog.</p>}
      <div className="pair-fields">
        <label className="field">
          <span>Dog’s SSH key fingerprint</span>
          <input value={fingerprint} disabled={busy || locked} placeholder="SHA256:…" autoCapitalize="none" autoCorrect="off" spellCheck={false}
            onChange={event => setFingerprint(event.target.value)} />
          <small>On a computer that already trusts the dog, run <code>ssh-keygen -lF &lt;dog address&gt;</code>. If the app reports a different key type, compare that one.</small>
        </label>
        <label className="field">
          <span>Dog’s SSH password</span>
          <input type="password" value={password} disabled={busy || locked} autoComplete="off" onChange={event => setPassword(event.target.value)} />
          <small>Used once for pairing, and never saved.</small>
        </label>
        <label className="check">
          <input type="checkbox" checked={confirmed} disabled={busy || locked} onChange={event => setConfirmed(event.target.checked)} />
          <span>I got this fingerprint from a device that already trusts this dog.</span>
        </label>
        <button className="btn" disabled={busy || locked || !target.trim() || !fingerprint.trim() || !password || !confirmed} onClick={() => void pair()}>
          {busy ? 'Pairing…' : 'Pair with this dog'}
        </button>
        {locked && <p className="fine">Disconnect before pairing again.</p>}
        {message && <p className="notice" role="status">{message}</p>}
      </div>
    </section>
  );
}
