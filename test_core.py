import unittest
from core import score_from_ocr, stable_scores, choose_clips, validate_clips, confirmed_goal_candidates, audio_candidates

def entry(text,x=0,y=0):return ([[x,y],[x+35,y],[x+35,y+14],[x,y+14]],text,.95)

class CoreTests(unittest.TestCase):
    def test_clock_is_not_score(self):
        self.assertIsNone(score_from_ocr([entry('83:24')]))
        self.assertIsNone(score_from_ocr([entry('1:23')]))
        self.assertEqual(score_from_ocr([entry('AKT 1 3 ORD'),entry('76:43',0,40)]),(1,3))
    def test_stability_and_var(self):
        r=stable_scores([(0,(1,2)),(4,(1,2)),(8,(2,2)),(12,(2,2)),(16,(1,2)),(20,(1,2)),(24,(8,8))])
        self.assertEqual([x['score'] for x in r],[(1,2),(2,2),(1,2)])
    def test_selection_bounds_and_priority(self):
        cs=[dict(start=-2,end=8,priority=1,reason='audio'),dict(start=4,end=18,priority=100,reason='goal'),dict(start=19,end=29,priority=1,reason='audio')]
        chosen=choose_clips(cs,25,20)
        self.assertEqual(chosen[0]['reason'],'goal')
        self.assertLessEqual(sum(c['end']-c['start'] for c in chosen),20)
        self.assertTrue(all(0<=c['start']<c['end']<=25 for c in chosen))
    def test_hidden_scoreboard_and_retracted_goal(self):
        readings=[(0,(1,1)),(4,(1,1)),(8,(1,2)),(12,None),(16,(1,2)),
                  (20,(2,2)),(24,(2,2)),(28,(1,2)),(32,(1,2)),(36,(1,3)),(40,(1,3))]
        goals=confirmed_goal_candidates(stable_scores(readings))
        self.assertEqual([g['reason'] for g in goals],['Есеп өзгерді: 1:2','Есеп өзгерді: 1:3'])
        self.assertEqual(goals[0]['start'],-6)
    def test_short_selection_is_not_padded(self):
        clips=choose_clips([dict(start=20,end=37,priority=100,reason='goal')],600,176.9)
        self.assertEqual(sum(c['end']-c['start'] for c in clips),17)
        self.assertEqual(audio_candidates([.2]*200,200),[])
        energy=[.02]*200
        energy[80:84]=[.2,.4,.4,.2]
        self.assertTrue(audio_candidates(energy,200))
    def test_no_arbitrary_truncation(self):
        c=[dict(start=10,end=27,priority=100,reason='goal'),dict(start=40,end=57,priority=100,reason='goal')]
        self.assertEqual(len(choose_clips(c,100,20)),1)
    def test_bad_times(self):
        for a,b in [(-1,2),(4,3),(0,999),(float('nan'),4)]:
            with self.assertRaises(ValueError):validate_clips([dict(start=a,end=b)],30)
if __name__=='__main__':unittest.main()
