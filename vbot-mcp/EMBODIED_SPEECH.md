# Embodied speech: Big Head talks and moves in one reply

Status: design, not built. Today voice mode only talks: the prompt says Big Head's body is
"still learning to move from conversations like this one", so joy comes out in words. This note is
the target once motion tools work and each gesture has been rehearsed on the real dog.

## The idea

Instead of describing a motion in words, which the speaker reads aloud:

> WOOF WOOF!!! I'm so glad to be here! *wiggles whole body out of joy* With you in front of me
> *eyes grow wider* I am so happy!

Qwen writes speech with compact gesture tags at the moment each one fits:

> WOOF WOOF!!! I'm so glad to be here! gest<wiggle,2> With you in front of me gest<curious> I am so happy!

The server splits it into speech and gestures, speaks the text, and fires each gesture at its place.
Nobody ever hears a tag.

## Tag format

```
gest<NAME>          default intensity
gest<NAME,N>        N = 1 (small) .. 3 (big); capped per gesture
```

- **Compact**: about 4–6 tokens, so Qwen's reply budget stays on words.
- **Distinctive**: `gest<` never appears in normal speech in English or Chinese, so parsing is a single
  regex: `gest<([a-z_]+)(?:,([1-3]))?>`.
- **Safe to get wrong**: an unknown name, a bad intensity or a broken tag is dropped and logged. It is
  never spoken and never mapped to a guess.
- It stays inside the existing `reply` field of the JSON answer (`REPLY_FORMAT`). Studio shows tags as
  small badges, and the dog only receives the speech parts.

Why not standard tool calls: a tool call ends Qwen's turn, so speech and motion can't be interleaved
mid-sentence, and each call costs a round trip. Inline tags keep one reply with the timing built in.
The same gestures can still be exposed as MCP tools for the dog's own agent (see `qwen-bridge/`).

## Gesture vocabulary

Short, friendly names for Qwen, mapped on the server to vendor presets
(`vbot-lab/docs/resources/body-trajectories.md`, `docs/guides/rcp-presets.md`). Only rehearsed presets
are enabled.

| Tag name | Preset | Status (Nov 8 rehearsal) |
| --- | --- | --- |
| `wiggle` | RELAXED_SWING | passed, 8.7 s |
| `sway` | RHYTHMIC_SWING | passed, 7.2 s |
| `dance` | RHYTHM | passed, 17.6 s (long: end-of-reply only) |
| `butt_wiggle` | TWIST_BUTT | passed, 10.3 s |
| `curious` (head tilt) | CURIOUS | untested |
| `excited` | EXCITED | untested |
| `look_left` / `look_right` | LOOKLEFT / LOOKRIGHT | untested |
| `cheer` | CHEER_L / CHEER_R | untested |
| `high_five` | HIGH_FIVE_L / HIGH_FIVE_R | untested |
| `bark` (body motion) | DOG_BARK | untested |

Never: CONDUCT and HAPPY_BOUNCE_B (both made the dog fall); anything that walks or jumps.

"Expressions" (`eyes grow wider`) have no face display in the vendor docs, so they become head or body
gestures such as `curious` or `look_left`. If a light or display API turns up, add it as its own tag.

## Timing

1. Split the reply into `[speech, gesture, speech, gesture, …]`.
2. Speak a segment, then start the next gesture **without waiting** by default, so the next words play
   while the dog moves. That's how a person talks while gesturing.
3. Gestures marked `wait` in the table (long ones like `dance`) finish before the next segment, and
   are only allowed at the end of a reply.
4. One gesture at a time, so a new tag waits for the current motion. Cap at 2 gestures per reply and a
   cooldown of a few seconds between them.

To check on the dog: whether the speech service can start a new utterance while a motion runs
(`robot_voice.py` `say` op), and how long the gap between segments sounds.

## Safety

- Server-side allowlist: Qwen can only name tags in the table, never preset IDs.
- Dropped silently (speech continues) while chess reactions or a show run (`demo.armed` / `demo.busy`),
  or if the dog's posture isn't ready.
- Any result other than SUCCEEDED stops the remaining gestures in that reply.
- Each new tag is rehearsed alone, with a person next to the dog, before it's enabled. Never in a loop.

## Prompt change when this goes live

Keep the persona; change only what's true:

- Move "move, turn, jump, dance or do tricks" out of `CANNOT_DO` and list the enabled tags in `CAN_DO`.
- Replace "your joy comes out in what you say rather than in moves you describe" with something like:
  "you can also show it with your body using these gestures, at the moments they fit, about one per
  reply".
- Keep walking, following and carrying in `CANNOT_DO` until there is a tool for them.

## Pieces

- `server/vbot_voice.py`: parse tags out of the reply, build the segment list, and update `CAN_DO`.
- Dog link: reuse the chess server's existing preset path (`server/vbot_demo.py`) for gestures and the
  `say` op for speech; no new service on the dog.
- Tests: parser (good, unknown, malformed tags; Chinese text), timing order with a fake dog, and the
  armed/busy and failure stops.
