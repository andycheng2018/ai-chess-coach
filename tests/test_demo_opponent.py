from pathlib import Path
import sys, unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server'))
import chess
from bot_runtime import LichessBotRuntime
from demo_opponent import choose_demo_move, offered_capture
from vbot_policy import CelebrationPolicy

class DemoOpponentTests(unittest.TestCase):
    def test_offers_queen_after_knight_development_in_both_colors(self):
        board=chess.Board()
        for move in ['e2e4','e7e5','g1f3']: board.push_uci(move)
        for position in [board,board.mirror()]:
            before=position.fen()
            move=choose_demo_move(position)
            self.assertEqual(position.fen(),before)
            self.assertIn(move,position.legal_moves)
            position.push(move)
            self.assertEqual(offered_capture(position),900)
    def test_opening_opens_queen_and_all_choices_are_legal(self):
        board=chess.Board();board.push_uci('e2e4')
        for position in [board,board.mirror()]:
            move=choose_demo_move(position)
            self.assertEqual(position.piece_at(move.from_square).piece_type,chess.PAWN)
            self.assertIn(chess.square_file(move.from_square),[3,4])
        for _ in range(30):
            if board.is_game_over():break
            move=choose_demo_move(board)
            self.assertIn(move,board.legal_moves);board.push(move)
    def test_capture_offer_rejects_pinned_and_equal_exchange(self):
        pinned=chess.Board('3rk3/8/8/8/8/8/3R1q2/3K4 w - - 0 1')
        self.assertNotIn(chess.Move.from_uci('d2f2'),pinned.legal_moves)
        self.assertEqual(offered_capture(pinned),0)
        exchange=chess.Board('3rk3/8/8/3q4/8/8/3Q4/4K3 w - - 0 1')
        self.assertEqual(offered_capture(exchange),0)
    def runtime(self,rated=False):
        runtime=LichessBotRuntime()
        runtime._game_states['AbCd1234']={'gameId':'AbCd1234','rated':rated,'initialFen':'startpos',
                'state':{'status':'started','moves':'e2e4'},'updatedAt':1}
        return runtime
    def test_per_game_unrated_guard_and_cleanup(self):
        for rated in [True,None,0,'false']:
            runtime=self.runtime(rated)
            with self.assertRaises(ValueError):runtime.set_demo_mode('AbCd1234',True)
        runtime=self.runtime()
        with self.assertRaises(ValueError):runtime.set_demo_mode('Missing1',True)
        with self.assertRaises(ValueError):runtime.set_demo_mode('AbCd1234','true')
        runtime.set_demo_mode('AbCd1234',True)
        self.assertTrue(runtime.game_state('AbCd1234')['demoMode'])
        self.assertEqual(runtime.status()['demoGames'],['AbCd1234'])
        runtime._clear_game_state('AbCd1234')
        self.assertFalse(runtime.game_state('AbCd1234')['demoMode'])
    def test_runtime_uses_demo_only_for_selected_game_and_submits_once(self):
        runtime=self.runtime();runtime.set_demo_mode('AbCd1234',True)
        runtime._engine.choose_move=Mock(return_value=(chess.Move.from_uci('e7e6'),1))
        runtime._request=Mock()
        state={'status':'started','moves':'e2e4'}
        runtime._maybe_move('AbCd1234','startpos',state,chess.BLACK)
        runtime._engine.choose_move.assert_not_called()
        runtime._maybe_move('AbCd1234','startpos',state,chess.BLACK)
        runtime._request.assert_called_once()
        runtime._maybe_move('Other123','startpos',state,chess.BLACK)
        runtime._engine.choose_move.assert_called_once()
    def test_normal_restored_without_changing_global_level(self):
        runtime=self.runtime();original=runtime.level()
        runtime.set_demo_mode('AbCd1234',True);runtime.set_demo_mode('AbCd1234',False)
        self.assertEqual(runtime.level(),original)
        self.assertFalse(runtime.game_state('AbCd1234')['demoMode'])
    def test_real_good_capture_qualifies_even_when_still_losing_only_in_unrated_demo(self):
        record={'gameId':'AbCd1234','playerColor':'white','ply':1,'classification':'good',
            'fenBefore':'4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1',
            'playedMoveUci':'d2d5','opponentReplyUci':'e8e7','evaluationAfter':-500,
            'engineDiagnostics':{'profile':'balanced','playedSearch':{'depth':16}}}
        game={'timeControlKnown':True,'clock':None,'state':{'status':'started'},'demoMode':True,'rated':False}
        result=CelebrationPolicy().observe(record,game)
        self.assertEqual(result['tier'],'major');self.assertTrue(result['demoCapture'])
        for changed in [{'demoMode':False},{'rated':True},{'rated':None}]:
            self.assertEqual(CelebrationPolicy().observe(record,{**game,**changed})['tier'],'small')
        for changed in [{'classification':'mistake'},{'opponentReplyUci':None},
                        {'engineDiagnostics':{'playedSearch':{'depth':8}}}]:
            self.assertNotEqual(CelebrationPolicy().observe({**record,**changed},game)['tier'],'major')
    def test_demo_does_not_upgrade_equal_exchange(self):
        record={'gameId':'AbCd1234','playerColor':'white','ply':1,'classification':'good',
            'fenBefore':'3rk3/8/8/3q4/8/8/3Q4/4K3 w - - 0 1',
            'playedMoveUci':'d2d5','opponentReplyUci':'d8d5','evaluationAfter':0,
            'engineDiagnostics':{'profile':'balanced','playedSearch':{'depth':16}}}
        self.assertEqual(CelebrationPolicy().observe(record,{'demoMode':True,'rated':False})['tier'],'small')

if __name__=='__main__':unittest.main()
