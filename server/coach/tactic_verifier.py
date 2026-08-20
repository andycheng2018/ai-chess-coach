from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import chess


PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}


THEME_PRIORITY = (
    "Mate in One",
    "Mate in Two",
    "Mate in Three or More",
    "Forced Mate",
    "Back-Rank Mate",
    "Smothered Mate",
    "Support Mate",
    "Mating Net",
    "Underpromotion",
    "Promotion",
    "En Passant",
    "Stalemate",
    "Double Check",
    "Discovered Check",
    "Fork / Double Attack",
    "Pin",
    "Skewer",
    "Discovered Attack",
    "X-Ray Attack",
    "Removal of the Defender",
    "Deflection",
    "Decoy",
    "Overloading",
    "Interference",
    "Clearance Sacrifice",
    "Clearance",
    "Queen Sacrifice",
    "Exchange Sacrifice",
    "Sacrifice",
    "Zwischenzug",
    "Desperado",
    "Windmill",
    "Perpetual Check",
    "Hanging Piece",
    "Trapped Piece",
    "Back-Rank Weakness",
    "Attack on f7 / f2",
    "Attacking the Castled King",
    "Vulnerable King",
    "Simplification",
    "Zugzwang",
    "Endgame Tactic",
    "Defense",
    "King Safety",
    "Passed Pawn",
    "Opposition",
    "Open File",
    "Weak Square",
    "Checkmate Pattern",
)


@dataclass(frozen=True)
class ThemeEvidence:
    theme: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def prioritize_theme_evidence(
    evidence: Iterable[ThemeEvidence],
    limit: int = 3,
) -> list[ThemeEvidence]:
    by_theme = {
        item.theme: item
        for item in evidence
    }
    return [
        by_theme[theme]
        for theme in THEME_PRIORITY
        if theme in by_theme
    ][:max(0, limit)]


def _piece_label(
    board: chess.Board,
    square: chess.Square,
) -> str:
    piece = board.piece_at(square)
    name = (
        chess.piece_name(piece.piece_type)
        if piece is not None
        else "piece"
    )
    return f"{name} on {chess.square_name(square)}"


def _material(board: chess.Board, color: chess.Color) -> int:
    return sum(
        PIECE_VALUES[piece.piece_type]
        for piece in board.piece_map().values()
        if piece.color == color
        and piece.piece_type != chess.KING
    )


def _non_pawn_material(board: chess.Board) -> int:
    return sum(
        PIECE_VALUES[piece.piece_type]
        for piece in board.piece_map().values()
        if piece.piece_type not in {
            chess.KING,
            chess.PAWN,
        }
    )


def _legal_line(
    board: chess.Board,
    moves: Iterable[chess.Move],
    max_plies: int = 12,
) -> list[chess.Move]:
    temp = board.copy(stack=False)
    legal: list[chess.Move] = []

    for move in list(moves)[:max_plies]:
        if move not in temp.legal_moves:
            break
        legal.append(move)
        temp.push(move)

    return legal


def _ray_step(
    from_square: chess.Square,
    to_square: chess.Square,
) -> tuple[int, int] | None:
    file_delta = chess.square_file(to_square) - chess.square_file(from_square)
    rank_delta = chess.square_rank(to_square) - chess.square_rank(from_square)

    if file_delta == 0 and rank_delta:
        return (0, 1 if rank_delta > 0 else -1)
    if rank_delta == 0 and file_delta:
        return (1 if file_delta > 0 else -1, 0)
    if abs(file_delta) == abs(rank_delta) and file_delta:
        return (
            1 if file_delta > 0 else -1,
            1 if rank_delta > 0 else -1,
        )
    return None


def _ray_squares(
    from_square: chess.Square,
    file_step: int,
    rank_step: int,
) -> list[chess.Square]:
    file_index = chess.square_file(from_square) + file_step
    rank_index = chess.square_rank(from_square) + rank_step
    squares: list[chess.Square] = []

    while 0 <= file_index < 8 and 0 <= rank_index < 8:
        squares.append(chess.square(file_index, rank_index))
        file_index += file_step
        rank_index += rank_step

    return squares


