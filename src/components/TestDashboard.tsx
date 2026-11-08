import { useRef, useState } from 'react';
import { askQwenToSpeak, isCloudBackend, runDiagnostic, sayOnDog, type DiagnosticName, type DiagnosticReport, type DiagnosticStatus } from '../diagnostics';

const CARDS: { name: DiagnosticName; title: string; description: string }[] = [
  { name: 'backend', title: 'Cloud backend', description: 'This device → chess server' },
  { name: 'vbot', title: 'VBOT link', description: 'Chess server → the dog' },
  { name: 'qwen', title: 'Qwen endpoint', description: 'Chess server → Qwen model' },
  { name: 'mcp', title: 'MCP bridge', description: 'qwen_ask tool and the dog’s agent' },
];
const STATUS_TEXT: Record<DiagnosticStatus, string> = { pass: 'Working', warn: 'Needs a look', fail: 'Failed', skip: 'Skipped' };
const STEP_ICON: Record<DiagnosticStatus, string> = { pass: '✓', warn: '!', fail: '✕', skip: '–' };

function formatLatency(ms: number | null | undefined) {
  if (ms == null) return '';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function backendUrl() {
  return window.__CHESS_BACKEND_URL__ || import.meta.env.VITE_BOT_CONTROL_URL || 'http://127.0.0.1:8765';
}

export function TestDashboard({ onClose, onPair }: { onClose: () => void; onPair: () => void }) {
  const [reports, setReports] = useState<Partial<Record<DiagnosticName, DiagnosticReport>>>({});
  const [running, setRunning] = useState<Partial<Record<DiagnosticName, boolean>>>({});
  const [finishedAt, setFinishedAt] = useState<Partial<Record<DiagnosticName, Date>>>({});
  const [runningAll, setRunningAll] = useState(false);
  const inFlight = useRef(new Set<DiagnosticName>());
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [speech, setSpeech] = useState<'idle' | 'asking' | 'ready' | 'saying' | 'said'>('idle');
  const [speechError, setSpeechError] = useState('');
  const url = backendUrl();
  const cloud = isCloudBackend(url);

  async function ask() {
    setSpeech('asking'); setSpeechError(''); setAnswer('');
    try { setAnswer(await askQwenToSpeak(question.trim(), url)); setSpeech('ready'); }
    catch (cause) { setSpeechError((cause as Error).message); setSpeech('idle'); }
  }
  async function say() {
    setSpeech('saying'); setSpeechError('');
    try { await sayOnDog(answer, url); setSpeech('said'); }
    catch (cause) { setSpeechError((cause as Error).message); setSpeech('ready'); }
  }

  async function run(name: DiagnosticName) {
    if (inFlight.current.has(name)) return;
    inFlight.current.add(name);
    setRunning(old => ({ ...old, [name]: true }));
    const report = await runDiagnostic(name, url);
    inFlight.current.delete(name);
    setReports(old => ({ ...old, [name]: report }));
    setFinishedAt(old => ({ ...old, [name]: new Date() }));
    setRunning(old => ({ ...old, [name]: false }));
  }
  // One at a time, so the MCP test's Qwen call can't inflate the Qwen timing.
  async function runAll() {
    setRunningAll(true);
    for (const card of CARDS) await run(card.name);
    setRunningAll(false);
  }

  return <div className="tablet-connection-backdrop" role="dialog" aria-modal="true" aria-labelledby="test-dashboard-title">
    <div className="test-dashboard">
      <header className="test-dashboard-header">
        <div>
          <span className="eyebrow">CHESS BUDDY · DIAGNOSTICS</span>
          <h1 id="test-dashboard-title">Test Dashboard</h1>
          <p className="test-dashboard-target">
            Testing <strong>{new URL(url).host}</strong>
            <span className={`test-badge ${cloud ? 'pass' : 'warn'}`}>{cloud ? 'Cloud' : 'Local'}</span>
          </p>
        </div>
        <div className="test-dashboard-actions">
          <button className="primary" disabled={runningAll} onClick={() => void runAll()}>{runningAll ? 'Running…' : 'Run all tests'}</button>
          <button className="ghost" onClick={onClose}>Close</button>
        </div>
      </header>
      {!cloud && <p className="test-dashboard-note">This app is using a local server, so these tests won’t show the cloud. <button className="test-link" onClick={onPair}>Pair with the cloud server</button> to test it.</p>}
      <div className="test-card-grid">
        {CARDS.map(card => {
          const report = reports[card.name]; const busy = !!running[card.name];
          return <section className="card test-card" key={card.name} aria-busy={busy}>
            <div className="test-card-top">
              <div><h2>{card.title}</h2><p className="fine-print">{card.description}</p></div>
              <span className={`test-badge ${busy ? 'running' : report?.status || 'idle'}`} role="status">{busy ? 'Testing…' : report ? STATUS_TEXT[report.status] : 'Not run'}</span>
            </div>
            {report ? <>
              <p className="test-card-summary">{report.summary}</p>
              {report.steps.length > 0 && <ul className="test-steps">
                {report.steps.map(step => <li key={step.label} className={step.status}>
                  <span className="test-step-icon" aria-hidden="true">{STEP_ICON[step.status]}</span>
                  <div><strong>{step.label}</strong>{step.detail !== report.summary && <span>{step.detail}</span>}</div>
                  <time>{formatLatency(step.latencyMs)}</time>
                </li>)}
              </ul>}
            </> : <p className="fine-print test-card-empty">{busy ? 'Waiting for a reply…' : 'No result yet.'}</p>}
            <div className="test-card-footer">
              <span className="fine-print">{report && !busy ? `${formatLatency(report.latencyMs)} · ${finishedAt[card.name]?.toLocaleTimeString()}` : ''}</span>
              <button className="ghost" disabled={busy} onClick={() => void run(card.name)}>{report ? 'Run again' : 'Run'}</button>
            </div>
          </section>;
        })}
      </div>
      <section className="card test-speech" aria-labelledby="test-speech-title">
        <h2 id="test-speech-title">Make the dog talk</h2>
        <p className="fine-print">Qwen answers here first. Then the dog says exactly those words in its own voice, without its onboard model.</p>
        <form onSubmit={event => { event.preventDefault(); if (question.trim() && speech !== 'asking' && speech !== 'saying') void ask(); }}>
          <label htmlFor="test-speech-question">Question for Qwen</label>
          <div className="test-speech-row">
            <input id="test-speech-question" maxLength={1000} value={question} onChange={event => setQuestion(event.target.value)} placeholder="Why do dogs wag their tails?" autoComplete="off" />
            <button className="primary" disabled={!question.trim() || speech === 'asking' || speech === 'saying'}>{speech === 'asking' ? 'Asking…' : 'Ask Qwen'}</button>
          </div>
        </form>
        {answer && <div className="test-speech-answer">
          <span className="eyebrow">QWEN SAYS</span>
          <p>{answer}</p>
          <div className="test-speech-actions">
            <button className="primary" disabled={speech === 'saying' || speech === 'asking'} onClick={() => void say()}>{speech === 'saying' ? 'Sending…' : speech === 'said' ? 'Say it again' : 'Say it on the dog'}</button>
            {speech === 'said' && <span role="status" className="test-badge pass">Sent to the dog</span>}
          </div>
        </div>}
        {speechError && <p className="inline-error" role="alert">{speechError}</p>}
      </section>
      <p className="fine-print test-dashboard-foot">The status tests only read information and ask Qwen one short question. Nothing here moves the dog.</p>
    </div>
  </div>;
}
