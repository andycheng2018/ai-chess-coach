# Chess Buddy: AI Chess Coach

Chess Buddy is a real-time chess coaching app I built to make engine analysis feel more like learning from a human coach.

Instead of only telling the player the best move like what chess engines (Stockfish, AlphaZero) do, Chess Buddy watches the game, identifies important mistakes and opportunities, and explains **why** they matter. It works with regular Lichess games and can also connect to a physical SenseRobot chess board. **Important Note:** Chess Buddy only allows the player to train with custom chess bots ran by stockfish. Live games with other players are not allowed and would be considered cheating.

## Demo

### Chess Buddy Demo

[![Watch the Chess Buddy demo](https://img.youtube.com/vi/vRGb5EtCH84/maxresdefault.jpg)](https://www.youtube.com/shorts/vRGb5EtCH84)

A quick demo of Chess Buddy providing real-time chess analysis and AI coaching.

### Live Investor Presentation

[![Watch the investor presentation](https://img.youtube.com/vi/TgatZ2pcA3w/maxresdefault.jpg)](https://www.youtube.com/watch?v=TgatZ2pcA3w)

Presenting Chess Buddy and its SenseRobot integration during an in-person demo.


The main design idea is simple:

> **Stockfish is the chess truth. Lichess is the game truth. AI explains the Stockfish analysis.**

Stockfish is responsible for evaluations, best moves, tactics, and move classification. Lichess is responsible for all functionalities tied to a chess game, including preserving the game state if the player disconnects. The language model (GPT-4.1-mini) turns those verified results into short, understandable coaching instead of trying to analyze the position itself.

## What it does

* **Live AI coaching**: analyzes moves as you play and explains important mistakes in natural/chess language.
* **Critical-position questions**: sometimes asks the player what they think the opponent is threatening instead of immediately giving away the answer.
* **Personalized practice**: turns useful mistakes from the game into tactical or positional puzzles afterward.
* **Learning log**: saves important moments so players can revisit the exact position and see the better move or opponent threat.
* **Voice coach**: speaks feedback using ElevenLabs, with browser speech tts as a fallback.
* **English & Chinese coaching**: supports coaching and voice feedback in both languages.
* **SenseRobot support**: scan a SenseRobot Lichess room QR code and use Chess Buddy while playing on a physical board.
* **Adjustable opponent strength**: Stockfish-based opponent with multiple practice levels.
* **iOS + web**: built as a React web app and packaged for iPhone using Capacitor.

## How it works

A typical game looks like this:

1. The player signs in with Lichess and starts a game.
2. Lichess streams the moves to Chess Buddy in real time.
3. Stockfish evaluates the player's move and checks what changed in the position.
4. Important moments are passed to the coaching layer.
5. The AI turns Stockfish's analysis into a short explanation or question.
6. The feedback can be displayed on screen and spoken aloud.
7. Useful mistakes are saved for review and can become practice puzzles.

This separation was important to me because LLMs can explain ideas well, but they are not reliable chess engines (As of 2026, AI is in general pretty bad at chess. They are great at hallucinating where pieces are, thus making many illegal moves). I use **Stockfish as the source of truth** and AI only for communication.

## SenseRobot Integration

Chess Buddy can also work with a physical **SenseRobot** chess board.

The iPhone app scans the room QR code created by SenseRobot and connects the Chess Buddy bot to the corresponding Lichess game. Moves made on the physical board are synchronized through Lichess, allowing the same coaching system to analyze a real over-the-board game.

This was one of the more interesting parts of the project because it connects:

**physical chess board → Lichess → backend → Stockfish → AI coach → iPhone**

## Reliability

Real-time games introduced several problems that weren't obvious when I first built the project.

For example, players can move faster than the coach can finish analyzing the previous move (especially if the analysis mode is selected to be deeper). I solved this with a **FIFO coaching queue**, so a new move doesn't silently cancel an earlier mistake.

The app also handles:

* dropped Lichess streams and automatic reconnects
* backend restarts during active games
* duplicate move protection
* Lichess rate limits
* Stockfish process failures
* iOS audio restrictions
* restoring active games after reopening the app

Lichess remains the authoritative source for the game state, so the frontend can recover instead of relying only on local state.

## Tech Stack

**Frontend**

* React
* TypeScript
* Vite
* chess.js

**iOS**

* Capacitor
* Xcode
* QR scanning

**Backend / AI**

* Python
* Stockfish / python-chess
* OpenAI API
* ElevenLabs

**Infrastructure**

* Lichess OAuth + Board/Bot APIs
* Docker
* Render

## Running Locally

### Requirements

* Python 3.10+
* Node.js
* npm
* Stockfish
* Lichess BOT account (Anyone can make their own on Lichess)

Clone the repository and set up the project:

```bash
git clone <repo>
cd ai-chess-coach
./setup_mac.sh
```

Create a `.env` file using `.env.example` and add the services you want to use.

Then run:

```bash
./dev.sh
```

The web app will run locally at:

```text
http://localhost:5173
```

The LLM and ElevenLabs integrations are optional. Stockfish-based chess analysis can still work without them.

## What I Learned

The goal of this project was to integrate it with the SenseRobot chess robot without accessing its internal API since this is still closed to the public as of 2026. The workaround I found was to use its support for the 3rd party chess browser Lichess. By challenging a bot in Lichess and connecting it to the SenseRobot, we can effectively create a real game hosted by Lichess and easily analyzed by Stockfish.

Some of the biggest things I learned were:

* grounding AI output in deterministic systems instead of trusting the model directly
* designing around unreliable real-time network streams
* synchronizing multiple clients around one authoritative game state
* handling asynchronous analysis without losing events
* integrating a web application with an iOS app and physical hardware
* turning raw engine output into feedback that is actually useful to a player

The hardest part wasn't making Stockfish play chess. It was deciding **when the coach should speak, what it should teach, and how to make sure what it says is actually correct.**

## Status

Chess Buddy is an active project and is still being improved, especially around coaching quality, puzzle selection, voice behavior, and physical-board integration to hopefully be a stepping stone in AI coaching technologies.