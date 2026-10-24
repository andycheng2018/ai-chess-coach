import { useEffect, useState } from 'react';
import { canConfirmPhysicalExchange, physicalWitnessMatches, senseMoveLine, type PhysicalWitness } from '../sensePhysicalSync';

type Props = { gameId: string; username: string; playerColor: 'white' | 'black'; moves: string; san: string[]; connected: boolean };

export function SenseRobotGameStatus({ gameId, username, playerColor, moves, san, connected }: Props) {
  const [witness, setWitness] = useState<PhysicalWitness | null>(null);
  const confirmed = physicalWitnessMatches(witness, gameId, username, moves);
  const eligible = connected && canConfirmPhysicalExchange(moves, playerColor);
  useEffect(() => { if (witness && !confirmed) setWitness(null); }, [witness, confirmed]);
  return <section className="sense-game-status" aria-label="SenseRobot game connection">
    <div><strong>SenseRobot · {gameId}</strong><span role="status">{connected ? 'Lichess synced' : 'Reconnecting to Lichess'}</span></div>
    <p>{username} · <strong>{playerColor}</strong> · {san.length ? `Latest moves: ${san.slice(-6).join(' · ')}` : 'No moves recorded in this game yet.'}</p>
    {confirmed ? <p className="sense-physical-confirmed">✓ You confirmed a matching physical move and robot reply for this game. Check new moves continue to match.</p>
      : <><p>Physical board unconfirmed for this game. After your move and the robot’s reply, compare the moves above.</p>
        <button type="button" className="ghost" disabled={!eligible} onClick={() => setWitness({ gameId, username, moves: senseMoveLine(moves) })}>Confirm matching physical moves</button></>}
    <details><summary>Robot still shows a QR code?</summary><p>The screen can stay on the invitation while a game still plays. Check the game ID and actual physical moves. The QR screen alone does not prove disconnection; avoid rejoining or creating another room solely because it stays visible.</p></details>
  </section>;
}
