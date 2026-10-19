import copy
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from PIL import Image
import camera
import core
from channel_templates import TemplateStore
from review_model import ReviewModel
from timeline import plan_timeline
from batch_queue import BatchQueue
import visuals
import workflow


class EditingTests(unittest.TestCase):
    def test_reorder_changes_export_order_and_undo_restores_it(self):
        model=ReviewModel([dict(start=0,end=5),dict(start=20,end=25)],30)
        model.move(0,1)
        planned=plan_timeline(model.clips,30,False,False)
        self.assertEqual([c['start'] for c in planned['segments']],[20,0])
        model.undo();self.assertEqual([c['start'] for c in model.clips],[0,20])

    def test_trim_does_not_silently_remove_second_merged_goal(self):
        model=ReviewModel([dict(start=0,end=15,kind='goal',goal_at=4,goal_times=[4,12])],30)
        with self.assertRaises(ValueError):model.trim(0,0,10)
        self.assertEqual(model.clips[0]['end'],15)
        model.clear_goal(0);model.trim(0,0,10);self.assertNotIn('goal_times',model.clips[0])


class ChannelTests(unittest.TestCase):
    def test_assets_are_copied_portable_and_authentication_is_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);base=root/'app';base.mkdir();logo=root/'logo.png';music=root/'song.wav'
            Image.new('RGB',(20,20),'blue').save(logo);music.write_bytes(b'song')
            settings=dict(intro=False,show_final=False,youtube_browser='chrome',youtube_cookie_file='private cookies.txt',
                          channel_style=dict(brand_name='ExampleChannel',brand_logo=str(logo),accent_color='#00ff00'))
            store=TemplateStore(base);record=store.save('Арна',settings,str(music))
            self.assertNotIn('youtube_browser',record['settings']);self.assertNotIn('youtube_cookie_file',record['settings'])
            self.assertFalse(record['settings']['show_final'])
            logo.unlink();music.unlink();moved=root/'moved app';shutil.move(base,moved)
            record=TemplateStore(moved).get('Арна')
            self.assertTrue(Path(record['settings']['channel_style']['brand_logo']).is_file())
            self.assertEqual(Path(record['music_file']).read_bytes(),b'song')
            saved_logo=Path(record['settings']['channel_style']['brand_logo'])
            TemplateStore(moved).delete('Арна');self.assertTrue(saved_logo.exists())

    def test_project_branding_survives_template_source_removal_and_project_move(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'project';(folder/'source').mkdir(parents=True)
            (folder/'source/original.mp4').touch();logo=root/'logo.png';Image.new('RGB',(10,10),'blue').save(logo)
            project=dict(kind='football_project',directory=str(folder),source_file='source/original.mp4',
                         settings={'channel_style':{'brand_logo':str(logo)}},title='A — B')
            workflow.stage_style(project);workflow.save_project(project);logo.unlink()
            moved=root/'moved';shutil.move(folder,moved);loaded=workflow.load_project(moved)
            self.assertTrue(Path(workflow.project_style(loaded)['brand_logo']).is_file())

    def test_selected_colors_and_logo_are_in_rendered_card(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);logo=root/'logo.png';Image.new('RGB',(20,20),'blue').save(logo)
            output=root/'card.png'
            visuals.card(output,'A — B',style=dict(panel_color='#ff0000',accent_color='#00ff00',brand_logo=str(logo)))
            with Image.open(output) as im:
                self.assertEqual(im.getpixel((40,120))[:3],(255,0,0))
                self.assertEqual(im.getpixel((40,1182))[:3],(0,0,255))

    def test_font_is_copied_and_bad_color_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=getattr(visuals.font(20),'path',None)
            if not path:self.skipTest('No TrueType font on host')
            record=TemplateStore(d).save('Font',{'channel_style':{'font_file':str(path)}})
            self.assertTrue(Path(record['settings']['channel_style']['font_file']).is_file())
            with self.assertRaises(ValueError):TemplateStore(d).save('Bad',{'channel_style':{'accent_color':'red; invalid'}})


class TrackingTests(unittest.TestCase):
    def test_crop_must_keep_goal_posts_visible(self):
        regions=[(.7,.2,.9,.5)]
        self.assertTrue(camera.goal_fits_crop(regions,.8,.27))
        self.assertFalse(camera.goal_fits_crop(regions,.4,.27))

    def test_post_geometry_does_not_treat_white_dot_as_goal(self):
        frame=np.full((360,640,3),(35,125,35),np.uint8)
        cv2.line(frame,(440,80),(560,80),(255,255,255),3)
        cv2.line(frame,(440,80),(440,140),(255,255,255),3)
        cv2.line(frame,(560,80),(560,140),(255,255,255),3)
        self.assertTrue(camera.goal_regions(frame))
        self.assertFalse(camera.goal_regions(self.frame(300)))

    def frame(self,x):
        frame=np.full((360,640,3),(35,125,35),np.uint8)
        cv2.circle(frame,(x,210),4,(255,255,255),-1)
        cv2.circle(frame,(570,210),4,(255,255,255),-1)
        return frame

    def test_motion_and_history_prefer_moving_ball_over_static_white_spot(self):
        tracker=camera.BallTracker();points=[]
        for i in range(12):points.append(tracker.update(self.frame(290+i*7),i*.25))
        self.assertLess(abs(points[-1][0]-367/640),.02)
        self.assertTrue(points[-1][1])

    def test_lost_ball_does_not_jump_to_distant_white_spot(self):
        tracker=camera.BallTracker()
        for i in range(8):tracker.update(self.frame(290+i*7),i*.25)
        frame=np.full((360,640,3),(35,125,35),np.uint8);cv2.circle(frame,(570,210),4,(255,255,255),-1)
        x,found=tracker.update(frame,2)
        self.assertFalse(found);self.assertLess(x,.65)

    def test_reacquired_static_object_requires_fresh_motion(self):
        tracker=camera.BallTracker()
        for i in range(8):tracker.update(self.frame(290+i*7),i*.25)
        blank=np.full((360,640,3),(35,125,35),np.uint8)
        for i in range(8,20):tracker.update(blank,i*.25)
        for i in range(20,32):x,found=tracker.update(self.frame(340),i*.25)
        self.assertFalse(found)


class ResumeTests(unittest.TestCase):
    def analysis(self,*args,**kwargs):return dict(score='1:0',clips=[dict(start=0,end=2,reason='audio')],warnings=[])
    def render(self,video,music,clips,output,**kwargs):Path(output).write_bytes(b'rendered')

    def test_cancel_after_source_resumes_without_download(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'A — B.mp4';video.write_bytes(b'source');checkpoints=[]
            with patch('workflow.core.analyze',side_effect=core.Cancelled()):
                with self.assertRaises(core.Cancelled):workflow.create_project(d,local_video=str(video),on_checkpoint=checkpoints.append,log=lambda _:None)
            directory=checkpoints[-1]['directory'];self.assertEqual(checkpoints[-1]['stage'],'source')
            with patch('workflow.downloader.download',side_effect=AssertionError('must reuse source')),patch('workflow.core.analyze',side_effect=self.analysis),patch('workflow.core.render',side_effect=self.render):
                result=workflow.resume_project(directory,log=lambda _:None)
            self.assertEqual(result['project']['status'],'ready');self.assertEqual(len(workflow.recent_projects(d)),1)

    def test_failed_download_reuses_registered_project_directory(self):
        with tempfile.TemporaryDirectory() as d:
            checkpoints=[]
            with patch('workflow.downloader.download',side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):workflow.create_project(d,url='https://youtu.be/so5hJv_2cVQ',on_checkpoint=checkpoints.append,log=lambda _:None)
            def download(url,folder,*args,**kwargs):
                path=Path(folder)/'download.mp4';path.write_bytes(b'source');return dict(path=str(path),title='A — B')
            with patch('workflow.downloader.download',side_effect=download),patch('workflow.core.analyze',side_effect=self.analysis),patch('workflow.core.render',side_effect=self.render):workflow.resume_project(checkpoints[0]['directory'],log=lambda _:None)
            self.assertEqual(len(workflow.recent_projects(d)),1)

    def test_changed_score_does_not_reuse_stale_montage(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'A — B.mp4';video.write_bytes(b'source');checkpoints=[]
            with patch('workflow.core.analyze',side_effect=self.analysis),patch('workflow.core.render',side_effect=self.render),patch('workflow.commit_outputs',side_effect=core.Cancelled()):
                with self.assertRaises(core.Cancelled):workflow.create_project(d,local_video=str(video),on_checkpoint=checkpoints.append,log=lambda _:None)
            with patch('workflow.core.render',side_effect=self.render) as render:
                workflow.rerender(checkpoints[-1]['directory'],'2:1',log=lambda _:None)
            render.assert_called_once();self.assertEqual(render.call_args.kwargs['score'],'2:1')

    def test_resume_after_analysis_skips_both_download_and_analyze(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'A — B.mp4';video.write_bytes(b'source');checkpoints=[]
            with patch('workflow.core.analyze',side_effect=self.analysis),patch('workflow.core.render',side_effect=core.Cancelled()):
                with self.assertRaises(core.Cancelled):workflow.create_project(d,local_video=str(video),on_checkpoint=checkpoints.append,log=lambda _:None)
            with patch('workflow.core.analyze',side_effect=AssertionError('must reuse analysis')),patch('workflow.core.render',side_effect=self.render):
                result=workflow.resume_project(checkpoints[-1]['directory'],log=lambda _:None)
            self.assertEqual(result['project']['status'],'ready')

    def test_finished_montage_is_reused_after_save_interruption(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'A — B.mp4';video.write_bytes(b'source');checkpoints=[]
            with patch('workflow.core.analyze',side_effect=self.analysis),patch('workflow.core.render',side_effect=self.render),patch('workflow.commit_outputs',side_effect=core.Cancelled()):
                with self.assertRaises(core.Cancelled):workflow.create_project(d,local_video=str(video),on_checkpoint=checkpoints.append,log=lambda _:None)
            with patch('workflow.core.metadata',return_value={'duration':2}),patch('workflow.core.render',side_effect=AssertionError('must reuse montage')),patch('workflow.core.analyze',side_effect=AssertionError('must reuse analysis')):
                result=workflow.resume_project(checkpoints[-1]['directory'],log=lambda _:None)
            self.assertEqual(result['project']['status'],'ready')

    def test_renamed_project_is_recovered_by_id_after_stale_queue_path(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'A — B.mp4';video.write_bytes(b'source');checkpoints=[]
            with patch('workflow.core.analyze',side_effect=core.Cancelled()):
                with self.assertRaises(core.Cancelled):workflow.create_project(d,local_video=str(video),on_checkpoint=checkpoints.append,log=lambda _:None)
            self.assertFalse(Path(checkpoints[0]['directory']).exists())
            self.assertEqual(workflow.resolve_checkpoint(d,checkpoints[0]),Path(checkpoints[-1]['directory']))

    def test_completed_result_is_not_encoded_again_after_queue_crash(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'A — B.mp4';video.write_bytes(b'source')
            with patch('workflow.core.analyze',side_effect=self.analysis),patch('workflow.core.render',side_effect=self.render):r=workflow.create_project(d,local_video=str(video),log=lambda _:None)
            with patch('workflow.core.render',side_effect=AssertionError('already done')):
                self.assertEqual(workflow.resume_project(r['directory'],log=lambda _:None)['video'],r['video'])

    def test_queue_eta_uses_measured_completed_job_and_checkpoint_is_persistent(self):
        with tempfile.TemporaryDirectory() as d:
            now=[0.];q=BatchQueue(Path(d)/'queue.json',clock=lambda:now[0])
            q.add('https://youtu.be/so5hJv_2cVQ\nhttps://youtu.be/ll8-Gm7CgPs')
            self.assertIsNone(q.summary()['eta_seconds'])
            def process(url):
                q.checkpoint(url,dict(directory='saved',project_id='id',stage='source'))
                now[0]+=10
                if url.endswith('ll8-Gm7CgPs'):raise core.Cancelled()
                return dict(directory='saved',project={'title':'A — B'})
            q.run(process,threading.Event());q.retry_failed()
            self.assertEqual(q.summary()['eta_seconds'],10)
            restored=BatchQueue(q.path);self.assertEqual(restored.items[1]['project_id'],'id')
