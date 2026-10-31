"""Authored stage score. Planning never contacts the robot or fabricates chess events."""
from vbot_policy import SAD_PRESET, MAX_SMALL_DURATION_MS

PACE = {'flow': .15, 'lively': .75, 'theatrical': 2, 'relaxed': 5}
BODY_REST = {'flow': 2, 'lively': 3, 'theatrical': 5, 'relaxed': 20}
DANCE = 'actions/ROCKYOU.json'


def performance_plan(payload, verified):
    dances = payload.get('dances', 2)
    pace = payload.get('pace', 'flow')
    if type(dances) is not int or dances not in {1, 2, 3} or pace not in PACE:
        raise ValueError('Choose 1–3 dances and a listed performance pace.')
    score = [
        ('Entrance', 'Hello, Halloween crowd.', 'actions/WAVE.json'),
        ('Curious', 'Did something move over there?', 'atom/look_left.json'),
        ('Curious', 'And over here?', 'atom/look_right.json'),
        ('Curious', 'I am definitely a very brave dog.', 'atom/look_up.json'),
        ('Dramatic', 'A small moment of theatrical despair.', SAD_PRESET),
        ('Dramatic', 'Wait. I have a plan.', 'atom/look_forward.json'),
        ('Playful', 'Yes. We are going to be friends.', 'actions/SAYYES.json'),
        ('Playful', 'A little happy bounce.', 'actions/HAPPY_LITTLE_JUMP.json'),
        ('Playful', 'High-five, from a comfortable distance.', 'actions/HIGH_FIVE_R.json'),
        ('Finale', 'Time for the dance floor.', DANCE),
    ]
    for encore in range(1, dances):
        score += [('Encore', f'One more? Dance {encore + 1} of {dances}.', 'actions/WAVE.json'),
                  ('Encore', 'Back to the dance floor.', DANCE)]
    score += [('Curtain call', 'Thank you. You have been a wonderful crowd.', 'actions/WAVE.json'),
              ('Curtain call', 'And… scene.', 'atom/look_forward.json')]
    cues, missing, estimate = [], [], 0
    for index, (act, caption, preset) in enumerate(score):
        entry = verified(preset)
        duration = (entry or {}).get('durationMs')
        maximum = 120000 if preset in {DANCE, SAD_PRESET} else MAX_SMALL_DURATION_MS
        ready = (isinstance(duration, (int, float)) and not isinstance(duration, bool)
                 and 0 < duration <= maximum)
        if not ready and preset not in missing:
            missing.append(preset)
        # Stage beats are independent of the chess-reaction cooldown policy.
        # Confirmed completion and fresh idle telemetry still gate every cue.
        rest = BODY_REST[pace] if preset in {DANCE, SAD_PRESET} else PACE[pace]
        if index == len(score) - 1:
            rest = 0
        cues.append({'act': act, 'caption': caption, 'preset': preset, 'restSeconds': rest,
                     'durationMs': duration if ready else None, 'rehearsed': ready})
        estimate += (duration / 1000 if ready else 0) + rest
    return {'title': 'Midnight Mischief', 'dances': dances, 'pace': pace, 'cues': cues,
            'missingPresets': missing, 'allRehearsed': not missing,
            'estimatedSeconds': round(estimate) if not missing else None,
            'note': 'Timing uses measured rehearsals plus breathing room. Fresh readiness checks can add time. Captions are stage directions, not automatic speech or vision detections.'}
