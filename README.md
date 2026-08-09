# AI Chess Coach

Current stabilization build: **v1.0.4**.

A focused Lichess training site: sign in, choose a practice level, challenge your dedicated BOT account, and receive immediate Stockfish + optional LLM coaching on your moves.

## What changed in this cleanup

The old project embedded the full `lichess-bot` repository and controlled it by rewriting YAML/restarting a child process. That layer is gone. The backend now talks directly to the Lichess Bot API, owns the Stockfish process, reconnects dropped streams, recovers active games after restart, prevents duplicate move submissions, and accepts training takebacks.

The web app no longer has `!level`, player chat, self-invite cards, or a manual fake bot-online state. Difficulty is website-controlled. The bot uses short engine time budgets (about 45–240 ms locally) and varies move quality rather than adding artificial waiting.

The board input path is also hardened: drag capture stays on the board element, a submitted move locks input until the authoritative game stream confirms the exact UCI move, and optimistic pieces disappear as soon as the stream advances. This prevents fast bot replies from leaving the browser one ply behind.

Active game IDs are saved locally and reopened after a refresh. Before creating any new challenge, the site also checks for an already-running game against the coach bot. Refreshing or closing the page never calls abort/resign. Ending a game now requires an explicit confirmation dialog.

The coach now separates **engine truth** from **LLM teaching**: Stockfish decides what is good/bad and supplies grounded lines; the LLM explains why, chooses whether a best-move/threat visual is useful, and chooses key squares. The server validates annotations. Important mistakes can be reopened in a position-correct review board so arrows are never shown on the wrong live position.


## Interface & review improvements in v1.0.4

The training setup now offers **Unlimited**, 30 min, 15+10, 10+5, 10 min, 5+3, and 3+2. Unlimited challenges omit the Lichess clock fields, so the board shows an infinity clock instead of counting down. Your selected time control is remembered locally.

The **Learning log** is now persistent. Important coaching moments are saved in the browser per game and restored after refresh. Clicking any log entry opens the exact FEN from before the mistake, with an optional second tab for the position immediately after the move. The review board keeps the player's original orientation even when reviewing an older saved game.

Game endings now have a dedicated result experience: a visible result strip beside the move list and a **Game Over** modal with score, win/loss/draw state, ending reason, coaching counts, **Review mistakes**, **Keep board open**, and **New training game** actions.

## One-time setup (macOS)

Requirements: Python 3.10+, Node 20.19+ or 22.12+, npm, Homebrew Stockfish.

```bash
brew install stockfish
./setup_mac.sh
```

Edit `.env`:

```env
LICHESS_BOT_TOKEN=your_bot_account_token
LICHESS_BOT_USERNAME=bot_2435

# Optional, for richer explanations. Without it, Stockfish fallback coaching works.
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-luna
```

The Lichess token must belong to a BOT account. Do not put your normal player token here.

## Run

Simplest:

```bash
./dev.sh
```

Then open `http://localhost:5173`.

Or use two terminals:

```bash
./run_backend.sh
```

```bash
./run_web.sh
```

## Practice ladder

| Level | Estimated practice strength | Engine budget |
|---|---:|---:|
| Newcomer | ~500 | 45 ms |
| Beginner | ~800 | 60 ms |
| Developing | ~1100 | 80 ms |
| Club | ~1400 | 110 ms |
| Strong | ~1700 | 160 ms |
| Expert | ~2000 | 240 ms |

These are teaching-strength estimates, not official Lichess ratings. Lower levels intentionally choose more often among reasonable-but-inferior engine candidates.

## Coaching behavior

Every student move is checked. Good moves get a short confirmation; significant mistakes get an explanation, reusable lesson, self-question, and optional board annotations. The **Review this position** button separates the two contexts:

- **Better move** — position before your move, green alternative arrow.
- **Opponent threat** — position after your move, red forcing-response arrow.

The learning log keeps the important moments and summarizes recurring focus areas after the game. Voice and board hints are optional.

## Configuration

`.env` is preferred and is ignored by Git. `bot/config.yml` is supported as a local fallback for the bot token.

Useful tuning variables:

```env
STOCKFISH_PATH=/opt/homebrew/bin/stockfish
CHESS_SERVER_PORT=8765
COACH_TIME_MS=180
COACH_MISTAKE_THRESHOLD_CP=80
```

## Troubleshooting

**Coach bot offline / token error** — check `LICHESS_BOT_TOKEN`, then restart `./dev.sh`.

**Stockfish not found** — run `brew install stockfish`, or set `STOCKFISH_PATH`.

**Port 8765 already in use** — stop the old backend process before starting this one.

**Lichess game is open but site is stale** — refresh the page. The current game ID is persisted locally, the game stream reconnects to that ID, and the app checks `/api/account/playing` before it creates any new challenge. A stale saved game is discarded if Lichess reports that it no longer exists.

**A piece will not drag reliably** — v1.0.3 moved pointer capture from the piece element to the board itself. If you are upgrading an older copy, replace `src/components/ChessBoard.tsx` and `src/App.tsx` together.

**Unexpected resign/abort** — v1.0.3 has no refresh/unload resign path. The only UI route to abort/resign is `End game…` followed by a confirmation button.

**No OpenAI key** — this is okay. The project uses deterministic Stockfish-based explanations instead.

## Tests

```bash
npm run typecheck
./.venv/bin/python -m unittest discover -s tests -v
```

The Python unit tests cover level progression, state reconstruction, duplicate-move protection, takeback direction, and core move classification. TypeScript strict checking covers the web changes. Live Lichess behavior requires your BOT token and therefore is not exercised by offline tests.

## Engine compatibility note

The bot and coach configure only ordinary UCI options (for example `Threads` and `Hash`). Options managed by python-chess, including `Ponder` and `MultiPV`, are intentionally not passed to `engine.configure()`. This avoids startup errors such as `cannot set Ponder which is automatically managed`.
