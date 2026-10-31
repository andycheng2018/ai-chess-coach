import { useEffect, useState, type ReactNode } from 'react';
import { Capacitor } from '@capacitor/core';
import { authenticatedBackendFetch } from '../nativeBackend';
import { standalone, type LocalSettings } from '../standaloneRuntime';

export function StandaloneRuntime({ children }: { children: ReactNode }) {
  const android = Capacitor.getPlatform() === 'android';
  const [ready, setReady] = useState(!android);
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<LocalSettings>({});
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState('');
  const [password, setPassword] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (!android) return;
    let active = true;
    void standalone.boot().then(state => {
      if (!active) return;
      window.__CHESS_BACKEND_URL__ = state.url;
      window.fetch = authenticatedBackendFetch(window.fetch.bind(window), state);
      setSettings(state.settings); setFields({ model: state.settings.model || 'gpt-4.1-mini', botUsername: state.settings.botUsername || '', robotTarget: state.settings.robotTarget || '', robotFingerprint: state.settings.robotFingerprint || '' });
      setOpen(!state.settings.openaiKeyConfigured && !state.settings.botTokenConfigured);
      setReady(true);
    }).catch(cause => { if (active) setError(String(cause?.message || cause)); });
    return () => { active = false; };
  }, [android]);
  function update(name: string, value: string) { setFields(old => ({ ...old, [name]: value })); }
  async function save() {
    setBusy(true); setError(''); setNotice('');
    try {
      const next = await standalone.configure(fields);
      setSettings(next); setFields(old => ({ ...old, openaiKey: '', botToken: '', elevenLabsKey: '' }));
      setNotice('Saved on this tablet. Robot reactions remain off until you explicitly enable them.');
    } catch (cause) { setError(String((cause as Error).message || cause)); }
    finally { setBusy(false); }
  }
  async function publicKey() {
    setBusy(true); setError('');
    try { setKey((await standalone.publicKey()).publicKey); }
    catch (cause) { setError(String((cause as Error).message || cause)); }
    finally { setBusy(false); }
  }
  async function pairDog() {
    setBusy(true); setError('');
    try {
      await standalone.installRobotKey({ password, confirmed });
      setNotice('Tablet public key installed on the trusted dog. Readiness and rehearsal checks still apply before movement.');
    } catch (cause) { setError(String((cause as Error).message || cause)); }
    finally { setPassword(''); setBusy(false); }
  }
  if (!android) return <>{children}</>;
  if (!ready) return <div className="tablet-connection-backdrop"><section className="card tablet-connection-card"><h1>Starting Chess Buddy on this tablet…</h1><p>Loading the local chess engine and coaching backend.</p>{error && <><p role="alert">{error}</p><button className="primary" onClick={() => window.location.reload()}>Try again</button></>}</section></div>;
  return <>
    {children}
    {!open && <button className="tablet-connection-button ghost" onClick={() => setOpen(true)}>Tablet settings</button>}
    {open && <div className="tablet-connection-backdrop"><section className="card tablet-connection-card" role="dialog" aria-modal="true" aria-labelledby="standalone-title">
      <span className="eyebrow">CHESS BUDDY · STANDALONE</span><h1 id="standalone-title">Everything runs from this tablet</h1>
      <p>Stockfish and the coaching backend run locally. Lichess and Luna need Internet. VBOT connects directly over Wi-Fi; SenseRobot uses its Lichess room.</p>
      <form onSubmit={event => { event.preventDefault(); void save(); }}>
        <label>OpenAI API key {settings.openaiKeyConfigured && '· saved'}<input type="password" autoComplete="off" value={fields.openaiKey || ''} onChange={e => update('openaiKey', e.target.value)} placeholder="Leave blank to keep the saved key"/></label>
        <label>Luna model<input value={fields.model || ''} onChange={e => update('model', e.target.value)}/></label>
        <label>Lichess bot username<input autoCapitalize="none" value={fields.botUsername || ''} onChange={e => update('botUsername', e.target.value)}/></label>
        <label>Lichess bot token {settings.botTokenConfigured && '· saved'}<input type="password" autoComplete="off" value={fields.botToken || ''} onChange={e => update('botToken', e.target.value)} placeholder="Token for your BOT account; student signs in separately"/></label>
        <details><summary>VBOT direct connection</summary>
          <label>Dog address<input autoCapitalize="none" value={fields.robotTarget || ''} onChange={e => update('robotTarget', e.target.value)} placeholder="vbot@192.168.0.170"/></label>
          <label>Verified dog SSH fingerprint<input autoCapitalize="none" value={fields.robotFingerprint || ''} onChange={e => update('robotFingerprint', e.target.value)} placeholder="SHA256:…"/></label>
          <label>Import this dog's existing rehearsal profile<input type="file" accept=".json,application/json" onChange={async e => { const file = e.target.files?.[0]; if (!file) return; if (file.size > 16384) { setError('Profile is too large.'); return; } try { const text = await file.text(); const profile = JSON.parse(text); update('robotProfile', text); if (profile.hostKeyFingerprint) update('robotFingerprint', profile.hostKeyFingerprint); } catch { setError('Choose a valid robot verification JSON file.'); } }}/></label>
          <p className="fine-print">Save these settings before pairing. The imported profile contains rehearsal evidence, not an SSH private key. New presets require supervised verification.</p>
        </details>
        <details><summary>Optional ElevenLabs voice</summary><label>ElevenLabs key {settings.elevenLabsKeyConfigured && '· saved'}<input type="password" autoComplete="off" value={fields.elevenLabsKey || ''} onChange={e => update('elevenLabsKey', e.target.value)}/></label><label>Voice ID<input value={fields.voiceId || ''} onChange={e => update('voiceId', e.target.value)}/></label></details>
        <button className="primary" disabled={busy}>{busy ? 'Working…' : 'Save tablet settings'}</button>
      </form>
      <details><summary>Pair the tablet's own SSH key with VBOT</summary>
        <p>This tablet generates its own key. You can add its public key to your dog's vbot account yourself, or use the one-time password method below. The password is not saved.</p>
        <button className="ghost" disabled={busy} onClick={() => void publicKey()}>Show tablet public key</button>{key && <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{key}</pre>}
        <label>One-time dog SSH password<input type="password" autoComplete="off" value={password} onChange={e => setPassword(e.target.value)}/></label>
        <label><span><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/> I verified the fingerprint and authorize installing this tablet's public key on my dog.</span></label>
        <button className="ghost" disabled={busy || !password || !confirmed} onClick={() => void pairDog()}>Install tablet public key on dog</button>
      </details>
      {notice && <p role="status">{notice}</p>}{error && <p className="inline-error" role="alert">{error}</p>}
      <p className="fine-print">Keys are stored with Android Keystore encryption. Keep this app running during games. Turn robot reactions off before changing settings. The ongoing notification can stop the local backend.</p>
      <button className="ghost" disabled={busy} onClick={() => setOpen(false)}>Continue to Chess Buddy</button>
    </section></div>}
  </>;
}
