import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import publishing
from timeline import plan_timeline,segment_duration

class PublishingTests(unittest.TestCase):
    def test_match_names(self):
        for title in ['Испания — Аргентина','Spain v Argentina | Final | Highlights',
                      'HIGHLIGHTS | Spain 1-0 Argentina | Final','Spain vs Argentina 1:0']:
            p=publishing.parse_match_title(title)
            self.assertIsNotNone(p,title)
            self.assertIn(p['team_a'],['Испания','Spain'])
            self.assertIn(p['team_b'],['Аргентина','Argentina'])
        self.assertIsNone(publishing.parse_match_title('Unidentified football video'))
    def test_tags_and_text(self):
        t=publishing.youtube_text('Ақтөбе','Ордабасы','1:3')
        self.assertIn('Ақтөбе — Ордабасы 1:3',t)
        self.assertIn('#рекомендации #рекомендация',t)
        self.assertNotIn('Ферран',t)
        self.assertLessEqual(len(t.split('ТЕГТЕР\n')[1].strip()),500)
    def test_safe_names(self):
        self.assertNotIn('/',publishing.safe_name('А/Б:Клуб?'))
        self.assertNotEqual(publishing.safe_name('CON'),'CON')
    def test_full_slow_motion_duration(self):
        c=dict(start=0,end=10,kind='goal',goal_at=5,reason='goal')
        p=plan_timeline([c],180,True,True,.5)
        r=[x for x in p['segments'] if x['is_replay']][0]
        self.assertEqual((r['start'],r['end']),(1,8))
        self.assertEqual(segment_duration(r),14)
        self.assertEqual(p['duration'],27)
    def test_does_not_truncate_replay_for_limit(self):
        c=dict(start=0,end=10,kind='goal',goal_at=5,reason='goal')
        p=plan_timeline([c],20,True,True,.5)
        self.assertEqual(p['duration'],13)
        self.assertEqual(len(p['segments']),1)
        self.assertTrue(p['notes'])
    def test_drop_audio_before_goal_replay(self):
        clips=[dict(start=0,end=10,kind='goal',goal_at=5),dict(start=40,end=50,reason='audio')]
        p=plan_timeline(clips,30,True,True,.5)
        self.assertEqual(p['duration'],27)
        self.assertTrue(p['segments'][1]['is_replay'])
    def test_atomic_two_file_folder_and_no_overwrite(self):
        def render(video,music,clips,output,**opts):Path(output).write_bytes(b'test-video')
        with tempfile.TemporaryDirectory() as tmp,patch('core.render',render):
            a=publishing.export_package(tmp,'x',None,[],'Ақтөбе','Ордабасы','1:3')
            b=publishing.export_package(tmp,'x',None,[],'Ақтөбе','Ордабасы','1:3')
            self.assertNotEqual(a['directory'],b['directory'])
            self.assertEqual({p.suffix for p in Path(a['directory']).iterdir()},{'.mp4','.txt'})
            self.assertEqual(len(list(Path(a['directory']).iterdir())),2)
    def test_failed_export_leaves_no_partial_folder(self):
        with tempfile.TemporaryDirectory() as tmp,patch('core.render',side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):publishing.export_package(tmp,'x',None,[],'A','B','0:0')
            self.assertFalse(list((Path(tmp)/'output').iterdir()))
if __name__=='__main__':unittest.main()
