import { useEffect, useState } from 'react';
import { vbotEventText } from '../vbotDemo';
import type { VbotCompanionControl } from '../useVbotCompanion';

type Props = { control: VbotCompanionControl; gameId: string | null; canArm: boolean; ended: boolean; blockedReason?: string };

export function VbotCompanion({ control, gameId, canArm, ended, blockedReason }: Props) {
  const { status, pending, offline, error } = control;
  const [target, setTarget] = useState(status?.target || '');
  const [space, setSpace] = useState(false);
  const [stop, setStop] = useState(false);
  useEffect(() => { if (!target && status?.target) setTarget(status.target); }, [status?.target, target]);
  useEffect(() => { setSpace(false); setStop(false); }, [gameId, target]);
  const nativeAvailable = status?.companionApiVersion === 1;
  const linked = Boolean(status?.armed && status.gameId === gameId);
  const ready = Boolean(status?.readinessFresh && status.readiness?.ready && status.readiness.target === target.trim());
  const locked = pending || Boolean(status?.busy) || offline || !nativeAvailable;
  const badge = offline ? 'Unavailable' : status?.busy ? 'Reacting' : status?.armed && !linked ? 'Other match' : !linked ? 'Off'
    : status?.mode === 'rehearsal' ? 'Preview only' : (status?.cooldownRemaining || 0) > 0 ? 'Resting' : 'Live';
  const requests = new Set(status?.events.filter(e => e.gameId === gameId).map(e => e.requestId).filter(Boolean));
  const events = status?.events.filter(e => e.gameId === gameId || (e.requestId && requests.has(e.requestId))).slice(0, 5) || [];
  const attention = events.find(e => ['not_ready', 'rejected', 'unknown'].includes(e.status));

  return <section id="vbot-companion" className="vbot-companion" aria-label="VBOT companion">
    <div className="vbot-header"><div><span className="vbot-kicker">ROBOT COMPANION</span><h3>VBOT reacts with you</h3></div>
      <span className={`vbot-badge ${linked ? 'on' : ''}`} role="status">{badge}</span></div>
    <p className="vbot-copy">Good moves earn a brief gesture. Major gains can earn Rock You. Blunders get a sad reaction.</p>
    <p className="vbot-footnote">{status?.sadPresetVerified
      ? 'Sad reaction rehearsed. Body performances are spaced three minutes apart and disabled in fast games or time trouble.'
      : 'Sad reaction awaits a supervised rehearsal on this robot. Live sad reactions stay off until then.'}</p>
    <p className="vbot-match">{ended ? 'Match finished · reactions off' : gameId ? `Follows this match · ${gameId}` : 'Start or resume a training match to link VBOT.'}</p>
    {status?.armed && !linked && <p className="vbot-notice">VBOT is enabled for match {status.gameId}. Turn that session off before connecting this match.</p>}
    {linked && <p className="vbot-notice">{status?.mode === 'rehearsal' ? 'Previewing new coach verdicts. The robot will stay still.'
      : status?.busy ? 'A reaction is in progress, including its readiness checks. New moves are not queued.'
      : (status?.cooldownRemaining || 0) > 0 ? `Resting for ${Math.ceil(status?.cooldownRemaining || 0)}s before another reaction.`
      : 'Listening for the next eligible coach verdict. Earlier moves are not replayed.'}</p>}
    {!linked && attention && <p className="vbot-notice" role="status">Paused: {attention.reason || attention.message} Inspect VBOT, then check again before enabling reactions.</p>}
    {!canArm && !ended && blockedReason && <p className="vbot-notice">{blockedReason}</p>}
    {error && <p className="inline-error" role="alert">{error}</p>}
    {status && !nativeAvailable && <p className="vbot-notice">Restart the local coach server to enable integrated VBOT controls.</p>}
    {status?.armed || status?.busy ? <div className="vbot-actions"><button className="vbot-off" disabled={pending} onClick={() => void control.off()}>Turn reactions off</button></div>
      : <>
        <details className="vbot-settings"><summary>Robot connection</summary>
          <label htmlFor="vbot-target">Robot SSH address</label>
          <input id="vbot-target" value={target} onChange={e => setTarget(e.target.value)} disabled={locked} placeholder="vbot@192.168.0.170" autoComplete="off" />
          <small>Uses this Mac’s existing SSH key. No passwords are stored here.</small>
        </details>
        <div className="vbot-actions"><button className="ghost" disabled={locked || !target.trim()} onClick={() => void control.check(target.trim())}>{pending ? 'Checking…' : 'Check robot'}</button>
          <button className="ghost" disabled={locked || !canArm} onClick={() => void control.connect('rehearsal', target.trim(), false)}>Preview without motion</button></div>
        {status?.readiness?.target === target.trim() && <p className={`vbot-readiness ${ready ? 'ready' : ''}`} role="status">{ready ? 'Robot passed readiness. Confirm the space below to enable motion.'
          : status.readiness.ready ? 'Readiness check expired. Check again before enabling motion.' : status.readiness.reason || 'Robot is not ready.'}</p>}
        {!ended && gameId && <div className="vbot-live-setup">
          <label><input type="checkbox" checked={space} onChange={e => setSpace(e.target.checked)} disabled={locked} />VBOT is standing on clear level ground, unplugged, with room to move.</label>
          <label><input type="checkbox" checked={stop} onChange={e => setStop(e.target.checked)} disabled={locked} />I’m supervising, people/pets are clear, and the app’s Stop is ready.</label>
          <button className="primary" disabled={locked || !canArm || !ready || !space || !stop} onClick={() => void control.connect('live', target.trim(), space && stop)}>Enable live reactions</button>
        </div>}
      </>}
    <p className="vbot-footnote">Finishing or switching matches turns reactions off. Turning reactions off prevents new actions; use VBOT’s app Stop to stop movement already underway.</p>
    {events.length > 0 && <details className="vbot-history" open={Boolean(attention && !linked)}><summary>Recent reactions</summary>
      <ol>{events.map((e, i) => <li key={`${e.time}-${e.status}-${i}`}><time>{new Date(e.time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}</time>
        <span>{e.playedMove && <strong>{e.playedMove} · </strong>}{vbotEventText(e)}</span></li>)}</ol>
    </details>}
  </section>;
}
