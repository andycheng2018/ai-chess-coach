/**
 * Lets LocalFaceTransport talk to the controller inside the APK through the app's
 * plugin. The adapter's rules stay in one place, including "a lost submit is unknown".
 */
export type BackendCall = (request: { path: string; body: string }) => Promise<{ status: number; body: unknown }>;

export const NATIVE_CONTROLLER_DOWN = 'The app’s controller isn’t answering. Close and reopen the app, then connect again.';

function aborted(signal: AbortSignal | null | undefined): Promise<never> {
  return new Promise((_resolve, reject) => {
    if (!signal) return;
    if (signal.aborted) reject(new Error('aborted'));
    else signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
  });
}

export function nativeFetcher(call: BackendCall) {
  return async (input: string, init?: RequestInit): Promise<Response> => {
    const path = input.split('/').pop() ?? '';
    const body = typeof init?.body === 'string' ? init.body : '';
    const reply = await Promise.race([call({ path, body }), aborted(init?.signal)]);
    return { ok: reply.status >= 200 && reply.status < 300, status: reply.status, json: async () => reply.body } as Response;
  };
}
