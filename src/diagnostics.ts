export type DiagnosticStatus = 'pass' | 'warn' | 'fail' | 'skip';
export type DiagnosticName = 'backend' | 'mcp' | 'qwen' | 'vbot';
export type DiagnosticStep = { label: string; status: DiagnosticStatus; detail: string; latencyMs: number | null };
export type DiagnosticReport = { check: DiagnosticName; status: DiagnosticStatus; summary: string; latencyMs: number; steps: DiagnosticStep[] };

/** Longer than the server's own limits, so its explanation arrives before ours fires. */
export const DIAGNOSTIC_TIMEOUT_MS: Record<DiagnosticName, number> = { backend: 15000, mcp: 140000, qwen: 110000, vbot: 60000 };

export function isCloudBackend(url: string): boolean {
  try {
    const { protocol, hostname } = new URL(url);
    return protocol === 'https:' && hostname !== 'localhost' && !hostname.endsWith('.local');
  } catch { return false; }
}

function failure(check: DiagnosticName, summary: string, latencyMs = 0): DiagnosticReport {
  return { check, status: 'fail', summary, latencyMs, steps: [] };
}

/** Always resolves to a report: a failed connection is a result here, not an exception. */
export async function runDiagnostic(check: DiagnosticName, backendUrl: string, request: typeof fetch = fetch): Promise<DiagnosticReport> {
  const started = performance.now();
  const elapsed = () => Math.round(performance.now() - started);
  let response: Response;
  try {
    response = await request(`${backendUrl}/api/diagnostics/${check}`, { signal: AbortSignal.timeout(DIAGNOSTIC_TIMEOUT_MS[check]), cache: 'no-store' });
  } catch (cause) {
    const timedOut = (cause as Error)?.name === 'TimeoutError';
    return failure(check, timedOut ? 'The server did not finish this check in time.' : `Could not reach the server at ${backendUrl}.`, elapsed());
  }
  if (response.status === 403) return failure(check, 'The server refused this device. Pair it again with the current pairing key.', elapsed());
  if (response.status === 404) return failure(check, 'This server is running an older version without these tests.', elapsed());
  if (!response.ok) return failure(check, `The server answered HTTP ${response.status}.`, elapsed());
  try {
    const report = await response.json() as DiagnosticReport;
    // The backend card reports what the user feels: the round trip from this device.
    return check === 'backend' ? { ...report, latencyMs: elapsed() } : report;
  } catch { return failure(check, 'The server sent an unreadable reply.', elapsed()); }
}

async function postJson<T>(url: string, body: object, timeoutMs: number, request: typeof fetch): Promise<T> {
  let response: Response;
  try {
    response = await request(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(timeoutMs) });
  } catch (cause) {
    throw new Error((cause as Error)?.name === 'TimeoutError' ? 'The server took too long to answer.' : 'Could not reach the server.');
  }
  const data = await response.json().catch(() => ({})) as T & { message?: string };
  if (response.status === 404) throw new Error('This server is running an older version without this feature.');
  if (response.status === 403) throw new Error('The server refused this device. Pair it again with the current pairing key.');
  if (!response.ok) throw new Error(data.message || `The server answered HTTP ${response.status}.`);
  return data;
}

export async function askQwenToSpeak(question: string, backendUrl: string, request: typeof fetch = fetch): Promise<string> {
  return (await postJson<{ answer: string }>(`${backendUrl}/api/vbot/say/ask`, { question }, 95000, request)).answer;
}

/** Resolves when the dog accepts the words; a refusal throws with the dog's reason. */
export async function sayOnDog(text: string, backendUrl: string, request: typeof fetch = fetch): Promise<void> {
  const result = await postJson<{ ok: boolean; reason?: string }>(`${backendUrl}/api/vbot/say/speak`, { text }, 50000, request);
  if (!result.ok) throw new Error(result.reason || 'The dog did not speak.');
}
