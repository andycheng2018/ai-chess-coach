import { CONTROL_URL, type CoachResult } from './coach';

/** Fire once from accepted live coaching; never block the chess/voice pipeline. */
export async function notifyVbotMove(
  result: CoachResult, gameId: string, playerColor: 'white' | 'black',
): Promise<void> {
  if (!gameId || result.gameId !== gameId || !result.recordId || result.playerColor !== playerColor) return;
  try {
    const response = await fetch(`${CONTROL_URL}/api/vbot/celebrate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recordId: result.recordId, gameId, playerColor }),
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) console.warn('VBOT demo unavailable; chess continues normally.');
  } catch {
    // The demo dashboard shows accepted events. Do not retry a physical command.
    console.warn('VBOT demo unavailable; chess continues normally.');
  }
}
