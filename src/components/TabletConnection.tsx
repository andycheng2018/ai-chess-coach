import { useState, type ReactNode } from 'react';
import { Capacitor } from '@capacitor/core';
import { clearConnection, parsePairingQr, saveConnection, TABLET_HEADER, validateConnection, type TabletConnection } from '../nativeBackend';

/**
 * Pair this device with a Chess Buddy server: a Mac on the same Wi-Fi, or a hosted
 * server such as https://chess-api.urbot.ai. A saved server replaces the tablet's own
 * backend, so its pairing key unlocks coaching, bot accounts and robot controls there.
 */
export function ServerConnectionPanel({ existing, onClose, children }: {
  existing: TabletConnection | null; onClose: () => void; children?: ReactNode;
}) {
  const native = Capacitor.getPlatform() === 'android';
  const [url, setUrl] = useState(existing?.url || 'https://chess-api.urbot.ai');
  const [token, setToken] = useState(existing?.token || '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function connect() {
    setBusy(true); setError('');
    try {
      const connection = validateConnection({ url, token });
      const response = await fetch(`${connection.url}/api/health`, { headers: { [TABLET_HEADER]: connection.token }, signal: AbortSignal.timeout(10000), redirect: 'error' });
      const data = await response.json().catch(() => ({}));
      if (response.status === 403) throw new Error('The server refused this pairing key. Copy the key from its pairing page again.');
      if (!response.ok || !data.ok || data.tabletPairing !== true) throw new Error(data.message || 'That server is not set up for pairing.');
      saveConnection(connection);
      window.location.reload();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not reach the server. Check the address and the Internet connection.'); }
    finally { setBusy(false); }
  }
  async function scan() {
    setBusy(true); setError('');
    try {
      const { scanSenseRoomUrl } = await import('../senseScanner');
      const connection = parsePairingQr(await scanSenseRoomUrl('Scan the Chess Buddy server pairing QR'));
      setUrl(connection.url); setToken(connection.token);
      // Show the scanned destination for review before sending the pairing key.
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not scan the pairing QR.'); }
    finally { setBusy(false); }
  }
  function forget() {
    clearConnection();
    window.location.reload();
  }
  return <div className="tablet-connection-backdrop"><section className="card tablet-connection-card" role="dialog" aria-modal="true" aria-labelledby="server-connection-title">
    <span className="eyebrow">CHESS BUDDY · SERVER</span><h1 id="server-connection-title">{existing ? 'Connected to a Chess Buddy server' : 'Use a Chess Buddy server'}</h1>
    <p>The server runs Stockfish, Luna, the Lichess bot and the VBOT controller. This device shows the board and coaching. {native && 'While a server is saved, this tablet does not start its own backend.'}</p>
    {native && <button className="ghost" disabled={busy} onClick={() => void scan()}>Scan server pairing QR</button>}
    <form onSubmit={event => { event.preventDefault(); void connect(); }}>
      <label>Server address<input aria-label="Server address" autoCapitalize="none" autoCorrect="off" type="url" placeholder="https://chess-api.urbot.ai" value={url} onChange={event => setUrl(event.target.value)} disabled={busy}/></label>
      <label>Pairing key<input aria-label="Pairing key" type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} disabled={busy}/></label>
      <p className="fine-print">The key authorizes this device to use the server’s coaching, bot accounts and robot controls, from anywhere. Keep it private. Robot readiness checks and onsite confirmation still apply, and reactions turn off if this device stops checking in.</p>
      {error && <p className="inline-error" role="alert">{error}</p>}
      <div className="analysis-navigation"><button className="primary" disabled={busy || !url || !token}>{busy ? 'Checking connection…' : existing ? 'Save and reconnect' : 'Connect'}</button>
        <button type="button" className="ghost" disabled={busy} onClick={onClose}>Back</button>
        {existing && <button type="button" className="ghost" disabled={busy} onClick={forget}>{native ? 'Forget server and use this tablet' : 'Forget server'}</button>}</div>
    </form>
    {children}
  </section></div>;
}