def _between(
    first: chess.Square,
    second: chess.Square,
) -> list[chess.Square]:
    step = _ray_step(first, second)
    if step is None:
        return []

    result: list[chess.Square] = []
    for square in _ray_squares(first, *step):
        if square == second:
            return result
        result.append(square)
    return []


def _slider_matches_step(
    piece: chess.Piece,
    step: tuple[int, int],
) -> bool:
    diagonal = step[0] != 0 and step[1] != 0
    if piece.piece_type == chess.QUEEN:
        return True
    if piece.piece_type == chess.BISHOP:
        return diagonal
    if piece.piece_type == chess.ROOK:
        return not diagonal
    return False


def _attacked_enemy_targets(
    board: chess.Board,
    attacker_square: chess.Square,
    enemy: chess.Color,
) -> list[chess.Square]:
    targets = [
        square
        for square in board.attacks(attacker_square)
        if (
            (piece := board.piece_at(square)) is not None
            and piece.color == enemy
        )
    ]

    def target_priority(
        square: chess.Square,
    ) -> tuple[int, chess.Square]:
        piece = board.piece_at(square)
        value = (
            PIECE_VALUES[piece.piece_type]
            if piece is not None
            else 0
        )
        return (-value, square)

    return sorted(
        targets,
        key=target_priority,
    )


def verified_move_facts(
    board: chess.Board,
    move: chess.Move,
) -> dict[str, object]:
    """Return compact legal-board facts safe for prompts and spoken copy."""
    if move not in board.legal_moves:
        return {}

    mover = board.turn
    moved_piece = board.piece_at(move.from_square)
    captured_piece = board.piece_at(move.to_square)
    if board.is_en_passant(move):
        captured_square = (
            move.to_square - 8
            if mover == chess.WHITE
            else move.to_square + 8
        )
        captured_piece = board.piece_at(captured_square)

    san = board.san(move)
    after = board.copy(stack=False)
    after.push(move)
    targets = _attacked_enemy_targets(
        after,
        move.to_square,
        not mover,
    )

    return {
        "move": san,
        "move_uci": move.uci(),
        "moved_piece": (
            chess.piece_name(moved_piece.piece_type)
            if moved_piece is not None
            else ""
        ),
        "from": chess.square_name(move.from_square),
        "to": chess.square_name(move.to_square),
        "is_capture": board.is_capture(move),
        "captured_piece": (
            chess.piece_name(captured_piece.piece_type)
            if captured_piece is not None
            else ""
        ),
        "gives_check": after.is_check(),
        "is_checkmate": after.is_checkmate(),
        "attacked_enemy_pieces": [
            _piece_label(after, square)
            for square in targets
        ],
    }


def _new_slider_attacks(
    before: chess.Board,
    after: chess.Board,
    mover: chess.Color,
    moved_to: chess.Square,
) -> list[tuple[chess.Square, chess.Square]]:
    result: list[tuple[chess.Square, chess.Square]] = []

    for slider_square, slider in after.piece_map().items():
        if (
            slider.color != mover
            or slider.piece_type not in {
                chess.BISHOP,
                chess.ROOK,
                chess.QUEEN,
            }
            or slider_square == moved_to
        ):
            continue

        for target_square in after.attacks(slider_square):
            target = after.piece_at(target_square)
            if target is None or target.color == mover:
                continue
            if target_square not in before.attacks(slider_square):
                result.append((slider_square, target_square))

    return result


def _skewer_and_xray(
    board: chess.Board,
    attacker_square: chess.Square,
    enemy: chess.Color,
) -> tuple[tuple[chess.Square, chess.Square] | None, tuple[chess.Square, chess.Square] | None]:
    attacker = board.piece_at(attacker_square)
    if (
        attacker is None
        or attacker.piece_type not in {
            chess.BISHOP,
            chess.ROOK,
            chess.QUEEN,
        }
    ):
        return None, None

    skewer = None
    xray = None
    directions = (
        (1, 0), (-1, 0), (0, 1), (0, -1),
        (1, 1), (1, -1), (-1, 1), (-1, -1),
    )

    for direction in directions:
        if not _slider_matches_step(attacker, direction):
            continue

        occupied = [
            square
            for square in _ray_squares(attacker_square, *direction)
            if board.piece_at(square) is not None
        ]
        if len(occupied) < 2:
            continue

        front, behind = occupied[:2]
        front_piece = board.piece_at(front)
        behind_piece = board.piece_at(behind)
        if front_piece is None or behind_piece is None:
            continue

        if front_piece.color == enemy and behind_piece.color == enemy:
            xray = xray or (front, behind)
            if (
                PIECE_VALUES[front_piece.piece_type]
                > PIECE_VALUES[behind_piece.piece_type]
            ):
                skewer = skewer or (front, behind)

        elif behind_piece.color == enemy:
            xray = xray or (front, behind)

    return skewer, xray


