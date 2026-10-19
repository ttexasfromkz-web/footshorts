"""Real decoder, export and Tk controls exercised on the Windows CI runner."""
import copy
import os
from pathlib import Path
import queue
import shutil
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import cv2
import core
import workflow
from playback import PreviewPlayer


@unittest.skipUnless(os.environ.get('FOOTSHORTS_GUI_TESTS')=='1','Windows GUI integration job')
class WindowsReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name)
        source=cls.folder/'source';source.mkdir()
        cls.video=source/'original.mp4'
        core.run([core.ffmpeg(),'-v','error','-f','lavfi','-i','color=c=green:s=960x540:r=30:d=4',
            '-f','lavfi','-i','sine=frequency=440:duration=4',
            '-vf','drawbox=x=0:y=0:w=320:h=540:color=red:t=fill,drawbox=x=640:y=0:w=320:h=540:color=blue:t=fill',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest','-y',cls.video])
        cls.project=dict(kind='football_project',schema_version=1,directory=str(cls.folder),title='A — B',
            score='2:1',source_file='source/original.mp4',music_file='',settings={**workflow.DEFAULTS,'intro':False,'crop_top':0},
            clips=[dict(start=0,end=2,reason='audio'),dict(start=2,end=4,reason='audio')],
            video_file='result.mp4',text_file='result.txt',status='ready',revision=1)
        shutil.copy2(cls.video,cls.folder/'result.mp4')
        workflow.save_project(cls.project)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_decoder_clock_seeking_and_audio_cleanup(self):
        now=[10.]
        player=PreviewPlayer(self.video,clock=lambda:now[0],audio=False)
        try:
            player.seek(1);self.assertIsNotNone(player.frame())
            player.play();now[0]+=.5;self.assertAlmostEqual(player.position(),1.5)
            player.pause();now[0]+=1;self.assertAlmostEqual(player.position(),1.5)
            player.seek(3);self.assertIsNotNone(player.frame())
        finally:player.close()
        self.assertFalse(player.capture.isOpened())
        audio=PreviewPlayer(self.video,audio=True)
        try:
            audio.play();time.sleep(.15)
            self.assertIsNotNone(audio.audio,audio.audio_error)
            self.assertFalse(audio.audio.failure())
            audio.seek(1);audio.pause()
            self.assertIsNotNone(audio.audio,audio.audio_error)
            self.assertFalse(audio.audio.failure())
        finally:audio.close()
        fallback=PreviewPlayer(self.video,audio=True)
        try:
            with patch('audio_process.AudioProcess',side_effect=RuntimeError('audio unavailable')):
                fallback.play()
            self.assertIn('audio unavailable',fallback.audio_error)
            self.assertIsNotNone(fallback.frame())
        finally:fallback.close()

    def test_review_controls_save_goal_trim_and_focus(self):
        import tkinter as tk
        from review_ui import ReviewWindow
        root=tk.Tk();root.geometry('1000x740');root.update()
        saved=Mock();closed=Mock();window=None
        try:
            project=copy.deepcopy(self.project)
            window=ReviewWindow(root,project,saved,closed,audio=False);root.update()
            window.player.seek(1.2);window.mark_goal()
            self.assertAlmostEqual(window.model.clips[0]['goal_at'],1.2)
            window.start_text.set('00:00.50');window.end_text.set('00:01.90');window.apply_trim()
            window.player.seek(1.2);window.draw();window.focus_mode.set(True)
            x,y,w,h=window.image_box
            window.focus_click(SimpleNamespace(x=x+w*.3,y=y+h*.5))
            self.assertAlmostEqual(window.model.clips[0]['focus_points'][0]['x'],.3,places=3)
            window.zoom.set('1.3');window.apply_zoom()
            window.save(False);window=None
            saved.assert_called_once();closed.assert_called_once()
            p=workflow.load_project(self.folder)
            self.assertAlmostEqual(p['clips'][0]['start'],.5)
            self.assertAlmostEqual(p['clips'][0]['zoom'],1.3)
            self.assertAlmostEqual(p['clips'][0]['goal_at'],1.2)
            self.assertTrue(p['clips'][0]['focus_points'])
            self.assertTrue((self.folder/'result.mp4').is_file())
        finally:
            if window and window.alive:window.shutdown()
            root.destroy()

    def test_review_result_mode_selection_delete_and_undo(self):
        import tkinter as tk
        from review_ui import ReviewWindow
        root=tk.Tk();root.update();window=None
        try:
            window=ReviewWindow(root,copy.deepcopy(self.project),Mock(),Mock(),audio=False)
            window.open_video('result');self.assertEqual(window.mode,'result')
            window.listbox.selection_clear(0,'end');window.listbox.selection_set(0);window.select_clip()
            self.assertEqual(window.mode,'source')
            window.delete_clip();self.assertEqual(len(window.model.clips),1)
            window.undo();self.assertEqual(len(window.model.clips),2)
            window.play_clip();initial=window.player.position()
            for _ in range(4):time.sleep(.05);root.update()
            self.assertGreater(window.player.position(),initial+.1)
            window.player.seek(window.model.clips[0]['end']+.1)
            time.sleep(.05);root.update()
            self.assertFalse(window.player.playing)
        finally:
            if window:window.shutdown()
            root.destroy()

    def test_batch_window_processes_past_error(self):
        import tkinter as tk
        from batch_ui import BatchWindow
        from batch_queue import BatchQueue
        root=tk.Tk();root.update();window=None
        root.busy=False;root.review_open=False;root.cancel_event=threading.Event()
        root.app_base=self.folder;root.settings=lambda:copy.deepcopy(self.project['settings'])
        root.music=tk.StringVar(value='');root.jobs=queue.Queue();root.log=Mock()
        root.project_ready=Mock();root.status=tk.StringVar()
        root.start=lambda fn,callback:callback(fn())
        try:
            model=BatchQueue(self.folder/'queue-test.json');window=BatchWindow(root,model)
            window.urls.insert('1.0','https://youtu.be/so5hJv_2cVQ\nhttps://youtu.be/ll8-Gm7CgPs')
            window.add()
            with patch('workflow.create_project',side_effect=[RuntimeError('first failed'),
                    dict(directory=str(self.folder),project={'title':'A — B'})]):
                window.run()
            self.assertEqual([i['status'] for i in model.snapshot()],['error','done'])
            self.assertEqual(len(window.table.get_children()),2)
            root.project_ready.assert_called_once()
        finally:
            if window:window.destroy()
            root.destroy()

    def test_real_export_follows_manual_points_in_main_and_replay(self):
        output=self.folder/'manual-export.mp4'
        clip=dict(start=0,end=4,kind='goal',goal_at=2,
            focus_points=[dict(time=0,x=.17,y=.5),dict(time=3.9,x=.83,y=.5)],zoom=1)
        core.render(str(self.video),None,[clip],output,title='A — B',score='',crop_top=0,intro=False,
                    show_final=False,replays=True,action_camera=True,max_seconds=30,log=lambda _:None)
        self.assertAlmostEqual(core.metadata(output)['duration'],12,delta=.12)
        cap=cv2.VideoCapture(str(output))
        try:
            for t,red in [(.2,True),(3.8,False),(4.4,True),(11.6,False)]:
                cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read();self.assertTrue(ok)
                color=frame[600:660,320:400].mean(axis=(0,1))
                self.assertGreater(color[2] if red else color[0],150)
                self.assertLess(color[0] if red else color[2],80)
        finally:cap.release()

    def test_final_score_toggle_changes_actual_video_ending(self):
        for enabled in (True,False):
            output=self.folder/('final-score-'+str(enabled)+'.mp4')
            with patch('core.make_card',wraps=core.make_card) as card:
                core.render(str(self.video),None,[dict(start=0,end=2,reason='audio')],output,
                            title='A — B',score='2:1',crop_top=0,intro=False,show_final=enabled,
                            replays=False,action_camera=False,max_seconds=10,log=lambda _:None)
                self.assertEqual(sum(len(c.args)>4 and c.args[4] for c in card.call_args_list),1 if enabled else 0)
            self.assertAlmostEqual(core.metadata(output)['duration'],5 if enabled else 2,delta=.15)

    def test_montage_reorder_is_visible_in_encoded_video(self):
        source=self.folder/'two-colors.mp4';output=self.folder/'reordered.mp4'
        core.run([core.ffmpeg(),'-v','error','-f','lavfi','-i','color=c=red:s=320x180:r=30:d=2',
                  '-f','lavfi','-i','color=c=blue:s=320x180:r=30:d=2','-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
                  '-map','[v]','-c:v','libx264','-pix_fmt','yuv420p','-y',source])
        core.render(str(source),None,[dict(start=2,end=4,reason='Шабуыл'),dict(start=0,end=2,reason='Шабуыл')],output,
                    intro=False,show_final=False,replays=False,action_camera=False,crop_top=0,max_seconds=10,log=lambda _:None)
        cap=cv2.VideoCapture(str(output))
        try:
            for t,channel in [(.5,0),(2.5,2)]:
                cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read();self.assertTrue(ok)
                color=frame[600:660,320:400].mean(axis=(0,1));self.assertGreater(color[channel],150)
        finally:cap.release()

    def test_uncertain_automatic_camera_keeps_entire_pitch(self):
        output=self.folder/'camera-fallback.mp4'
        with patch('camera.track_details',return_value=dict(points=[(0,.9)],safe_crop=False)):
            core.render(str(self.video),None,[dict(start=0,end=2,reason='Шабуыл')],output,intro=False,
                        show_final=False,replays=False,action_camera=True,crop_top=0,max_seconds=10,log=lambda _:None)
        cap=cv2.VideoCapture(str(output))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC,500);ok,frame=cap.read();self.assertTrue(ok)
            self.assertGreater(frame[600:660,80:140,2].mean(),150)
            self.assertGreater(frame[600:660,580:640,0].mean(),150)
        finally:cap.release()

    def test_no_zoom_keeps_both_sides_even_with_saved_manual_zoom(self):
        output=self.folder/'no-zoom-export.mp4'
        clip=dict(start=0,end=4,kind='highlight',
            focus_points=[dict(time=0,x=.17,y=.5)],zoom=2)
        with patch('camera.track',side_effect=AssertionError('No zoom must not track')):
            core.render(str(self.video),None,[clip],output,title='A — B',score='',crop_top=0,intro=False,
                        show_final=False,replays=False,action_camera=False,max_seconds=30,log=lambda _:None)
        cap=cv2.VideoCapture(str(output))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC,1000);ok,frame=cap.read();self.assertTrue(ok)
            red=frame[600:660,80:140].mean(axis=(0,1))
            blue=frame[600:660,580:640].mean(axis=(0,1))
            self.assertGreater(red[2],150);self.assertLess(red[0],80)
            self.assertGreater(blue[0],150);self.assertLess(blue[2],80)
        finally:cap.release()
