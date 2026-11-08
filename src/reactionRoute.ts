export type ReactionRoute = 'cloud' | 'local';
const ROUTE_KEY = 'chessbuddy.reaction-route.v1';

export function selectedReactionRoute(): ReactionRoute {
  try { return localStorage.getItem(ROUTE_KEY) === 'local' ? 'local' : 'cloud'; }
  catch { return 'cloud'; }
}

export function saveReactionRoute(route: ReactionRoute): void {
  localStorage.setItem(ROUTE_KEY, route);
}

/** The coach record and robot controller must belong to the same backend. */
export function reactionRouteMatches(route: ReactionRoute, backend: string): boolean {
  try {
    const url = new URL(backend);
    const host = url.hostname.toLowerCase();
    const local = host === 'localhost' || host === '127.0.0.1' || host === '[::1]'
      || host.endsWith('.local') || /^10\./.test(host) || /^192\.168\./.test(host)
      || /^172\.(1[6-9]|2\d|3[01])\./.test(host);
    return route === 'cloud' ? url.protocol === 'https:' && !local : local;
  } catch { return false; }
}