def _newly_trapped_target(
    after: chess.Board,
    targets: list[chess.Square],
    mover: chess.Color,
) -> chess.Square | None:
    enemy = not mover
    if after.turn != enemy:
        return None

    for target_square in targets:
        target = after.piece_at(target_square)
        if (
            target is None
            or target.color != enemy
            or target.piece_type in {
                chess.KING,
                chess.PAWN,
            }
            or after.is_pinned(
                enemy,
                target_square,
            )
        ):
            continue

        escapes: list[chess.Move] = []
        for candidate in after.legal_moves:
            if candidate.from_square != target_square:
                continue
            escaped = after.copy(stack=False)
            escaped.push(candidate)
            if not escaped.is_attacked_by(
                mover,
                candidate.to_square,
            ):
                escapes.append(candidate)
        if not escapes:
            return target_square

    return None


def _is_back_rank_mate(
    after: chess.Board,
    move: chess.Move,
    mover: chess.Color,
) -> bool:
    if not after.is_checkmate():
        return False

    enemy_king = after.king(not mover)
    checker = after.piece_at(move.to_square)
    if enemy_king is None or checker is None:
        return False
    if checker.piece_type not in {chess.ROOK, chess.QUEEN}:
        return False

    king_rank = chess.square_rank(enemy_king)
    return king_rank in {0, 7}


def _is_smothered_mate(
    after: chess.Board,
    move: chess.Move,
    mover: chess.Color,
) -> bool:
    checker = after.piece_at(move.to_square)
    enemy_king = after.king(not mover)
    if (
        not after.is_checkmate()
        or checker is None
        or checker.piece_type != chess.KNIGHT
        or enemy_king is None
    ):
        return False

    for adjacent in chess.SquareSet(
        chess.BB_KING_ATTACKS[enemy_king]
    ):
        occupant = after.piece_at(adjacent)
        if occupant is None or occupant.color == mover:
            return False
    return True


def _is_supported_mate(
    after: chess.Board,
    move: chess.Move,
    mover: chess.Color,
) -> bool:
    return (
        after.is_checkmate()
        and bool(
            after.attackers(
                mover,
                move.to_square,
            )
        )
    )


def _is_castled_king_square(square: chess.Square | None) -> bool:
    return square in {
        chess.C1,
        chess.G1,
        chess.C8,
        chess.G8,
    }


def _king_zone(square: chess.Square | None) -> set[chess.Square]:
    if square is None:
        return set()
    return {
        square,
        *chess.SquareSet(
            chess.BB_KING_ATTACKS[square]
        ),
    }


def _is_passed_pawn(
    board: chess.Board,
    square: chess.Square,
    color: chess.Color,
) -> bool:
    piece = board.piece_at(square)
    if piece is None or piece.piece_type != chess.PAWN or piece.color != color:
        return False

    pawn_file = chess.square_file(square)
    pawn_rank = chess.square_rank(square)
    for enemy_square in board.pieces(chess.PAWN, not color):
        enemy_file = chess.square_file(enemy_square)
        enemy_rank = chess.square_rank(enemy_square)
        if abs(enemy_file - pawn_file) > 1:
            continue
        if color == chess.WHITE and enemy_rank > pawn_rank:
            return False
        if color == chess.BLACK and enemy_rank < pawn_rank:
            return False
    return True


