import { useState } from 'react';
import { DEFAULT_CLOUD_URL, parsePairingQr, validatePairing, type CloudPairing } from '../transport/cloudPairing';
import { isNativeApp } from '../transport/native';

async function scanQr(): Promise<string> {
  const { CapacitorBarcodeScanner, CapacitorBarcodeScannerCameraDirection, CapacitorBarcodeScannerScanOrientation } = await import('@capacitor/barcode-scanner');
  const result = await CapacitorBarcodeScanner.scanBarcode({
    hint: 0, // QR code
    cameraDirection: CapacitorBarcodeScannerCameraDirection.BACK,
    scanOrientation: CapacitorBarcodeScannerScanOrientation.ADAPTIVE,
    scanInstructions: 'Scan the pairing QR on your computer',
  });
  const value = result.ScanResult?.trim();
  if (!value) throw new Error('No QR code was scanned.');
  return value;
}

/** The key is saved on this device only, and it can control the dog from anywhere. */
export function CloudPairingCard({ pairing, locked, onChange }: { pairing: CloudPairing | null; locked: boolean; onChange: (pairing: CloudPairing | null) => void }) {
  const [url, setUrl] = useState(DEFAULT_CLOUD_URL);
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [scanning, setScanning] = useState(false);
  const [scanned, setScanned] = useState(false);

  async function scan() {
    setScanning(true); setError(''); setScanned(false);
    try {
      const found = parsePairingQr(await scanQr());
      // Shown for review first, so the key is saved only for a server you recognise.
      setUrl(found.url); setToken(found.token); setScanned(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not scan the pairing QR.'); }
    finally { setScanning(false); }
  }

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
    {isNativeApp && <button type="button" className="btn" disabled={scanning} onClick={() => void scan()}>{scanning ? 'Opening camera…' : 'Scan pairing QR'}</button>}
    {scanned && <p className="fine" role="status">QR scanned. Check the server address, then save.</p>}
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
