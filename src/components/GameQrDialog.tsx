import { useEffect, useRef, useState } from 'react';
import { gameQrLink } from '../gameQr';

type Props = { gameId: string; playerColor: 'white' | 'black'; username?: string; ended?: boolean; onJoinRoom: () => void; onClose: () => void };

export function GameQrDialog({ gameId, playerColor, username, ended, onJoinRoom, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [side, setSide] = useState(playerColor);
  const [qr, setQr] = useState({ url: '', image: '', error: '' });
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const url = gameQrLink(gameId, side);
  useEffect(() => {
    const node = dialog.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); if (opener?.isConnected) opener.focus(); };
  }, []);
  useEffect(() => {
    let active = true;
    setCopied(false); setCopyError('');
    void import('qrcode').then(module => module.default.toDataURL(url, {
      errorCorrectionLevel: 'M', margin: 4, width: 640,
      color: { dark: '#000000ff', light: '#ffffffff' },
    })).then(image => { if (active) setQr({ url, image, error: '' }); })
      .catch(() => { if (active) setQr({ url, image: '', error: 'Could not generate the QR. You can still open or copy the link.' }); });
    return () => { active = false; };
  }, [url]);
  async function copy() {
    try { await navigator.clipboard.writeText(url); setCopied(true); }
    catch { setCopied(false); setCopyError('Copy unavailable. Select the game link above to copy it manually.'); }
  }
  return <dialog ref={dialog} className="game-qr-dialog" aria-labelledby="game-qr-title" onCancel={onClose}>
    <div className="modal-header"><div><span className="modal-kicker">{ended ? 'FINISHED MATCH' : 'CURRENT MATCH'} · <span className="game-qr-id">{gameId}</span></span><h2 id="game-qr-title">Game QR code</h2></div>
      <button type="button" className="ghost" onClick={onClose} aria-label="Close game QR">✕</button></div>
    {ended && <p className="muted">This match has finished. Its QR opens the game record.</p>}
    <p>{username || 'You'} play <strong>{playerColor}</strong>. This QR shares the existing game in a browser.</p>
    <p className="sense-notice">This is a game-viewing link, not a SenseRobot room invitation. To join a new room, create it on SenseRobot and bring its invitation here. If physical moves already match this game, a QR or error screen alone does not mean you need to rejoin.</p>
    <button type="button" className="ghost wide" onClick={onJoinRoom}>Join a SenseRobot room link</button>
    <label htmlFor="game-qr-side">Board view</label>
    <select id="game-qr-side" value={side} onChange={e => setSide(e.target.value as 'white' | 'black')}>
      <option value={playerColor}>My view · {playerColor}</option>
      <option value={playerColor === 'white' ? 'black' : 'white'}>Opposite view · {playerColor === 'white' ? 'black' : 'white'}</option>
    </select>
    <div className="game-qr-image">{qr.url === url && qr.image
      ? <img src={qr.image} alt={`QR for game ${gameId}, ${side} side`} width="640" height="640" />
      : <p role="status">{qr.url === url && qr.error ? qr.error : 'Generating QR…'}</p>}</div>
    <a className="game-qr-link" href={url} target="_blank" rel="noreferrer">{url}</a>
    <div className="game-qr-actions"><button className="ghost" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy game link'}</button>
      {qr.url === url && qr.image && <a className="ghost" href={qr.image} download={`lichess-${gameId}-${side}.png`}>Save QR image</a>}</div>
    {copyError && <p role="status">{copyError}</p>}
    <p className="muted">Opens this existing match; it does not create a room or change either player’s color. The QR is generated locally.</p>
  </dialog>;
}
