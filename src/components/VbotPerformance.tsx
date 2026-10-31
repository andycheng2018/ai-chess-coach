import { useEffect, useRef, useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { vbotRequest, vbotReactionLabel, type PerformancePlan } from '../vbotDemo';
import type { VbotCompanionControl } from '../useVbotCompanion';

export function VbotPerformance({ control, onClose }: { control: VbotCompanionControl; onClose: () => void }) {
  const { status, pending, offline, error } = control;
  const android = Capacitor.getPlatform() === 'android';
  const [target, setTarget] = useState(status?.target || '');
  const [dances, setDances] = useState(2);
  const [pace, setPace] = useState('flow');
  const [plan, setPlan] = useState<PerformancePlan | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [localError, setLocalError] = useState('');
  const [space, setSpace] = useState(false);
  const [stop, setStop] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); if (opener?.isConnected) opener.focus(); };
  }, []);
  const show = status?.performance;
  const active = status?.sessionKind === 'performance' && Boolean(status.armed || status.busy);
  const available = status?.performanceApiVersion === 1;
  const locked = pending || previewing || active;
  useEffect(() => { if (status?.target) setTarget(status.target); }, [status?.target]);
  useEffect(() => { setPlan(null); setSpace(false); setStop(false); }, [target, dances, pace]);
  async function preview() {
    setPreviewing(true); setLocalError('');
    try { setPlan((await vbotRequest('performance/preview', { target: target.trim(), dances, pace })).performancePreview || null); }
    catch (cause) { setLocalError(cause instanceof Error ? cause.message : 'Could not load the performance preview.'); }
    finally { setPreviewing(false); }
  }
  const visiblePlan = active && show ? show : plan;
  const cue = show?.cues[show.cueIndex];
  return <dialog ref={dialog} className="game-qr-dialog vbot-stage-dialog" aria-labelledby="vbot-stage-title" onCancel={event => { event.preventDefault(); if (!pending) onClose(); }}>
    <div className="modal-header"><h2 id="vbot-stage-title">Dog stage</h2><div className="vbot-actions">
      {active && <button className="vbot-off" disabled={pending} onClick={() => void control.off()}>Stop further cues</button>}
      <button className="ghost" disabled={pending} onClick={onClose} aria-label="Close dog stage">✕</button>
    </div></div>
    <section className="vbot-companion vbot-performance" aria-label="Standalone dog performance">
    <span className="eyebrow">VBOT · HALLOWEEN STAGE</span>
    <h2>Midnight Mischief</h2>
    <p>A curious entrance, a surprise happy bounce, playful audience gestures, then Rock You and an optional encore. No chess game needed.</p>
    {status && !available && <p className="inline-error">Restart the updated coach backend to load Dog stage. On Android, install the latest complete app update.</p>}
    {show && <div className="vbot-notice" role="status">
      <strong>{show.phase === 'completed' ? 'Last show complete' : show.phase === 'stopped' ? 'Show stopped' : show.phase === 'stopping' ? 'Stopping after the current motion' : `${cue?.act || 'Starting'} · ${show.phase}`}</strong>
      <p>{cue?.caption}</p><p>{show.completedCues} / {show.cues.length} cues completed.</p>
      {show.phase === 'resting' && show.phaseEndsAt && <p>Transition · {Math.max(0, Math.ceil((show.phaseEndsAt - Date.now()) / 1000))}s until the next cue. </p>}
      {show.phase === 'rescanning' && <p role="status">Safety rescan {show.rescanCount || 1} · {show.rescanReason || 'Waiting for the robot to settle.'} No next movement until checks pass. You can stop further cues at any time.</p>}
      {show.stopReason && <p className="inline-error">{show.stopReason}</p>}
    </div>}
    {!active && <>
    <label>Dog address<input value={target} disabled={android || locked || Boolean(status?.armed)} onChange={event => setTarget(event.target.value)} placeholder="vbot@your-router-address" autoCapitalize="none" /></label>
    {android && <p className="vbot-footnote">The address comes from Tablet settings. Close this panel and save the new dog address there when changing Wi-Fi.</p>}
    <button className="ghost" disabled={locked || offline || !target.trim() || Boolean(status?.armed || status?.busy)} onClick={() => { setPlan(null); void control.check(target.trim()); }}>Check robot connection · no motion</button>
    {status?.readiness?.target === target.trim() && status.readiness.ready === false && <p className="inline-error">{status.readiness.reason}</p>}
    <p className="vbot-footnote">On a new Wi-Fi network, check the address first, then preview the score. Existing rehearsals transfer only when the trusted robot identity matches.</p>
    <div className="vbot-actions">
      <label>Dance count<select value={dances} disabled={locked} onChange={event => setDances(Number(event.target.value))}>
        <option value={1}>One grand finale</option><option value={2}>Finale + one encore</option><option value={3}>Finale + two encores</option>
      </select></label>
      <label>Breathing room<select value={pace} disabled={locked} onChange={event => setPace(event.target.value)}>
        <option value="flow">Flow · minimal pauses</option><option value="lively">Lively · 0.75 seconds between short cues</option><option value="theatrical">Theatrical · 2 seconds</option><option value="relaxed">Relaxed · 5 seconds</option>
      </select></label>
    </div>
    <p className="vbot-footnote">Flow uses 0.15-second transition beats and 2 seconds after body performances. Every cue still waits for successful completion and fresh idle-state checks. Transient settling triggers safety rescans for up to 30 seconds. A confirmed root dance-precondition refusal can get up to three total attempts, each after fresh checks and a non-motion static probe. Faults or unknown outcomes stop the show. The score ends after the selected encores.</p>
    <button className="ghost" disabled={locked || offline || !available} onClick={() => void preview()}>{previewing ? 'Building score…' : 'Preview the whole score · no motion'}</button>
    </>}
    {visiblePlan && <>
      <p>{visiblePlan.estimatedSeconds ? `Measured motions + rests: about ${Math.ceil(visiblePlan.estimatedSeconds / 60)} minutes. Readiness checks may add time.` : 'Duration awaits measured rehearsals for every cue.'}</p>
      <details open={!active}><summary>Score · {visiblePlan.cues.length} cues</summary><ol className="vbot-score">{visiblePlan.cues.map((item, index) => <li key={index} aria-current={active && show?.cueIndex === index ? 'step' : undefined}>
        <strong>{item.act}</strong> · {vbotReactionLabel(item.preset)}{!item.rehearsed && ' · rehearsal needed'}
        <p>{item.caption}</p><small>{item.durationMs ? `${(item.durationMs / 1000).toFixed(1)}s measured motion + ` : ''}{item.restSeconds}s rest</small>
      </li>)}</ol></details>
      <p className="vbot-footnote">{visiblePlan.note}</p>
      {!visiblePlan.allRehearsed && <p className="inline-error">Live start is blocked until this exact robot has measured, successful rehearsals for: {visiblePlan.missingPresets.map(vbotReactionLabel).join(', ')}.</p>}
    </>}
    {active ? <>
      <button className="vbot-off" disabled={pending} onClick={() => void control.off()}>Stop the show · prevent further cues</button>
      <p className="vbot-footnote">This cancels queued cues and rests. Use the onsite handset Stop for movement already underway.</p>
    </> : <>
      {status?.armed && <p>Turn chess reactions off before starting the standalone show.</p>}
      <label><input type="checkbox" checked={space} disabled={locked} onChange={event => setSpace(event.target.checked)} /> I checked the performance area and the audience is clear of the dog’s moving space.</label>
      <label><input type="checkbox" checked={stop} disabled={locked} onChange={event => setStop(event.target.checked)} /> An onsite operator has the handset Stop ready.</label>
      <button className="primary" disabled={locked || offline || !available || !plan?.allRehearsed || !target.trim() || !space || !stop || Boolean(status?.armed || status?.busy)}
        onClick={() => void control.startPerformance({ target: target.trim(), dances, pace, requestId: crypto.randomUUID().replaceAll('-', ''), confirmSafeWorkspace: space, confirmHandsetStop: stop })}>Check robot & start live performance</button>
    </>}
    {(localError || error) && <p className="inline-error" role="alert">{localError || error}</p>}
    {active && <p className="vbot-footnote">Closing this panel leaves the show running. Open Dog stage again to monitor or stop further cues. Use the handset Stop for current motion.</p>}
  </section></dialog>;
}
