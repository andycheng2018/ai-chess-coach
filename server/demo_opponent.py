"""Deliberately generous, legal moves for an explicit unrated demo opponent.

This is an authored teaching behavior, not an Elo-calibrated engine level.
It never changes the board or submits moves itself.
"""
import random
import chess

VALUES = {chess.PAWN:100, chess.KNIGHT:300, chess.BISHOP:300, chess.ROOK:500, chess.QUEEN:900, chess.KING:0}


def offered_capture(board):
    """Best legal queen/rook capture, net of the strongest immediate recapture."""
    best = 0
    for move in list(board.legal_moves):
        victim = board.piece_at(move.to_square)
        if not victim or victim.piece_type not in {chess.QUEEN, chess.ROOK}:
            continue
        attacker = board.piece_at(move.from_square)
        board.push(move)
        recaptured = any(reply.to_square == move.to_square and board.is_capture(reply)
                         for reply in board.legal_moves)
        gain = VALUES[victim.piece_type] - (VALUES[attacker.piece_type] if recaptured else 0)
        board.pop()
        if gain >= 200:
            best = max(best, gain)
    return best


def choose_demo_move(board):
    """Offer major pieces when possible; otherwise open/bring out the queen."""
    legal = list(board.legal_moves)
    if not legal:
        raise ValueError("No legal move available.")
    ranked = []
    for move in legal:
        piece = board.piece_at(move.from_square)
        victim = board.piece_at(move.to_square)
        board.push(move)
        # Avoid ending the lesson with a mate or draw if another move exists.
        terminal = board.is_game_over()
        gift = offered_capture(board)
        board.pop()
        score = -100000 if terminal else gift * 100
        if victim:
            score -= VALUES[victim.piece_type] * 2
        if piece.piece_type == chess.QUEEN:
            # Bring the queen toward human pieces instead of retreating forever.
            targets = list(board.pieces(chess.PAWN, not board.turn) |
                           board.pieces(chess.KNIGHT, not board.turn) |
                           board.pieces(chess.BISHOP, not board.turn))
            distance = min((chess.square_distance(move.to_square, s) for s in targets), default=4)
            score += 100 - distance * 15
        # A quiet central pawn push opens the queen's diagonal from startpos.
        if piece.piece_type == chess.PAWN and chess.square_file(move.from_square) in {3,4}:
            score += 50 + abs(move.to_square-move.from_square)
        ranked.append((score, move))
    best = max(score for score, _ in ranked)
    return random.choice([move for score, move in ranked if score == best])