def _is_open_file(
    board: chess.Board,
    square: chess.Square,
) -> bool:
    file_index = chess.square_file(square)
    return not any(
        chess.square_file(pawn_square) == file_index
        for color in (chess.WHITE, chess.BLACK)
        for pawn_square in board.pieces(chess.PAWN, color)
    )


def _is_verified_outpost(
    board: chess.Board,
    square: chess.Square,
    color: chess.Color,
) -> bool:
    piece = board.piece_at(square)
    if (
        piece is None
        or piece.color != color
        or piece.piece_type not in {chess.KNIGHT, chess.BISHOP}
    ):
        return False

    rank = chess.square_rank(square)
    if (color == chess.WHITE and rank < 4) or (color == chess.BLACK and rank > 3):
        return False
    if not board.attackers(color, square):
        return False

    enemy = not color
    return not any(
        square in board.attacks(pawn_square)
        for pawn_square in board.pieces(chess.PAWN, enemy)
    )


def _has_opposition(board: chess.Board) -> bool:
    white_king = board.king(chess.WHITE)
    black_king = board.king(chess.BLACK)
    if white_king is None or black_king is None:
        return False
    if _non_pawn_material(board) != 0:
        return False

    file_gap = abs(chess.square_file(white_king) - chess.square_file(black_king))
    rank_gap = abs(chess.square_rank(white_king) - chess.square_rank(black_king))
    return (file_gap == 0 and rank_gap == 2) or (rank_gap == 0 and file_gap == 2)


def _line_material_swing(
    board: chess.Board,
    line: list[chess.Move],
    mover: chess.Color,
    plies: int = 5,
) -> int:
    before = _material(board, mover) - _material(board, not mover)
    temp = board.copy(stack=False)
    for move in line[:plies]:
        if move not in temp.legal_moves:
            break
        temp.push(move)
    after = _material(temp, mover) - _material(temp, not mover)
    return after - before


def _line_exploits_targets(
    board: chess.Board,
    line: list[chess.Move],
    target_squares: Iterable[chess.Square],
) -> bool:
    """Require the PV to cash in the geometric motif, not merely resemble it."""
    if len(line) < 3:
        return False

    mover = board.turn
    after_motif = board.copy(stack=False)
    first = line[0]
    if first not in after_motif.legal_moves:
        return False
    after_motif.push(first)
    material_after_motif = (
        _material(after_motif, mover)
        - _material(after_motif, not mover)
    )

    after_reply = board.copy(stack=False)
    for move in line[:2]:
        if move not in after_reply.legal_moves:
            return False
        after_reply.push(move)

    follow_up = line[2]
    if (
        follow_up not in after_reply.legal_moves
        or not after_reply.is_capture(follow_up)
        or follow_up.to_square not in set(target_squares)
    ):
        return False

    line_end = after_motif.copy(stack=False)
    for continuation in line[1:5]:
        if continuation not in line_end.legal_moves:
            return False
        line_end.push(continuation)

    material_at_line_end = (
        _material(line_end, mover)
        - _material(line_end, not mover)
    )
    return material_at_line_end - material_after_motif >= 1


def _line_has_forcing_payoff(
    board: chess.Board,
    line: list[chess.Move],
    *,
    mate_in: int | None = None,
) -> bool:
    if mate_in is not None and mate_in > 0:
        return True
    if len(line) < 3:
        return False
    return _line_material_swing(
        board,
        line,
        board.turn,
    ) >= 1


