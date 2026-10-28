"""Authored one-move lessons. This is separate from real-game Stockfish verdicts."""
import json
from pathlib import Path
import chess

PRACTICE_ID = "CAPTURE1"
EXERCISES = {e["id"]:e for e in json.loads((Path(__file__).resolve().parents[1] / "src/captureExercises.json").read_text())}

def exercise(exercise_id):
    if exercise_id not in EXERCISES: raise ValueError("Choose a listed capture lesson.")
    return EXERCISES[exercise_id]

def assess_capture(exercise_id, uci):
    lesson=exercise(exercise_id)
    board=chess.Board(lesson['fen'])
    try: move=chess.Move.from_uci(str(uci))
    except ValueError: return {"correct":False,"hint":lesson['hint']}
    if move not in board.legal_moves or move.uci()!=lesson['move']:
        return {"correct":False,"hint":lesson['hint']}
    captured=board.piece_at(move.to_square)
    if not captured or captured.color==board.turn or captured.piece_type not in {chess.QUEEN,chess.ROOK}:
        raise ValueError("This lesson does not contain the required legal big-piece capture.")
    san=board.san(move);board.push(move)
    return {"correct":True,"san":san,"fenAfter":board.fen(),"captured":chess.piece_name(captured.piece_type),
            "points":9 if captured.piece_type==chess.QUEEN else 5}
