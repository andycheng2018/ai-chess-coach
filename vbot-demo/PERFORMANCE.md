# Dog stage: Midnight Mischief

Open **Dog stage → Preview & perform** beside Capture Practice on the home screen.
No Lichess game, synthetic chess move, cloud model call, or voice service is needed
for this standalone performance. The existing VBOT controller, SSH identity, robot
helper, motion dispatcher, and readiness checks are reused.

The authored sequence is entrance → curiosity → theatrical disappointment →
playfulness → Rock You → optional encores → curtain call. The default is two
dances in Flow pace: 0.15-second transition beats after short cues and two seconds
after body performances. The first live run of the older pacing took 6:58: 139
seconds of motion, 115 seconds of scripted rests, and about 164 seconds of check/
connection overhead. Flow removes most scripted dead air. A concurrent telemetry experiment passed
a read-only device check but did not reduce measured latency (7.8 seconds versus
7.5 seconds for the existing check), so it was not deployed. Connection/helper
startup overhead remains; revised whole-show timing is not yet measured. Captions are operator stage
directions. Speech playback and audience perception are separate integrations.

## Before the party

1. Put the operator device and the dog on the portable router's main network.
   Use the robot's current address. A router's device label or saved lease does
   not prove the device is currently reachable. Verify the existing SSH host key;
   never accept a replacement identity just because an IP changed.
2. On Android, save the current dog address in **Tablet settings** first. The
   tablet must already have its own SSH identity paired with this dog and the
   matching rehearsal profile imported. On Mac, use the existing trusted SSH key.
3. Open Dog stage and choose **Check robot connection · no motion**. On a new
   Mac network, a positive check associates the new address with the already
   trusted robot identity. This can preserve existing rehearsal evidence without
   pretending a different robot was rehearsed. Unmet readiness conditions are shown.
4. Choose **Preview the whole score · no motion**. Inspect every cue, its measured
   duration, breathing room, and the expected total duration. Preview never arms
   the controller or calls the robot. Missing individual rehearsal evidence blocks
   live start; a broad demo approval does not replace measured evidence here.
5. Select 1–3 dances. Flow (default) uses 0.15-second short transitions and
   two seconds after body performances. Lively uses 0.75/3 seconds, Theatrical
   2/5 seconds, and Relaxed 5/20 seconds. No rest follows the final cue.
   These stage beats are separate from the unchanged chess-reaction cooldowns;
   successful completion and fresh idle telemetry still gate each new cue.
6. Confirm the actual performance space and an onsite operator with the handset
   Stop ready. **Check robot & start live performance** performs another fresh
   check and submits one bounded show. Rehearse this complete sequence onsite
   before presenting it to a crowd; individual preset rehearsals do not establish
   the combined sequence's acceptance on a new floor or in a new audience layout.

## During the show

The panel shows the current act, cue, completed cue count, and rest countdown.
The Stop-further-cues control stays in the header while the score scrolls.
Closing the panel leaves the show running; the home-screen Dog stage button
indicates a live show and reopens its controls.

**Stop further cues** cancels upcoming cues and interrupts a waiting rest. It is
not a physical emergency stop: use the onsite handset Stop for current movement.
Every motion still requires the existing provider, fresh telemetry, posture,
battery, host-identity and terminal-outcome checks. A rejection, unknown result,
identity change, or failed postflight ends the remaining score. There is no
automatic replay, recovery dance, or endless loop. No new cue is submitted after
the 15-minute execution window; an in-flight motion still requires the handset
Stop if it must be interrupted. A repeated start-request identity cannot replay it.

Chess reactions and stage performances share one dispatcher. Stop the show before
arming chess reactions. The chess watcher cannot detach an independent stage
session merely because a game ends or changes. Show dances update the same body
performance timestamp used by chess; ordinary chess timing rules are preserved.

## Validation boundary

Offline tests replace robot I/O and cover ordered execution, repeated starts,
stopping during rest/motion, failed or unknown results, host identity changes,
freshness/rehearsal admission, and shared-controller exclusion. Browser preview
uses rehearsal metadata only. Those witnesses do not prove a live, whole-show
robot rehearsal. The robot helper and its preset allowlist do not need modification
for this score, provided the existing helper and rehearsed presets are installed.