def _sequence_evidence(
    board: chess.Board,
    line: list[chess.Move],
    *,
    mate_in: int | None = None,
) -> list[ThemeEvidence]:
    if len(line) < 3:
        return []

    first, reply, follow_up = line[:3]
    mover = board.turn
    first_piece = board.piece_at(first.from_square)
    if first_piece is None:
        return []

    after_first = board.copy(stack=False)
    first_is_capture = board.is_capture(first)
    captured_first = board.piece_at(first.to_square)
    after_first.push(first)
    if reply not in after_first.legal_moves:
        return []

    reply_is_capture = after_first.is_capture(reply)
    reply_captures_offer = (
        reply_is_capture
        and reply.to_square == first.to_square
    )
    reply_piece_before = after_first.piece_at(reply.from_square)
    after_reply = after_first.copy(stack=False)
    after_reply.push(reply)
    if follow_up not in after_reply.legal_moves:
        return []

    follow_is_capture = after_reply.is_capture(follow_up)
    result: list[ThemeEvidence] = []
    swing = _line_material_swing(board, line, mover)
    forcing_payoff = (
        swing >= 1
        or (
            mate_in is not None
            and mate_in > 0
        )
    )

    if reply_captures_offer and (swing >= 2 or after_reply.san(follow_up).endswith("#")):
        offered = chess.piece_name(first_piece.piece_type)
        if first_piece.piece_type == chess.QUEEN:
            theme = "Queen Sacrifice"
        elif first_piece.piece_type == chess.ROOK:
            theme = "Exchange Sacrifice"
        else:
            theme = "Sacrifice"
        result.append(ThemeEvidence(
            theme,
            f"The {offered} is offered on {chess.square_name(first.to_square)} and the engine line gains compensation after it is taken.",
        ))

    if reply_captures_offer and follow_is_capture and forcing_payoff:
        result.append(ThemeEvidence(
            "Decoy",
            f"The reply is drawn to {chess.square_name(reply.to_square)}, enabling {after_reply.san(follow_up)}.",
        ))

    if (
        first_is_capture
        and captured_first is not None
        and follow_is_capture
        and forcing_payoff
    ):
        defended_target = follow_up.to_square
        if first.to_square in board.attackers(
            captured_first.color,
            defended_target,
        ):
            result.append(ThemeEvidence(
                "Removal of the Defender",
                f"The first move removes {_piece_label(board, first.to_square)}, then the line captures {_piece_label(after_reply, defended_target)}.",
            ))

    if reply_piece_before is not None and follow_is_capture and forcing_payoff:
        follow_target = follow_up.to_square
        if reply.from_square in board.attackers(
            reply_piece_before.color,
            follow_target,
        ):
            result.append(ThemeEvidence(
                "Deflection",
                f"The defender is pulled away from {chess.square_name(reply.from_square)}, allowing {after_reply.san(follow_up)}.",
            ))

    follow_piece = after_reply.piece_at(follow_up.from_square)
    if forcing_payoff and follow_piece is not None and first.from_square in _between(
        follow_up.from_square,
        follow_up.to_square,
    ):
        theme = (
            "Clearance Sacrifice"
            if reply_captures_offer
            else "Clearance"
        )
        result.append(ThemeEvidence(
            theme,
            f"The first move clears {chess.square_name(first.from_square)} for {after_reply.san(follow_up)}.",
        ))

    if reply_piece_before is not None and follow_is_capture and forcing_payoff:
        defended = [
            square
            for square in after_first.attacks(reply.from_square)
            if (
                (piece := after_first.piece_at(square)) is not None
                and piece.color == reply_piece_before.color
            )
        ]
        if len(defended) >= 2 and follow_up.to_square in defended:
            result.append(ThemeEvidence(
                "Overloading",
                f"The defender on {chess.square_name(reply.from_square)} was responsible for multiple pieces and cannot maintain both duties.",
            ))

    if (
        first_piece.piece_type != chess.KING
        and board.is_attacked_by(not mover, first.from_square)
        and reply_captures_offer
        and (first_is_capture or board.gives_check(first))
        and swing >= 0
    ):
        result.append(ThemeEvidence(
            "Desperado",
            f"The attacked {chess.piece_name(first_piece.piece_type)} uses a forcing move before it is captured.",
        ))

    if board.gives_check(first) and follow_is_capture and forcing_payoff:
        immediate = chess.Move(
            follow_up.from_square,
            follow_up.to_square,
            promotion=follow_up.promotion,
        )
        if (
            immediate in board.legal_moves
            and board.is_capture(immediate)
            and immediate != first
        ):
            result.append(ThemeEvidence(
                "Zwischenzug",
                f"Instead of immediately playing {board.san(immediate)}, the line inserts the forcing check {board.san(first)} first.",
            ))

    return result


