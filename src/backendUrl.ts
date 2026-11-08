/** Read at call time: on Android the address is only known after the app boots. */
export function backendUrl(): string {
  return window.__CHESS_BACKEND_URL__ || import.meta.env.VITE_BOT_CONTROL_URL || 'http://127.0.0.1:8765';
}
