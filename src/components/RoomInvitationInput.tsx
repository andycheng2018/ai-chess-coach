import { useRef, useState } from 'react';
import { normalizeRoomInvitation } from '../roomInvitation';

type Props = { id: string; value: string; disabled: boolean; onChange: (value: string) => void; onBusyChange: (busy: boolean) => void };

export function RoomInvitationInput({ id, value, disabled, onChange, onBusyChange }: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const inFlight = useRef(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function read(source: () => Promise<string>) {
    if (disabled || inFlight.current) return;
    inFlight.current = true; setReading(true); onBusyChange(true); onChange(''); setError(''); setNotice('');
    try {
      const invitation = normalizeRoomInvitation(await source());
      onChange(invitation);
      setNotice('QR read. Check the room and colors below, then connect.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not read this QR. Try a clearer photo or paste the invitation link.'); }
    finally { inFlight.current = false; setReading(false); onBusyChange(false); }
  }
  function image(file?: File) {
    if (file) void read(async () => (await import('../roomQrImage')).readRoomQrImage(file));
  }
  return <section className="room-invitation-input" aria-label="Scan or import room invitation"
    onDragOver={event => { if (event.dataTransfer.types.includes('Files')) event.preventDefault(); }}
    onDrop={event => { if (event.dataTransfer.files.length) { event.preventDefault(); image(event.dataTransfer.files[0]); } }}
    onPaste={event => { const file = Array.from(event.clipboardData.files).find(file => file.type.startsWith('image/')); if (file) { event.preventDefault(); image(file); } }}>
    <p>Point <strong>this device’s camera</strong> at the robot’s room QR. No phone or document handoff needed.</p>
    <div className="room-invitation-actions">
      <button type="button" className="primary" disabled={disabled || reading} onClick={() => void read(async () => (await import('../senseScanner')).scanSenseRoomUrl())}>Scan room QR</button>
      <button type="button" className="ghost" disabled={disabled || reading} onClick={() => fileInput.current?.click()}>Choose QR photo</button>
    </div>
    <input ref={fileInput} type="file" accept="image/*" hidden disabled={disabled || reading} aria-label="Choose a QR photo or screenshot" onChange={event => { image(event.target.files?.[0]); event.target.value = ''; }} />
    <label htmlFor={id}>Room invitation link</label>
    <input id={id} type="url" autoComplete="off" inputMode="url" placeholder="Scan a QR or paste its Lichess invitation" value={value} disabled={disabled || reading} onChange={event => { onChange(event.target.value); setError(''); setNotice(''); }} />
    <p className="fine-print">You can also paste or drop a QR screenshot here. Images are read on this device.</p>
    {reading && <p role="status">Reading the room QR…</p>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="inline-error" role="alert">{error}</p>}
  </section>;
}
