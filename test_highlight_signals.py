import copy
import unittest
import numpy as np
import core
from highlight_signals import score_sample_times,refinement_times,fuse_candidates,repeated_sequence,remove_repeated_candidates


class SignalTests(unittest.TestCase):
    def test_bad_ocr_spike_does_not_hide_the_next_real_goal(self):
        readings=[(0,(0,0)),(8,(0,0)),(16,(8,8)),(24,(8,8)),(32,(1,0)),(40,(1,0))]
        events=core.stable_scores(readings)
        self.assertEqual([e['score'] for e in core.clean_score_events(events)],[(0,0),(1,0)])
        self.assertEqual(len(core.confirmed_goal_candidates(events)),1)
        self.assertIn(25.,refinement_times(readings,50))

    def test_impossible_team_swap_does_not_poison_later_score(self):
        events=[dict(time=t,score=s) for t,s in [(0,(1,0)),(20,(0,1)),(40,(2,0))]]
        self.assertEqual([g['reason'] for g in core.confirmed_goal_candidates(events)],['Есеп өзгерді: 2:0'])

    def test_unresolved_multi_goal_jump_is_not_split_into_invented_goals(self):
        events=[dict(time=t,score=s) for t,s in [(0,(0,0)),(20,(2,0)),(40,(3,0))]]
        self.assertEqual(len(core.clean_score_events(events)),3)
        self.assertEqual([g['reason'] for g in core.confirmed_goal_candidates(events)],['Есеп өзгерді: 3:0'])

    def test_three_overlapping_goals_do_not_duplicate_source_footage(self):
        clips=core.choose_clips([dict(start=a,end=b,priority=100,kind='goal',goal_at=g)
                                 for a,b,g in [(0,17,10),(28,45,38),(8,31,20)]],60,50)
        self.assertEqual(len(clips),1)
        self.assertEqual((clips[0]['start'],clips[0]['end']),(0,45))
        self.assertEqual(clips[0]['goal_times'],[10,20,38])

    def test_goal_mark_inside_full_budget_is_retained(self):
        clips=core.choose_clips([dict(start=10,end=50,priority=100,kind='goal',goal_at=20),
                                 dict(start=25,end=40,priority=100,kind='goal',goal_at=30)],100,40)
        self.assertEqual(clips[0]['goal_times'],[20,30])

    def test_clear_peak_in_otherwise_silent_audio_can_refine_confirmed_goal(self):
        energy=np.zeros(40);energy[20]=.6
        clip=fuse_candidates([dict(start=10,end=27,priority=100,kind='goal',goal_at=18)],energy)[0]
        self.assertTrue(clip['evidence']['audio_peak']);self.assertEqual(clip['goal_at'],19)

    def test_full_match_sampling_can_confirm_scores(self):
        times=score_sample_times(5400)
        self.assertLessEqual(max(b-a for a,b in zip(times,times[1:])),8)
        events=core.stable_scores([(t,(0,0) if t<1000 else (1,0)) for t in times])
        self.assertEqual([e['score'] for e in events],[(0,0),(1,0)])
        self.assertEqual(len(core.confirmed_goal_candidates(events)),1)

    def test_sparse_two_goal_jump_is_refined_without_inventing_events(self):
        readings=[(0,(0,0)),(8,(0,0)),(16,(2,0)),(24,(2,0))]
        extra=refinement_times(readings,30)
        self.assertIn(9.,extra);self.assertIn(15.,extra)
        dense=readings+[(t,(0,0) if t<10 else (1,0) if t<15 else (2,0)) for t in extra]
        events=core.stable_scores(sorted(dense))
        self.assertEqual(len(core.confirmed_goal_candidates(events)),2)

    def test_close_confirmed_goals_share_one_clip_instead_of_losing_footage(self):
        clips=core.choose_clips([dict(start=0,end=17,priority=100,kind='goal',goal_at=10),
                                 dict(start=8,end=25,priority=100,kind='goal',goal_at=18)],40,30)
        self.assertEqual(len(clips),1);self.assertEqual(clips[0]['end'],25)
        self.assertEqual(clips[0]['goal_times'],[10,18])

    def test_audio_and_visual_activity_never_become_confirmed_goal(self):
        energy=np.ones(40)*.02;energy[20]=.8
        clips=fuse_candidates([dict(start=15,end=25,priority=4,reason='audio')],energy)
        self.assertEqual(clips[0]['kind'],'highlight')
        self.assertEqual(clips[0]['confidence'],'review_required')
        self.assertTrue(clips[0]['evidence']['audio_peak'])

    def test_confirmed_goal_survives_quiet_audio(self):
        clips=fuse_candidates([dict(start=10,end=27,priority=100,kind='goal',goal_at=18)],np.zeros(40))
        self.assertEqual(clips[0]['confidence'],'score_confirmed');self.assertEqual(clips[0]['goal_at'],18)

    def sequence(self):
        return [dict(bits=[(i*17+j*13)%256 for j in range(18)],mean=.45,green=.5,contrast=.2) for i in range(6)]

    def test_only_repeated_audio_candidates_are_removed(self):
        seq=self.sequence();self.assertTrue(repeated_sequence(seq,copy.deepcopy(seq)))
        clips=[dict(priority=100,kind='goal',_signature=seq),dict(priority=20,kind='highlight',_signature=seq),dict(priority=100,kind='goal',_signature=seq)]
        kept,count=remove_repeated_candidates(clips)
        self.assertEqual(count,1);self.assertEqual(len(kept),2)
        self.assertTrue(all(c['kind']=='goal' and '_signature' not in c for c in kept))

    def test_static_frames_and_different_play_are_not_duplicates(self):
        seq=self.sequence()
        self.assertFalse(repeated_sequence([seq[0]]*6,[seq[0]]*6))
        other=copy.deepcopy(seq)
        for s in other:s['bits']=[x^255 for x in s['bits']]
        self.assertFalse(repeated_sequence(seq,other))
