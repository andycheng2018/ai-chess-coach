/**
 * Installed-capability catalog. Face assets and body presets are separate kinds
 * even when they share a name: `068_ROCKYOU` is a screen animation and
 * `actions/ROCKYOU.json` is a dance. Nothing here contacts a robot.
 */
export type CapabilityKind = 'face' | 'head' | 'body' | 'wait' | 'speech' | 'navigation';

/**
 * - exercised: played on the real dog and confirmed onsite (Nov 1 2026, display only).
 * - rehearsal-record: an earlier measured rehearsal exists for one dog. It does not
 *   transfer to another dog or firmware, and it is not permission to move.
 * - device-listed: the connected dog reports this asset; it has not been watched.
 * - documented: appears in SDK docs; not confirmed on any dog.
 * - unavailable: placeholder with no verified backend.
 */
export type Verification = 'exercised' | 'rehearsal-record' | 'device-listed' | 'documented' | 'unavailable';

export type CatalogEntry = {
  id: string;
  kind: CapabilityKind;
  label: string;
  /** Installed resource spelling, preserved exactly. */
  resource: string;
  category: string;
  verification: Verification;
  durationMs: number | null;
  durationBasis: 'requested' | 'measured-rehearsal' | 'unknown';
  assetId?: number;
  preset?: string;
  note?: string;
};

export const FACE_DEFAULT_MS = 4500;

/** IDs played successfully on the dog and confirmed by the onsite operator. */
export const EXERCISED_FACE_IDS: readonly number[] = [86, 76, 79, 71, 70, 81];

/**
 * Never playable: the SDK says not to simulate charging, safety or fault
 * indications, and these are diagnostics. The dog-side helper enforces this too.
 */
export const RESTRICTED_FACE_IDS: readonly number[] = [66, 67, 80, 89, 90, 91, 92, 93, 95];
const RESTRICTED_NAME = /charge|eye_test|test_ever/i;

const FACE_GROUPS: Record<string, string> = {
  Feelings: '003_sad_10s 004_happy_10s 005_happy_30s 006_confound_3s 007_timid_15s 008_courage_15s 009_courage_30s 010_fear_10s 011_angry_10s 012_dizzy_30s 013_surprise_20s 014_angry 016_courage 017_dizzy 018_fear_courage 019_happy 021_shy 023_sleepy 024_sweaty 028_wronged 057_droway 058_SAD 059_DOUBT 060_WORRY 061_SIGN 062_SAD_B 063_REGRET 064_ASTONISHED 065_SAD 070_EXCITED 071_PROUD 072_HAPPINES 073_TRUST 074_LOVE 075_DISPLEASED 076_NERVOUS 077_FEAR 078_DISLIKE 079_SURPRISE 081_CHEER 086_THINK 097_THINK 105_YAWN',
  'Eyes & idle': '000_blink_once 001_wink_10s 002_listen_10s 015_blink_many 020_listen_64f_v01 022_sleeping 025_talk_160f_v01 026_wakeup_84f_v01 027_wink 044_sound_waves 052_long_talk 055_power_on_wake_up 083_LISTEN_LINE 084_SEARCH 085_LOOK_UP 087_LOADING 096_LISTEN 100_LOW_BREATHE 101_LOOK_AROUND_B 103_REST 115_LIFE_LOOP_GROUP_A 116_LIFE_LOOP_GROUP_B',
  'Greetings & social': '033_love_u 034_please 042_bow 043_shake_head 046_wink_pose 048_say_hi 051_high_five 056_take_photos 088_WAVE 094_SELF_INTROUDCTION 104_LICK_HAND',
  'Party & music': '031_happy_birthday 037_ticking 040_rhythmic_swing 041_relaxed_swing 045_michael_jackson 047_new_year 053_fireworks 054_spring_festival 068_ROCKYOU 069_ROCKYOU 082_RHYTHM 099_Saxophone 111_DRUM 112_GUITAR 113_VIOLIN 114_PIANO',
  'Animals & silly': '029_dog_barking 030_pee 032_wolf_howl 035_scratching_head_right 036_scratching_head_left 038_rub_leg_right 039_rub_leg_left 049_pushup 050_lunge_forward 102_PLANE 106_PIG 107_DOG 108_HEN 109_CAT 110_ELEPHANT',
};

/** Names mirror vbot-demo/robot_action.py PRESETS. Durations are one dog's rehearsal record. */
const MOTION_PRESETS: readonly (readonly [string, CapabilityKind, string, string, number | null])[] = [
  ['atom/look_left.json', 'head', 'Look left', 'Head gestures', 1763],
  ['atom/look_right.json', 'head', 'Look right', 'Head gestures', 3005],
  ['atom/look_forward.json', 'head', 'Look forward', 'Head gestures', 1058],
  ['atom/look_up.json', 'head', 'Look up', 'Head gestures', 2018],
  ['atom/look_down.json', 'head', 'Look down', 'Head gestures', 847],
  ['actions/WAVE.json', 'body', 'Wave', 'Gestures', 7588],
  ['actions/SAYYES.json', 'body', 'Approving yes', 'Gestures', 5774],
  ['actions/SHAKEHAND.json', 'body', 'Handshake', 'Gestures', 8152],
  ['actions/SHAKEHAND_L.json', 'body', 'Left handshake', 'Gestures', 8864],
  ['actions/HIGH_FIVE_R.json', 'body', 'Right high-five', 'Gestures', 8529],
  ['actions/HIGH_FIVE_L.json', 'body', 'Left high-five', 'Gestures', 8102],
  ['actions/GRIEVANCE.json', 'body', 'Sad reaction', 'Gestures', 11070],
  ['actions/HAPPY_LITTLE_JUMP.json', 'body', 'Small happy jump', 'Jumps', 5765],
  ['actions/HAPPY_JUMP.json', 'body', 'Happy jump', 'Jumps', 7326],
  ['actions/JUMP_IN_PLACE.json', 'body', 'Jump in place', 'Jumps', 7324],
  ['actions/ROCKYOU.json', 'body', 'Rock You dance', 'Dances', 40451],
  ['actions/CHEER_R.json', 'body', 'Cheer', 'Dances', null],
];

