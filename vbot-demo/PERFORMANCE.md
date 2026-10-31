# Dog stage: Midnight Mischief

Open **Dog stage → Preview & perform** beside Capture Practice on the home screen.
No Lichess game, synthetic chess move, cloud model call, or voice service is needed
for this standalone performance. The existing VBOT controller, SSH identity, robot
helper, motion dispatcher, and readiness checks are reused.

The authored sequence is entrance → curiosity → surprise happy bounce →
playfulness → Rock You → optional encores → curtain call. The default is two
dances in Flow pace: 0.15-second transition beats after short cues and two seconds
after body performances. The first live run of the older pacing took 6:58: 139
seconds of motion, 115 seconds of scripted rests, and about 164 seconds of check/
connection overhead. Flow removes most scripted dead air. A concurrent telemetry experiment passed
a read-only device check but did not reduce measured latency (7.8 seconds versus
7.5 seconds for the existing check), so it was not deployed. That experiment was superseded by a show-scoped persistent SSH/SDK session
and continuously subscribed telemetry. On-device read-only checks over that
session returned ready in 8–138 ms after a one-time 5.5-second startup. A three-head-gesture live check then completed every cue with 0.286–0.409 seconds
of request overhead (elapsed time minus the robot-reported motion duration),
plus the authored 0.15-second transition. That measures transport/check overhead,
not an exact visual gap or a complete revised-show rehearsal. Captions are operator stage
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

## Persistent cue session

Install the updated `robot_action.py` helper on the dog before using this version
of Dog stage. It adds `--serve` to the same guarded preset executor; old single
preset commands remain supported. An older helper stops show startup rather than
silently falling back to per-cue reconnects. No vendor service restart is needed.

One SSH connection, SDK node, provider client and telemetry observer remain open
for one show. The local controller still sends just one identified cue at a time;
there is no remote queue. Every cue retains the rehearsal/host checks, provider
schema check, exclusive request record, unresolved-action guard, terminal result,
and postflight checks. A controller lock prevents overlapping helper processes.

The live observer requires the same 2 battery, 2 advancing system, 3 advancing
body and 2 head samples. Every topic's newest sample must be no older than 1.5
seconds and its complete window no older than 3.5 seconds. Postflight body/head
samples must all arrive after the terminal result. Malformed or stale telemetry
refuses another cue. Only the established head-busy/pending settling path waits;
other failed conditions stop immediately. No cached readiness boolean is reused.

The session expires after 15 minutes, 20 commands or 30 seconds waiting for its
next command. EOF/connection loss never triggers reconnect or replay. The current
motion still needs the onsite handset Stop if it must be interrupted. The native
Android bridge uses the existing configured target, private key and pinned host
fingerprint; this adds no listener or pairing permission.

## Rescans and bounded retry

Transient head-busy/pending, standing-idle transitions, or a false static condition
keep the logical cue pending for up to 30 seconds. Each scan reads current live
telemetry; this never repeats a cached readiness decision. Battery, charging,
alarms, system faults, head faults, stale/malformed/incomplete telemetry, provider
mismatch and uncertain task results stop the cue immediately.

Before Rock You, the provider evaluates its exact `is_robot_static == true`
precondition through a separate 1 ms Sleep-only DAG. The probe has no motion node,
no requested resources, `requires_static=false`, and normal prechecks enabled.
It does not prepare/change posture or set a context value. A failed static
predicate is observed again; validation or other probe failures stop the cue.

A motion attempt is repeated only for the recognized root `rockyou_30s` refusal:
ABORTED/HANDLER_ERROR, no motion-duration result, schema version 1, category 7
PRECONDITION_FAILED, `rcp.execution.precondition_failed`, the exact root task name,
and the false-to-true static predicate diagnostic. Nested-node failure markers,
cancellation, timeout, missing replies and generic ABORTED results are excluded.
The cue rescans all conditions and reruns the static probe before resubmitting.
There are at most three movement attempts, within the bounded rescan window.

Each logical cue is reserved durably before probes or movement; every probe and
movement attempt uses its own UUID and durable request record linked to the
logical cue. Only the final logical outcome acknowledges the client. Lost replies
never reconnect or replay a logical cue. The UI shows the pending rescan reason.
**Stop further cues** sends cancellation to a pending rescan; the helper polls
before each movement attempt. Use the handset Stop for already active movement.

## During the show

The panel shows the current act, cue, completed cue count, and rest countdown.
The Stop-further-cues control stays in the header while the score scrolls.
Closing the panel leaves the show running; the home-screen Dog stage button
indicates a live show and reopens its controls.

**Stop further cues** cancels upcoming cues and interrupts a waiting rest. It is
not a physical emergency stop: use the onsite handset Stop for current movement.
Every motion still requires the existing provider, fresh telemetry, posture,
battery, host-identity and terminal-outcome checks. An unrecognized rejection, unknown result, identity change, hard fault, or failed
postflight ends the remaining score. Only the narrow precondition-refusal path
above may resubmit a movement after rescans; there is no replay of uncertain
requests, recovery dance, or endless loop. No new cue is submitted after
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
robot rehearsal. The helper must support the persistent session protocol; the preset allowlist
and motion definitions are unchanged.
