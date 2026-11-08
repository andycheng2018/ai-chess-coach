import { useState } from 'react';
import { DEFAULT_CLOUD_URL, validatePairing, type CloudPairing } from '../transport/cloudPairing';

/** The key is saved on this device only, and it can control the dog from anywhere. */
export function CloudPairingCard({ pairing, locked, onChange }: { pairing: CloudPairing | null; locked: boolean; onChange: (pairing: CloudPairing | null) => void }) {
  const [url, setUrl] = useState(DEFAULT_CLOUD_URL);
  const [token, setToken] = useState('');
  const [error, setError] = useState('');

  if (pairing) {
    return <div className="cloud-pairing">
      <p className="fine">Paired with <strong>{new URL(pairing.url).host}</strong> on this device.</p>
      <button className="btn" disabled={locked} onClick={() => onChange(null)}>Forget this key</button>
    </div>;
  }
  return <form className="cloud-pairing" onSubmit={event => {
    event.preventDefault();
    try { onChange(validatePairing({ url, token })); setToken(''); setError(''); }
    catch (cause) { setError((cause as Error).message); }
  }}>
    <label className="field"><span>Server address</span>
      <input value={url} autoCapitalize="none" autoCorrect="off" spellCheck={false} onChange={event => setUrl(event.target.value)} />
    </label>
    <label className="field"><span>Pairing key</span>
      <input type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} />
      <small>This key can control the dog from anywhere. It’s saved only on this device.</small>
    </label>
    {error && <p className="notice notice-warn" role="alert">{error}</p>}
    <button className="btn btn-primary" disabled={!token.trim()}>Save pairing</button>
  </form>;
}