def _interference_evidence(
    board: chess.Board,
    move: chess.Move,
) -> ThemeEvidence | None:
    mover = board.turn
    enemy = not mover

    for slider_square, slider in board.piece_map().items():
        if (
            slider.color != enemy
            or slider.piece_type not in {
                chess.BISHOP,
                chess.ROOK,
                chess.QUEEN,
            }
        ):
            continue

        for defended_square in board.attacks(slider_square):
            defended = board.piece_at(defended_square)
            if defended is None or defended.color != enemy:
                continue
            between = _between(slider_square, defended_square)
            if move.to_square in between:
                return ThemeEvidence(
                    "Interference",
                    f"The move blocks the defensive line from {_piece_label(board, slider_square)} to {_piece_label(board, defended_square)}.",
                )
    return None


def _perpetual_or_windmill(
    board: chess.Board,
    line: list[chess.Move],
) -> list[ThemeEvidence]:
    if len(line) < 5:
        return []

    temp = board.copy(stack=False)
    mover = board.turn
    mover_checks = 0
    mover_check_captures = 0
    positions: dict[str, int] = {}

    for index, move in enumerate(line[:10]):
        if move not in temp.legal_moves:
            break
        san = temp.san(move)
        temp.push(move)
        key = " ".join(temp.fen().split()[:4])
        positions[key] = positions.get(key, 0) + 1
        if index % 2 == 0 and ("+" in san or "#" in san):
            mover_checks += 1
            if "x" in san:
                mover_check_captures += 1

    result: list[ThemeEvidence] = []
    if mover_checks >= 3 and any(count >= 2 for count in positions.values()):
        result.append(ThemeEvidence(
            "Perpetual Check",
            "The engine line repeats the position while the same side continues checking.",
        ))
    if mover_checks >= 3 and mover_check_captures >= 2:
        result.append(ThemeEvidence(
            "Windmill",
            "The line alternates repeated checks with captures, matching a windmill sequence.",
        ))
    return result


