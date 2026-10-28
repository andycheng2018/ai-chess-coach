import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import chess
from vbot_policy import CelebrationPolicy, fast_or_unknown


def record(ply=1, score=0, **updates):
    return {'gameId':'AbCd1234','playerColor':'white','ply':ply,'classification':'good',
            'fenBefore':chess.STARTING_FEN,'playedMoveUci':'e2e4','opponentReplyUci':'e7e5',
            'evaluationAfter':score,'engineDiagnostics':{'profile':'balanced','playedSearch':{'depth':16}},**updates}

GAME={'timeControlKnown':True,'clock':None,'state':{'status':'started'}}


class PolicyTests(unittest.TestCase):
    def test_book_and_ordinary_best_moves_never_become_full_dances(self):
        for label in ['good','book','excellent','best']:
            policy=CelebrationPolicy()
            for n,score in enumerate([20,25,10,30,15,20,25,20,22,25]):
                with self.subTest(label=label,n=n):
                    self.assertEqual(policy.observe(record(2*n+1,score,classification=label),GAME)['tier'],'small')

    def test_material_is_net_after_expected_reply_for_either_color(self):
        for mirror in [False, True]:
            for fen,move,reply,expected in [
                ('4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1','d2d5','e8e7','major'),
                ('3rk3/8/8/3q4/8/8/3Q4/4K3 w - - 0 1','d2d5','d8d5','small')]:
                board=chess.Board(fen)
                if mirror:
                    board=board.mirror()
                    def flip(uci):
                        m=chess.Move.from_uci(uci)
                        return chess.Move(chess.square_mirror(m.from_square),chess.square_mirror(m.to_square)).uci()
                    move,reply=flip(move),flip(reply)
                color='white' if board.turn else 'black'
                decision=CelebrationPolicy().observe(record(score=500,playerColor=color,fenBefore=board.fen(),playedMoveUci=move,opponentReplyUci=reply),GAME)
                self.assertEqual(decision['tier'],expected)

    def test_missing_reply_or_losing_evaluation_does_not_claim_material_win(self):
        args={'fenBefore':'4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1','playedMoveUci':'d2d5'}
        for extra in [{'opponentReplyUci':None,'evaluationAfter':500},
                      {'opponentReplyUci':'e8e7','evaluationAfter':-500}]:
            self.assertEqual(CelebrationPolicy().observe(record(**args,**extra),GAME)['tier'],'small')

    def test_single_evaluation_flip_uses_human_turn_baseline_not_move_quality(self):
        for color in ['white','black']:
            policy=CelebrationPolicy()
            for n,score in enumerate([-100,-105,-95,-100,-100,160]):
                decision=policy.observe(record(2*n+1,score,playerColor=color,evaluationBefore=score),GAME)
            self.assertEqual(decision['tier'],'major')
            self.assertGreaterEqual(decision['metrics']['gainCp'],200)
            # Plateau does not repeatedly celebrate the same advantage.
            for n in range(6,14):
                self.assertEqual(policy.observe(record(2*n+1,160,playerColor=color),GAME)['tier'],'small')

    def test_sustained_subthreshold_improvement_earns_one_major(self):
        policy=CelebrationPolicy(); decisions=[]
        for n,score in enumerate([0,5,-5,0,0,110,150,190]):
            decisions.append(policy.observe(record(2*n+1,score),GAME))
        self.assertEqual([d['tier'] for d in decisions],['small']*7+['major'])
        self.assertIn('Three human-turn',decisions[-1]['reason'])

    def test_noisy_or_one_off_unconfirmed_scores_do_not_pass_trend(self):
        policy=CelebrationPolicy()
        for n,score in enumerate([-200,200,-180,180,0,250,260,270]):
            self.assertEqual(policy.observe(record(2*n+1,score),GAME)['tier'],'small')

    def test_low_depth_missing_nan_and_mate_values_clear_the_baseline(self):
        for extra in [{'evaluationAfter':None},{'evaluationAfter':float('nan')},
                      {'evaluationAfter':20000},{'engineDiagnostics':{'playedSearch':{'depth':8}}},
                      {'engineDiagnostics':None}]:
            policy=CelebrationPolicy()
            for n in range(3): policy.observe(record(2*n+1,-100),GAME)
            decision=policy.observe(record(7,300,**extra),GAME)
            self.assertEqual(decision['tier'],'small')
            self.assertEqual(len(policy.points),0)

    def test_gaps_profiles_games_and_colors_reset_baseline(self):
        for extra in [{'ply':11},{'gameId':'Other123'},{'playerColor':'black'},
                      {'engineDiagnostics':{'profile':'deep','playedSearch':{'depth':18}}}]:
            policy=CelebrationPolicy()
            for n in range(3): policy.observe(record(2*n+1,-100),GAME)
            data=record(7,200);data.update(extra)
            self.assertEqual(policy.observe(data,GAME)['tier'],'small')

    def test_fast_unknown_and_low_clock_suppress_full_dances(self):
        rapid={'timeControlKnown':True,'clock':{'initial':600000,'increment':0},'state':{'wtime':300000,'btime':300000}}
        self.assertEqual(fast_or_unknown(GAME,'white'),(False,None))
        self.assertEqual(fast_or_unknown(rapid,'black'),(False,None))
        for game in [{}, {'timeControlKnown':True,'clock':{}},
                     {**rapid,'clock':{'initial':180000,'increment':2000}},
                     {**rapid,'state':{'wtime':119999}},
                     {**rapid,'state':{'btime':300000}}]:
            self.assertTrue(fast_or_unknown(game,'white')[0])

    def test_bad_move_cannot_earn_major_even_with_material_or_score_gain(self):
        for label in ['inaccuracy','mistake','blunder']:
            decision=CelebrationPolicy().observe(record(score=500,classification=label,fenBefore='4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1',playedMoveUci='d2d5',opponentReplyUci='e8e7'),GAME)
            self.assertEqual(decision['tier'],'sad' if label == 'blunder' else 'none')

    def test_blunder_uses_coach_label_with_missing_or_mate_evaluation_and_resets_baseline(self):
        for color in ['white', 'black']:
            for score in [None, -20000, 400]:
                policy = CelebrationPolicy()
                policy.observe(record(1, -100, playerColor=color), GAME)
                result = policy.observe(record(3, score, classification='blunder', playerColor=color), GAME)
                self.assertEqual(result['tier'], 'sad')
                self.assertEqual(len(policy.points), 0)


if __name__=='__main__':unittest.main()
