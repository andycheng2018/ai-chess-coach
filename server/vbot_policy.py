"""Deterministic celebration heuristics over validated canonical coach records.

Centipawns are already from the mover's perspective. These thresholds are demo
heuristics, not independent statistical observations or calibrated p-values.
"""
from collections import deque
import math
from statistics import median

GOOD_LABELS = {"good", "excellent", "best", "book"}
SMALL_PRESETS = ("actions/WAVE.json", "atom/look_left.json", "atom/look_right.json")
HEAD_PRESETS = SMALL_PRESETS[1:]
RULES = {"materialGainCp": 200, "singleSwingCp": 200, "trendGainCp": 150,
         "baselineMoves": 5, "recentMoves": 3, "minimumDepth": 12,
         "smallRestSeconds": 10, "danceRestSeconds": 20, "danceIntervalSeconds": 180,
         "minimumDanceClockMs": 120000, "minimumEstimatedGameMs": 600000}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fast_or_unknown(game, color):
    if game.get("timeControlKnown") is not True:
        return True, "Time control is unverified; using brief acknowledgments only."
    clock = game.get("clock")
    if clock is None:
        return False, None
    if not isinstance(clock, dict) or not all(number(clock.get(k)) and clock[k] >= 0 for k in ("initial", "increment")):
        return True, "Clock configuration is unverified; using brief acknowledgments only."
    remaining = game.get("state", {}).get("wtime" if color == "white" else "btime")
    if clock["initial"] + 40 * clock["increment"] < RULES["minimumEstimatedGameMs"]:
        return True, "Fast time control: full dances disabled."
    if not number(remaining) or remaining < RULES["minimumDanceClockMs"]:
        return True, "Less than two minutes or unverified clock: full dances disabled."
    return False, None


def material(board, color):
    import chess
    values = {chess.PAWN:100, chess.KNIGHT:300, chess.BISHOP:300, chess.ROOK:500, chess.QUEEN:900}
    player = color == "white"
    return sum(value * (len(board.pieces(piece, player)) - len(board.pieces(piece, not player)))
               for piece, value in values.items())


class CelebrationPolicy:
    def __init__(self):
        self.points = deque(maxlen=32)
        self.identity = None
        self.last_ply = None
        self.profile = None

    def observe(self, record, game):
        import chess
        identity = (record.get("gameId"), record.get("playerColor"))
        ply = record.get("ply")
        profile = (record.get("engineDiagnostics") or {}).get("profile")
        if identity != self.identity or not isinstance(ply, int) or self.last_ply is None or ply != self.last_ply + 2 or profile != self.profile:
            self.points.clear()
        self.identity, self.last_ply, self.profile = identity, ply, profile
        fast, pace_reason = fast_or_unknown(game, identity[1])
        decision = {"tier":"small", "reason":"Ordinary good move.", "briefOnly":fast, "paceReason":pace_reason}
        if record.get("classification") not in GOOD_LABELS:
            decision = {**decision, "tier":"none", "reason":"Coach did not label this move good."}
        score = record.get("evaluationAfter")
        diagnostics = record.get("engineDiagnostics") or {}
        depth = diagnostics.get("playedSearch", {}).get("depth")
        # Mate scores are synthetic sentinels, never pawn-sized evaluation swings.
        if not number(score) or abs(score) >= 15000 or not number(depth) or depth < RULES["minimumDepth"]:
            self.points.clear()
            return {**decision, "signalStatus":"Evaluation missing, mate-valued, or below depth 12; no full dance."}
        try:
            before = chess.Board(record["fenBefore"])
            after = before.copy(); after.push_uci(record["playedMoveUci"])
            reply = record.get("opponentReplyUci")
            # No expected reply means no claim that an apparent capture survives it.
            net_gain = None
            if reply:
                after.push_uci(reply)
                net_gain = material(after, identity[1]) - material(before, identity[1])
        except (ValueError, KeyError, TypeError):
            self.points.clear()
            return {**decision, "signalStatus":"Material continuation unavailable; no full dance."}
        prior = list(self.points)
        self.points.append({"cp":score, "ply":ply})
        if decision["tier"] == "none":
            return decision
        major = None
        metrics = {"evaluationCp":score, "netMaterialAfterReplyCp":net_gain}
        if net_gain is not None and net_gain >= RULES["materialGainCp"] and score >= -50:
            major = "At least two material points gained after Stockfish's expected reply."
        if len(prior) >= 5:
            baseline_values = [p["cp"] for p in prior[-5:]]
            baseline = median(baseline_values)
            noise = 1.4826 * median(abs(value-baseline) for value in baseline_values)
            gain = score-baseline
            metrics.update(baselineCp=baseline, gainCp=gain, baselineNoiseCp=round(noise, 1))
            if score >= 100 and gain >= max(RULES["singleSwingCp"], 4*noise):
                major = "A strong evaluation improvement over the recent human-turn baseline."
        if len(self.points) >= 8:
            points = list(self.points)[-8:]
            baseline_values = [p["cp"] for p in points[:5]]
            recent = [p["cp"] for p in points[5:]]
            baseline = median(baseline_values)
            noise = 1.4826 * median(abs(value-baseline) for value in baseline_values)
            improvement = median(recent)-baseline
            if (recent[-1] >= 100 and improvement >= max(RULES["trendGainCp"], 4*noise)
                    and min(recent) >= baseline+100 and recent[-1]-recent[0] >= 50
                    and all(b >= a-25 for a,b in zip(recent,recent[1:]))):
                major = "Three human-turn evaluations sustain an improvement over the previous five."
                metrics.update(baselineCp=baseline, recentMedianCp=median(recent), gainCp=improvement,
                               baselineNoiseCp=round(noise,1))
        if major:
            # Consume this moment even if busy/fast/cooling down; never replay a plateau later.
            self.points.clear(); self.points.append({"cp":score,"ply":ply})
            decision.update(tier="major", reason=major)
        return {**decision, "metrics":metrics}
