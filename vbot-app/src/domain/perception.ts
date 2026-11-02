/**
 * Types for a future "this is my player" feature. Selection, the ephemeral
 * detection track, location and last-seen memory stay separate, because the dog
 * currently reports 2D image boxes with no stable identity and no measured depth.
 * Detection `z=0` is not depth. Nothing here estimates a 3D position.
 */
export type ImageBox = { x: number; y: number; width: number; height: number };

export type Detection = {
  /** Valid only for one continuous track. It isn't a person's identity. */
  trackId: string; box: ImageBox; score: number; observedAt: number;
};

export type PlayerSelection = {
  sessionId: string; selectedAt: number; trackId: string;
  /** Always a host's explicit choice, never nearest-person or biometric matching. */
  chosenBy: 'host';
};

export type WorldEstimate = {
  x: number; y: number; z: number; frameId: string; frameRevision: number; localizationEpoch: number;
  observedAt: number; uncertaintyM: number; provenance: 'measured' | 'estimated';
};

export type PlayerMemory = {
  selection: PlayerSelection;
  lastSeenAt: number | null;
  /** Null until calibrated depth association is a verified milestone. */
  location: WorldEstimate | null;
};

export type TrackingStatus =
  | { state: 'none'; message: string }
  | { state: 'tracking'; message: string; detection: Detection }
  | { state: 'stale' | 'lost'; message: string };

export const TRACK_STALE_MS = 2000;
export const TRACK_LOST_MS = 10000;

/**
 * Follows only the explicitly selected track. If that track disappears it reports
 * so and asks for reselection; it never switches to the next visible person.
 */
export function trackingStatus(selection: PlayerSelection | null, detections: readonly Detection[], now: number): TrackingStatus {
  if (!selection) return { state: 'none', message: 'No player selected. Choose one from the current detections.' };
  const match = detections.find(item => item.trackId === selection.trackId);
  if (!match) return { state: 'lost', message: 'The selected person is no longer tracked. Select them again.' };
  const age = now - match.observedAt;
  if (age > TRACK_LOST_MS) return { state: 'lost', message: 'Tracking was lost. Select the player again.' };
  if (age > TRACK_STALE_MS) return { state: 'stale', message: 'Tracking is stale. Any repositioning would pause here.' };
  return { state: 'tracking', message: 'Tracking in the image. Distance is unknown.', detection: match };
}

/** A new localization epoch or frame revision makes old world coordinates invalid. */
export function usableLocation(location: WorldEstimate | null, frameRevision: number, localizationEpoch: number): WorldEstimate | null {
  if (!location) return null;
  return location.frameRevision === frameRevision && location.localizationEpoch === localizationEpoch ? location : null;
}
