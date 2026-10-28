import { useEffect, useRef, useState } from 'react';
import { vbotEventText, vbotReactionLabel, type ReactionProfile } from '../vbotDemo';
import type { VbotCompanionControl } from '../useVbotCompanion';

type Props = { control: VbotCompanionControl; gameId: string | null; canArm: boolean; ended: boolean; blockedReason?: string; practice?: boolean; demoOpponent?: boolean };

export function VbotCompanion({ control, gameId, canArm, ended, blockedReason, practice = false, demoOpponent = false }: Props) {
  const { status, pending, offline, error } = control;
  const [target, setTarget] = useState(status?.target || '');
  const [networkLabel, setNetworkLabel] = useState('');
  const networkSeen = useRef<string | null>(null);
  const [reactionProfile, setReactionProfile] = useState<ReactionProfile>('balanced');
  const [watchUntil, setWatchUntil] = useState(0);
  const watchProbe = useRef(false);
  const checkRef = useRef(control.check);
  checkRef.current = control.check;
  const [space, setSpace] = useState(false);
  const [stop, setStop] = useState(false);
  useEffect(() => {
    if (!status) return;
    const key = status.network ? status.network.current.id || [status.network.current.subnet || '', status.network.current.gateway || ''].join('|') : 'manual';
    if (networkSeen.current !== key) {
      networkSeen.current = key;
      setTarget(status.target || '');
      setNetworkLabel(status.network?.label || status.network?.current.ssid || '');
      setSpace(false); setStop(false);
    }
  }, [status]);
  useEffect(() => { setSpace(false); setStop(false); }, [gameId, target]);
  // Explicit, bounded read-only monitoring. Never arms or submits a gesture.
  useEffect(() => { setWatchUntil(0); }, [gameId, target, status?.network?.current.id]);
  useEffect(() => {
    if (!watchUntil) return;
    if (status?.armed || status?.busy || status?.readiness?.ready || Date.now() >= watchUntil) {
      setWatchUntil(0); return;
    }
    const timer = window.setInterval(() => {
      if (Date.now() >= watchUntil) { setWatchUntil(0); return; }
      if (document.hidden || watchProbe.current || pending || offline) return;
      watchProbe.current = true;
      void checkRef.current(target.trim()).finally(() => { watchProbe.current = false; });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [watchUntil, status?.armed, status?.busy, status?.readiness?.ready, pending, offline, target]);
  const nativeAvailable = status?.companionApiVersion === 1;
  const linked = Boolean(status?.armed && status.gameId === gameId);
  const ready = Boolean(status?.readinessFresh && status.readiness?.ready && status.readiness.target === target.trim());
  const locked = pending || Boolean(status?.busy) || offline || !nativeAvailable;
  const badge = offline ? 'Unavailable' : status?.busy ? 'Reacting' : status?.finishPending ? status.victoryPending ? 'Victory dance waiting' : 'Confirming result' : status?.armed && !linked ? 'Other match' : !linked ? 'Off'
    : status?.mode === 'rehearsal' ? 'Preview only' : (status?.cooldownRemaining || 0) > 0 ? 'Resting' : 'Live';
  const requests = new Set(status?.events.filter(e => e.gameId === gameId).map(e => e.requestId).filter(Boolean));
  const events = status?.events.filter(e => e.gameId === gameId || (e.requestId && requests.has(e.requestId))).slice(0, 5) || [];
  const attention = events.find(e => ['not_ready', 'rejected', 'unknown'].includes(e.status));

  return <section id="vbot-companion" className="vbot-companion" aria-label="VBOT companion">
    <div className="vbot-header"><div><span className="vbot-kicker">ROBOT COMPANION</span><h3>VBOT reacts with you</h3></div>
      <span className={`vbot-badge ${linked ? 'on' : ''}`} role="status">{badge}</span></div>
    <p className="vbot-copy">{practice ? 'Correct queen and rook captures earn the full Rock You dance when rewards are live and VBOT is ready.' : 'Good moves earn a random brief gesture. Major gains and a confirmed win can earn Rock You. Blunders get a sad reaction.'}</p>
    <details className="vbot-settings"><summary>Demo preflight & connection health</summary>
      <ul className="vbot-preflight">
        {(offline || !nativeAvailable) && <li>Local robot controller is unavailable.</li>}
        {!gameId && <li>No game selected. Start or resume a game.</li>}
        {!canArm && blockedReason && <li>{blockedReason}</li>}
        {!target.trim() && <li>No robot address for this network.</li>}
        {!linked && !ready && <li>{status?.readiness?.target === target.trim() && !status.readiness.ready ? status.readiness.reason || 'Robot is not ready.' : 'Enable includes a fresh robot check.'}</li>}
      </ul>
      <p className="vbot-footnote">Match: {gameId || 'none'} · Robot: {target || 'not selected'} · {linked ? 'session enabled' : 'reactions off'}. Physical board synchronization must be confirmed at SenseRobot.</p>
      {events[0] && <p>Latest event: {vbotEventText(events[0])}</p>}
    </details>
    {!practice && !!status?.smallPresetCandidates?.length && <details className="vbot-settings">
      <summary>Good-move gestures · {status.smallPresets?.length || 0} enabled</summary>
      <p className="vbot-footnote">Random choice each time, with no immediate repeat when another gesture is available. New moves during a reaction or rest are skipped, never queued. Fast games use head gestures only.</p>
      <ul>{status.smallPresetCandidates.map(preset => <li key={preset}>
        {vbotReactionLabel(preset)} · {status.operatorApprovedPresets?.includes(preset) ? 'Demo enabled · not individually rehearsed' : status.smallPresets?.includes(preset) ? 'Rehearsed' : 'Not enabled'}
      </li>)}</ul>
    </details>}
    {!practice && <p className="vbot-footnote">{status?.sadPresetVerified
      ? demoOpponent ? 'Demo capture rewards can repeat after the dance and 20-second rest. Fast games/time trouble still use brief gestures; sad performances keep their three-minute interval.' : 'Sad reaction rehearsed. During play, body performances are spaced three minutes apart and disabled in fast games or time trouble.'
      : 'Sad reaction awaits a supervised rehearsal on this robot. Live sad reactions stay off until then.'}</p>}
    <p className="vbot-match">{practice ? 'Capture Practice rewards · separate from your live game' : status?.finishPending ? 'Finishing this match · victory celebration can be cancelled below' : ended ? 'Match finished · reactions off' : gameId ? `Follows this match · ${gameId}` : 'Start or resume a training match to link VBOT.'}</p>
    {status?.armed && !linked && <p className="vbot-notice">VBOT is enabled for match {status.gameId}. Turn that session off before connecting this match.</p>}
    {linked && <p className="vbot-notice">{status?.mode === 'rehearsal' ? 'Previewing new coach verdicts. The robot will stay still.'
      : status?.victoryPending ? 'You won! Waiting for the current reaction and rest before Rock You. Keep supervising; turn reactions off to cancel.'
      : status?.finishPending && !status?.busy ? 'Confirming the final Lichess result. No new move reactions will start.'
      : status?.busy ? 'A reaction is in progress, including its readiness checks. New moves are not queued.'
      : (status?.cooldownRemaining || 0) > 0 ? `Resting for ${Math.ceil(status?.cooldownRemaining || 0)}s before another reaction.`
      : 'Listening for the next eligible coach verdict. Earlier moves are not replayed.'}</p>}
    {!linked && attention && <p className="vbot-notice" role="status">Paused: {attention.reason || attention.message} Inspect VBOT, then check again before enabling reactions.</p>}
    {status?.network && <div className="vbot-network-summary" role="status">
      <strong>Mac network: {status.network.label || status.network.current.ssid || status.network.current.subnet || 'unavailable'}</strong>
      {status.network.current.localIp && <span> · Mac {status.network.current.localIp}</span>}
      <p>{status.network.error || status.network.current.message || 'Network recognized from local settings.'}</p>
      <p>{status.network.suggestedTarget ? `Remembered robot: ${status.network.suggestedTarget}. Check before enabling.` : 'No robot address remembered here yet. Enter it under Robot connection, then save or check it.'}</p>
    </div>}
    {!canArm && !ended && blockedReason && <p className="vbot-notice">{blockedReason}</p>}
    {error && <p className="inline-error" role="alert">{error}</p>}
    {status && !nativeAvailable && <p className="vbot-notice">Restart the local coach server to enable integrated VBOT controls.</p>}
    {status?.armed || status?.busy ? <div className="vbot-actions"><button className="vbot-off" disabled={pending} onClick={() => void control.off()}>{status?.victoryPending ? 'Cancel victory dance & turn off' : 'Turn reactions off'}</button></div>
      : <>
        <details className="vbot-settings"><summary>Robot connection · remembered networks</summary>
          {!!status?.network?.addresses.length && <label>Saved addresses on this network
            <select aria-label="Saved VBOT address" value={status.network.addresses.some(a => a.target === target) ? target : ''}
              disabled={locked} onChange={e => { if (e.target.value) setTarget(e.target.value); }}>
              <option value="">Enter an address manually</option>
              {status.network.addresses.map(a => <option key={a.target} value={a.target}>{a.target} · {a.lastVerifiedAt ? 'SSH verified' : 'needs check'}</option>)}
            </select>
          </label>}
          <label htmlFor="vbot-target">Robot SSH address</label>
          <input id="vbot-target" value={target} onChange={e => setTarget(e.target.value)} disabled={locked} placeholder="vbot@192.168.0.170" autoComplete="off" />
          <small>Uses this Mac’s existing SSH key. No passwords are stored here.</small>
          {status?.network && <>
            <label htmlFor="vbot-network-label">Network label</label>
            <input id="vbot-network-label" placeholder="Home / Rich’s hotspot" value={networkLabel} onChange={e => setNetworkLabel(e.target.value)} disabled={locked} maxLength={80} />
            <button className="ghost" disabled={locked || !target.trim() || !status.network.current.id || Boolean(status.network.error)}
              onClick={() => { if (status.network?.current.id) void control.remember(target.trim(), networkLabel, status.network.current.id); }}>Remember for this network</button>
            <p className="vbot-footnote">A successful Check robot also remembers the address. Changing networks turns live reactions off; saved addresses never enable movement automatically.</p>
            {!!status.network.profiles.length && <ul>{status.network.profiles.map(p => <li key={p.id}>{p.label}: {p.targets.join(', ')}</li>)}</ul>}
          </>}
        </details>
        <label className="vbot-profile">Reaction style
          <select value={reactionProfile} disabled={locked} onChange={e => setReactionProfile(e.target.value as ReactionProfile)}>
            <option value="quiet">Quiet · head gestures</option><option value="balanced">Balanced · varied gestures</option><option value="showmanship">Showmanship · shorter brief-gesture rest</option>
          </select>
        </label>
        <p className="vbot-footnote">Showmanship uses a 3-second brief-gesture rest instead of 5. Dance intervals, clock restrictions, rehearsals and robot safety checks remain in force. Wins and capture lessons retain their full celebration.</p>
        <div className="vbot-actions"><button className="ghost" disabled={locked || !target.trim()} onClick={() => void control.check(target.trim())}>{pending ? 'Checking…' : 'Check robot'}</button>
          <button className="ghost" disabled={locked || !canArm} onClick={() => void control.connect('rehearsal', target.trim(), false, reactionProfile)}>Preview without motion</button></div>
        {status?.readiness?.target === target.trim() && <p className={`vbot-readiness ${ready ? 'ready' : ''}`} role="status">{ready ? 'Robot passed readiness. Enabling live reactions includes a fresh check.'
          : status.readiness.ready ? 'Readiness will be checked automatically when you enable reactions.' : status.readiness.reason || 'Robot is not ready.'}</p>}
        {watchUntil > 0 ? <button className="ghost" onClick={() => setWatchUntil(0)}>Stop readiness monitoring</button>
          : <button className="ghost" disabled={locked || !target.trim() || ready} onClick={() => setWatchUntil(Date.now() + 30000)}>Watch readiness for 30 seconds</button>}
        <p className="vbot-footnote">Read-only checks every 5 seconds, for at most 30 seconds. Stops when ready; never enables movement or replays a blocked reaction.</p>
        {!ended && gameId && <div className="vbot-live-setup">
          <label><input type="checkbox" checked={space} onChange={e => setSpace(e.target.checked)} disabled={locked} />VBOT is standing on clear level ground, unplugged, with room to move.</label>
          <label><input type="checkbox" checked={stop} onChange={e => setStop(e.target.checked)} disabled={locked} />I’m supervising, people/pets are clear, and the app’s Stop is ready.</label>
          <button className="primary" disabled={locked || !canArm || !target.trim() || !space || !stop} onClick={() => void control.connect('live', target.trim(), space && stop, reactionProfile)}>{pending ? 'Checking & enabling…' : practice ? 'Check & enable dance rewards' : 'Check & enable live reactions'}</button>
        </div>}
      </>}
    <p className="vbot-footnote">Connection-check expiry does not turn off live reactions. A confirmed win can play Rock You once after any current reaction/rest, before reactions turn off. Switching matches cancels a waiting victory dance. Turning reactions off prevents new actions; use VBOT’s app Stop to stop movement already underway.</p>
    {events.length > 0 && <details className="vbot-history" open={Boolean(attention && !linked)}><summary>Recent reactions</summary>
      <ol>{events.map((e, i) => <li key={`${e.time}-${e.status}-${i}`}><time>{new Date(e.time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}</time>
        <span>{e.playedMove && <strong>{e.playedMove} · </strong>}{vbotEventText(e)}{e.classification && <small className="vbot-event-detail">Coach: {e.classification}</small>}{e.paceReason && <small className="vbot-event-detail">{e.paceReason}</small>}{e.status === 'requested' && e.reason && <small className="vbot-event-detail">Why: {e.reason}</small>}</span></li>)}</ol>
    </details>}
  </section>;
}
