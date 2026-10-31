import { useState, type ReactNode } from 'react';
import { Capacitor } from '@capacitor/core';
import { clearConnection, parsePairingQr, readConnection, saveConnection, TABLET_HEADER, validateConnection } from '../nativeBackend';

export function TabletConnection({ children }: { children: ReactNode }) {
  const native = Capacitor.getPlatform() === 'android';
  const existing = readConnection();
  const [open, setOpen] = useState(native && !existing);
  const [url, setUrl] = useState(existing?.url || '');
  const [token, setToken] = useState(existing?.token || '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function connect(next = { url, token }) {
    setBusy(true); setError('');
    try {
      const connection = validateConnection(next);
      const response = await fetch(`${connection.url}/api/health`, { headers: { [TABLET_HEADER]: connection.token }, signal: AbortSignal.timeout(10000), redirect: 'error' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok || data.tabletPairing !== true) throw new Error(data.message || 'Open the tablet backend launcher on your Mac and use its pairing key.');
      saveConnection(connection);
      window.location.reload();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not reach the Mac. Check Wi-Fi and its address.'); }
    finally { setBusy(false); }
  }
  async function scan() {
    setBusy(true); setError('');
    try {
      const { scanSenseRoomUrl } = await import('../senseScanner');
      const connection = parsePairingQr(await scanSenseRoomUrl('Scan the Chess Buddy pairing QR on your Mac'));
      setUrl(connection.url); setToken(connection.token);
      // Show the scanned destination for review before sending the pairing key.
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not scan the pairing QR.'); }
    finally { setBusy(false); }
  }
  if (!native) return <>{children}</>;
  return <>
    {existing && children}
    {!open && <button className="tablet-connection-button ghost" onClick={() => setOpen(true)}>Mac connection</button>}
    {open && <div className="tablet-connection-backdrop"><section className="card tablet-connection-card" role="dialog" aria-modal="true" aria-labelledby="tablet-connection-title">
      <span className="eyebrow">CHESS BUDDY · TABLET</span><h1 id="tablet-connection-title">Connect to your Mac</h1>
      <p>Your tablet runs the board, coaching windows, and SenseRobot setup. Your Mac runs Stockfish, Luna, and the VBOT companion.</p>
      <ol><li>Put this tablet and your Mac on the same trusted Wi-Fi.</li><li>On the Mac, double-click <strong>Open Chess Buddy Tablet.command</strong>.</li><li>Scan its pairing QR or enter the address and key below.</li></ol>
      <button className="ghost" disabled={busy} onClick={() => void scan()}>Scan Mac pairing QR</button>
      <form onSubmit={event => { event.preventDefault(); void connect(); }}>
        <label>Mac server address<input aria-label="Mac server address" autoCapitalize="none" autoCorrect="off" type="url" placeholder="http://192.168.0.20:8765" value={url} onChange={event => setUrl(event.target.value)} disabled={busy}/></label>
        <label>Pairing key<input aria-label="Pairing key" type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} disabled={busy}/></label>
        <p className="fine-print">The key authorizes this tablet to use the Mac’s coaching and robot controls. Use a trusted local network for HTTP connections. Robot readiness and onsite confirmation still apply.</p>
        {error && <p className="inline-error" role="alert">{error}</p>}
        <div className="analysis-navigation"><button className="primary" disabled={busy || !url || !token}>{busy ? 'Checking connection…' : 'Connect tablet'}</button>
          {existing && <button type="button" className="ghost" disabled={busy} onClick={() => setOpen(false)}>Back to app</button>}
          {existing && <button type="button" className="ghost" disabled={busy} onClick={() => { clearConnection(); window.location.reload(); }}>Forget Mac</button>}</div>
      </form>
    </section></div>}
  </>;
}