def verify_tactical_line(
    board: chess.Board,
    moves: Iterable[chess.Move],
    *,
    mate_in: int | None = None,
) -> list[ThemeEvidence]:
    """Conservatively verify named motifs from a legal Stockfish line."""
    line = _legal_line(board, moves)
    if not line:
        return []

    move = line[0]
    mover = board.turn
    enemy = not mover
    moved_piece = board.piece_at(move.from_square)
    if moved_piece is None:
        return []

    before_pinned = {
        square
        for square, piece in board.piece_map().items()
        if piece.color == enemy and board.is_pinned(enemy, square)
    }
    is_capture = board.is_capture(move)
    captured_piece = board.piece_at(move.to_square)
    is_en_passant = board.is_en_passant(move)
    is_castling = board.is_castling(move)
    before_in_check = board.is_check()
    before_non_pawn_material = _non_pawn_material(board)

    after = board.copy(stack=False)
    san = board.san(move)
    after.push(move)
    moved_square = move.to_square
    moved_after = after.piece_at(moved_square)
    targets = _attacked_enemy_targets(after, moved_square, enemy)
    evidence: list[ThemeEvidence] = []

    def add(theme: str, reason: str) -> None:
        evidence.append(ThemeEvidence(theme, reason))

    if after.is_checkmate():
        add("Mate in One", f"{san} checkmates immediately.")
        add("Checkmate Pattern", f"{san} is a verified checkmating pattern.")
        if _is_back_rank_mate(after, move, mover):
            add("Back-Rank Mate", "The rook or queen checkmates a king confined to its back rank.")
        if _is_smothered_mate(after, move, mover):
            add("Smothered Mate", "A knight checkmates a king whose neighboring squares are occupied by its own pieces.")
        if _is_supported_mate(after, move, mover):
            add("Support Mate", f"The mating piece on {chess.square_name(move.to_square)} is protected.")
    elif mate_in is not None and mate_in >= 2:
        if mate_in == 2:
            add("Mate in Two", "Stockfish verifies a forced mate on the mover's second turn.")
        elif mate_in >= 3:
            add("Mate in Three or More", f"Stockfish verifies a forced mate in {mate_in}.")
        add("Forced Mate", f"Stockfish reports a forced mate in {mate_in}.")
        add("Mating Net", "The move begins a Stockfish-confirmed forced mating sequence.")

    if after.is_stalemate():
        add("Stalemate", f"{san} leaves the opponent with no legal move and no check.")

    if move.promotion is not None:
        promoted = chess.piece_name(move.promotion)
        add(
            "Promotion" if move.promotion == chess.QUEEN else "Underpromotion",
            f"The pawn promotes to a {promoted} on {chess.square_name(move.to_square)}.",
        )

    if is_castling:
        add("King Safety", f"{san} castles the king and connects the rook to the position.")

    if is_en_passant:
        add("En Passant", f"{san} is a legal en passant capture.")

    checkers = list(after.checkers())
    if len(checkers) >= 2:
        add("Double Check", f"{san} leaves two pieces checking the king.")
    elif checkers and move.to_square not in checkers:
        add("Discovered Check", f"Moving from {chess.square_name(move.from_square)} uncovers check from {_piece_label(after, checkers[0])}.")

    discovered = _new_slider_attacks(board, after, mover, move.to_square)
    if (
        discovered
        and not any(item.theme == "Discovered Check" for item in evidence)
        and _line_exploits_targets(
            board,
            line,
            [discovered[0][1]],
        )
    ):
        slider, target = discovered[0]
        add("Discovered Attack", f"The move uncovers {_piece_label(after, slider)} against {_piece_label(after, target)}.")

    newly_pinned = [
        square
        for square, piece in after.piece_map().items()
        if (
            piece.color == enemy
            and square not in before_pinned
            and after.is_pinned(enemy, square)
        )
    ]
    if newly_pinned and _line_exploits_targets(
        board,
        line,
        newly_pinned,
    ):
        add("Pin", f"{san} pins {_piece_label(after, newly_pinned[0])} to the king.")

    significant_targets = [
        square
        for square in targets
        if (
            (target := after.piece_at(square)) is not None
            and PIECE_VALUES[target.piece_type] >= 3
        )
    ]
    if (
        len(targets) >= 2
        and significant_targets
        and _line_exploits_targets(
            board,
            line,
            targets,
        )
    ):
        described = " and ".join(
            _piece_label(after, square)
            for square in targets[:2]
        )
        add("Fork / Double Attack", f"{_piece_label(after, moved_square)} attacks {described} at the same time.")

    skewer, xray = _skewer_and_xray(after, moved_square, enemy)
    if skewer is not None and _line_exploits_targets(
        board,
        line,
        skewer,
    ):
        add("Skewer", f"{_piece_label(after, skewer[0])} is attacked in front of {_piece_label(after, skewer[1])} on the same line.")
    elif (
        xray is not None
        and not newly_pinned
        and _line_exploits_targets(
            board,
            line,
            xray,
        )
    ):
        add("X-Ray Attack", f"{_piece_label(after, moved_square)} lines up with {_piece_label(after, xray[1])} through one intervening piece.")

    if is_capture and captured_piece is not None:
        recaptures = [
            reply
            for reply in after.legal_moves
            if reply.to_square == move.to_square and after.is_capture(reply)
        ]
        if not recaptures:
            add("Hanging Piece", f"{san} wins the {_piece_label(board, move.to_square)} without a legal recapture.")

    trapped = _newly_trapped_target(after, targets, mover)
    if trapped is not None and _line_exploits_targets(
        board,
        line,
        [trapped],
    ):
        add("Trapped Piece", f"{_piece_label(after, trapped)} is attacked and has no safe legal escape.")

    if moved_after is not None:
        f_pawn_square = chess.F7 if enemy == chess.BLACK else chess.F2
        if (
            f_pawn_square in after.attacks(moved_square)
            and after.piece_at(f_pawn_square) is not None
            and _line_exploits_targets(
                board,
                line,
                [f_pawn_square],
            )
        ):
            add("Attack on f7 / f2", f"{_piece_label(after, moved_square)} directly attacks the pawn on {chess.square_name(f_pawn_square)}.")

        if (
            moved_after.piece_type in {chess.ROOK, chess.QUEEN}
            and _is_open_file(after, moved_square)
        ):
            add("Open File", f"{_piece_label(after, moved_square)} occupies the pawn-free {chess.FILE_NAMES[chess.square_file(moved_square)]}-file.")

        if _is_verified_outpost(after, moved_square, mover):
            add("Weak Square", f"{_piece_label(after, moved_square)} occupies a defended outpost that no enemy pawn attacks.")

        if _is_passed_pawn(after, moved_square, mover):
            add("Passed Pawn", f"The pawn on {chess.square_name(moved_square)} has no enemy pawn ahead on its file or adjacent files.")

    enemy_king = after.king(enemy)
    zone = _king_zone(enemy_king)
    zone_hits = len(set(after.attacks(moved_square)).intersection(zone))
    if zone_hits >= 2 and _is_castled_king_square(enemy_king):
        add("Attacking the Castled King", f"The move attacks {zone_hits} squares around the castled king.")
    elif zone_hits >= 2:
        add("Vulnerable King", "The move creates verified pressure in the enemy king's immediate zone.")

    if enemy_king is not None and chess.square_rank(enemy_king) in {0, 7}:
        front_rank = 1 if chess.square_rank(enemy_king) == 0 else 6
        front_squares = [
            chess.square(file_index, front_rank)
            for file_index in range(
                max(0, chess.square_file(enemy_king) - 1),
                min(7, chess.square_file(enemy_king) + 1) + 1,
            )
        ]
        if all(
            (piece := after.piece_at(square)) is not None and piece.color == enemy
            for square in front_squares
        ) and (
            (
                mate_in is not None
                and mate_in > 0
            )
            or _line_has_forcing_payoff(
                board,
                line,
                mate_in=mate_in,
            )
        ):
            add("Back-Rank Weakness", "The king is confined on its back rank by its own pieces while a rook or queen line applies pressure.")

    if before_in_check and not after.is_check():
        add("Defense", f"{san} legally answers the check.")
    elif moved_after is not None:
        newly_defended = [
            square
            for square in after.attacks(moved_square)
            if (
                (piece := after.piece_at(square)) is not None
                and piece.color == mover
                and after.is_attacked_by(enemy, square)
                and move.from_square not in board.attackers(mover, square)
            )
        ]
        if newly_defended:
            add("Defense", f"{san} adds protection to {_piece_label(after, newly_defended[0])}, which is under attack.")

    if _has_opposition(after):
        add("Opposition", "The kings face each other with exactly one square between them in a king-and-pawn ending.")

    interference = _interference_evidence(board, move)
    if interference is not None and _line_has_forcing_payoff(
        board,
        line,
        mate_in=mate_in,
    ):
        evidence.append(interference)

    evidence.extend(
        _sequence_evidence(
            board,
            line,
            mate_in=mate_in,
        )
    )
    evidence.extend(_perpetual_or_windmill(board, line))

    line_end = board.copy(stack=False)
    for continuation_move in line[:4]:
        if continuation_move not in line_end.legal_moves:
            break
        line_end.push(continuation_move)

    queens_before = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(
        board.pieces(chess.QUEEN, chess.BLACK)
    )
    queens_after = len(line_end.pieces(chess.QUEEN, chess.WHITE)) + len(
        line_end.pieces(chess.QUEEN, chess.BLACK)
    )
    material_reduction = (
        before_non_pawn_material
        - _non_pawn_material(line_end)
    )
    if (
        len(line) >= 2
        and material_reduction >= 8
        and queens_after < queens_before
    ):
        add("Simplification", "The verified line trades queens and removes substantial non-pawn material.")

    tactical_names = {
        item.theme
        for item in evidence
        if item.theme not in {
            "Defense",
            "Vulnerable King",
            "Attacking the Castled King",
            "Back-Rank Weakness",
        }
    }
    if _non_pawn_material(board) <= 16 and tactical_names:
        add("Endgame Tactic", "The verified tactical motif occurs in a low-material endgame position.")

    # Stable priority, one reason per label, and at most three labels for UI.
    return prioritize_theme_evidence(
        evidence
    )


def verified_move_themes(
    board: chess.Board,
    move: chess.Move,
) -> list[str]:
    return [
        item.theme
        for item in verify_tactical_line(
            board,
            [move],
        )
    ]