export const MOTION_PRESET_NAMES: ReadonlySet<string> = new Set(MOTION_PRESETS.map(row => row[0]));

const SMALL_WORDS = /_(\d+s|\d+f.*|v\d+)$/i;

export function faceLabel(resource: string): string {
  let name = resource.replace(/^\d+_/, '');
  while (SMALL_WORDS.test(name)) name = name.replace(SMALL_WORDS, '');
  return name.split('_').filter(Boolean)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()).join(' ');
}

export function isRestrictedFace(assetId: number, resource = ''): boolean {
  return RESTRICTED_FACE_IDS.includes(assetId) || RESTRICTED_NAME.test(resource);
}

function faceEntry(resource: string, category: string, verification: Verification): CatalogEntry {
  const assetId = Number(resource.slice(0, 3));
  return {
    id: `face:${assetId}`, kind: 'face', label: faceLabel(resource), resource, category,
    verification: EXERCISED_FACE_IDS.includes(assetId) ? 'exercised' : verification,
    durationMs: FACE_DEFAULT_MS, durationBasis: 'requested', assetId,
    note: 'Screen animation only. It does not move the head or body.',
  };
}

function buildCatalog(): CatalogEntry[] {
  const faces = Object.entries(FACE_GROUPS).flatMap(([category, names]) =>
    names.split(' ').map(name => faceEntry(name, category, 'documented')));
  faces.sort((a, b) => Number(EXERCISED_FACE_IDS.includes(b.assetId!)) - Number(EXERCISED_FACE_IDS.includes(a.assetId!)));
  const motions = MOTION_PRESETS.map(([preset, kind, label, category, durationMs]): CatalogEntry => ({
    id: `${kind}:${preset}`, kind, label, resource: preset, category, preset, durationMs,
    verification: durationMs === null ? 'documented' : 'rehearsal-record',
    durationBasis: durationMs === null ? 'unknown' : 'measured-rehearsal',
    note: durationMs === null
      ? 'No measured rehearsal on record.'
      : 'Physical motion. Duration comes from an earlier rehearsal and must be re-verified on this dog.',
  }));
  return [
    ...faces, ...motions,
    { id: 'wait', kind: 'wait', label: 'Wait', resource: 'wait', category: 'Timing', verification: 'exercised',
      durationMs: 1000, durationBasis: 'requested', note: 'A pause in the controller. Sends nothing to the dog.' },
    { id: 'speech', kind: 'speech', label: 'Speak', resource: 'speech', category: 'Speech', verification: 'unavailable',
      durationMs: null, durationBasis: 'unknown', note: 'No verified speech backend yet.' },
    { id: 'navigation', kind: 'navigation', label: 'Walk to a point', resource: 'navigation', category: 'Navigation', verification: 'unavailable',
      durationMs: null, durationBasis: 'unknown', note: 'The /function/following schema exists, but no live provider has been demonstrated.' },
  ];
}

export const CATALOG: readonly CatalogEntry[] = buildCatalog();

/** Add assets the connected dog reports (it listed 139; the SDK docs list 116). */
export function mergeDeviceFaces(catalog: readonly CatalogEntry[], names: readonly string[] | null): CatalogEntry[] {
  if (!names) return [...catalog];
  const reported = new Map<number, string>();
  for (const name of names) {
    const match = /^(\d{3})_/.exec(name);
    if (match) reported.set(Number(match[1]), name);
  }
  const merged = catalog.map(entry => {
    if (entry.kind !== 'face' || entry.assetId === undefined || !reported.has(entry.assetId)) return entry;
    const resource = reported.get(entry.assetId)!;
    return { ...entry, resource, verification: entry.verification === 'exercised' ? entry.verification : 'device-listed' as const };
  });
  const known = new Set(merged.map(entry => entry.assetId));
  const extras = [...reported].filter(([id, name]) => !known.has(id) && !isRestrictedFace(id, name))
    .sort(([a], [b]) => a - b).map(([, name]) => faceEntry(name, 'More on this dog', 'device-listed'));
  return [...merged, ...extras];
}

export const VERIFICATION_LABEL: Record<Verification, string> = {
  exercised: 'Confirmed on the dog',
  'rehearsal-record': 'Earlier rehearsal on record',
  'device-listed': 'Listed by this dog',
  documented: 'Documented only',
  unavailable: 'Not available',
};

export const KIND_LABEL: Record<CapabilityKind, string> = {
  face: 'Face', head: 'Head', body: 'Body', wait: 'Wait', speech: 'Speech', navigation: 'Navigation',
};
