import copy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import core
import camera
from batch_queue import BatchQueue
from review_model import ReviewModel


class ReviewTests(unittest.TestCase):
    def clip(self):
        return dict(start=0,end=10,reason='audio',focus_points=[dict(time=1,x=.2,y=.4),dict(time=9,x=.8,y=.6)])

    def test_trim_preserves_camera_path_and_undo(self):
        model=ReviewModel([self.clip()],30);original=copy.deepcopy(model.clips)
        model.trim(0,2,8)
        points=model.clips[0]['focus_points']
        self.assertAlmostEqual(points[0]['x'],.275)
        self.assertAlmostEqual(points[-1]['x'],.724925,places=5)
        self.assertTrue(all(2<=p['time']<8 for p in points))
        model.undo();self.assertEqual(model.clips,original)

    def test_goal_and_invalid_boundary_do_not_lose_edits(self):
        model=ReviewModel([self.clip()],30);model.mark_goal(0,5)
        before=copy.deepcopy(model.clips)
        with self.assertRaises(ValueError):model.trim(0,6,9)
        self.assertEqual(model.clips,before)
        model.clear_goal(0);self.assertNotIn('goal_at',model.clips[0])
        model.delete(0);self.assertEqual(model.clips,[])
        model.undo();self.assertEqual(len(model.clips),1)

    def test_manual_points_reject_invalid_and_replace_same_frame(self):
        model=ReviewModel([dict(start=0,end=5)],10)
        model.focus(0,2,.3,.4);model.focus(0,2.01,.7,.5)
        self.assertEqual(len(model.clips[0]['focus_points']),1)
        with self.assertRaises(ValueError):model.focus(0,6,.3,.5)
        with self.assertRaises(ValueError):model.focus(0,2,2,.5)

    def test_manual_replay_uses_absolute_source_times(self):
        clip=dict(start=3,end=7,zoom=1.3,focus_points=[dict(time=0,x=.2,y=.3),dict(time=10,x=.8,y=.7)])
        xs,ys=camera.manual_tracks(clip,540,80,460)
        self.assertAlmostEqual(xs[0][1],.38)
        self.assertAlmostEqual(xs[-1][1],.62)
        self.assertIn('8.000',camera.crop_expression(xs,960,240,.5))
        rect=camera.manual_rectangle(clip,5,960,540,.15)
        self.assertGreaterEqual(rect[0],0);self.assertGreaterEqual(rect[1],80)
        self.assertLessEqual(rect[0]+rect[2],960);self.assertLessEqual(rect[1]+rect[3],540)

    def test_text_editor_preserves_saved_camera_points(self):
        import app
        from types import SimpleNamespace
        original=self.clip();original['zoom']=1.2
        ui=SimpleNamespace(clip_details={(0,10):original})
        clips=app.App.parse(ui,'00:00 - 00:10 | Гол | goal=00:05')
        self.assertEqual(clips[0]['focus_points'],original['focus_points'])
        self.assertEqual(clips[0]['zoom'],1.2);self.assertEqual(clips[0]['goal_at'],5)


class BatchTests(unittest.TestCase):
    URL1='https://youtu.be/so5hJv_2cVQ'
    URL2='https://youtu.be/ll8-Gm7CgPs'

    def test_failure_does_not_stop_next_match(self):
        with tempfile.TemporaryDirectory() as d:
            model=BatchQueue(Path(d)/'queue.json');model.add(self.URL1+'\n'+self.URL2)
            calls=[]
            def process(url):
                calls.append(url)
                if len(calls)==1:raise RuntimeError('first failed')
                return dict(directory='match2',project={'title':'A — B'})
            results=model.run(process,threading.Event())
            self.assertEqual(len(calls),2);self.assertEqual(len(results),1)
            self.assertEqual([i['status'] for i in model.snapshot()],['error','done'])
            again=BatchQueue(Path(d)/'queue.json')
            self.assertEqual(again.snapshot(),model.snapshot())

    def test_cancel_keeps_remaining_jobs_queued(self):
        with tempfile.TemporaryDirectory() as d:
            model=BatchQueue(Path(d)/'queue.json');model.add(self.URL1+'\n'+self.URL2)
            def process(url):raise core.Cancelled()
            model.run(process,threading.Event())
            self.assertEqual([i['status'] for i in model.snapshot()],['cancelled','queued'])
            model.retry_failed()
            self.assertTrue(all(i['status']=='queued' for i in model.snapshot()))

    def test_duplicate_links_and_bad_input(self):
        with tempfile.TemporaryDirectory() as d:
            model=BatchQueue(Path(d)/'queue.json')
            model.add(self.URL1+'\n'+self.URL1+'\nnot a video')
            self.assertEqual(len(model.snapshot()),2)
            self.assertEqual(model.snapshot()[1]['status'],'error')
