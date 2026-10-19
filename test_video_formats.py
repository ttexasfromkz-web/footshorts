import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import core
import publishing
import visuals
import workflow
from channel_templates import TemplateStore
from review_model import ReviewModel
from timeline import plan_timeline
from video_formats import dimensions,limit_seconds,analysis_target


class VideoFormatTests(unittest.TestCase):
    def test_duration_policy_is_separate_for_each_format(self):
        self.assertEqual(dimensions('shorts'),(720,1280))
        self.assertEqual(dimensions('landscape'),(1280,720))
        self.assertEqual(analysis_target({'output_format':'landscape','intro':True}),297)
        self.assertIsNone(analysis_target({'output_format':'landscape','target':None}))
        for value in (None,181,float('inf'),float('nan')):
            with self.assertRaises(ValueError):limit_seconds(value,'shorts')
        for value in (0,-1,float('inf'),float('nan')):
            with self.assertRaises(ValueError):limit_seconds(value,'landscape')

    def test_long_and_unlimited_timelines_include_complete_footage(self):
        clips=[dict(start=0,end=200,kind='goal',goal_at=100),dict(start=210,end=390,priority=2)]
        wide=plan_timeline(clips,300,True,False,intro_seconds=3,output_format='landscape')
        self.assertEqual(wide['duration'],206);self.assertEqual(len(wide['segments']),1)
        full=plan_timeline(clips,None,True,False,intro_seconds=3,output_format='landscape')
        self.assertEqual(full['duration'],386);self.assertEqual(len(full['segments']),2)
        with self.assertRaises(ValueError):plan_timeline(clips,180,True,False)
        self.assertEqual(ReviewModel(clips,400,'landscape').validate(),clips)
        with self.assertRaises(ValueError):ReviewModel(clips,400).validate()

    def test_analysis_selection_does_not_keep_the_old_three_minute_cap(self):
        goals=[dict(start=i*25,end=i*25+17,priority=100,kind='goal',goal_at=i*25+8) for i in range(20)]
        with patch('core.metadata',return_value={'duration':1000}),patch('core.confirmed_goal_candidates',return_value=goals),patch('core.run',side_effect=RuntimeError('No audio in fixture')),patch('highlight_signals.inspect_candidates',side_effect=lambda video,candidates,*_:candidates):
            wide=core.analyze('fixture',target=300,use_ocr=False,output_format='landscape',log=lambda _:None)
            full=core.analyze('fixture',target=None,use_ocr=False,output_format='landscape',log=lambda _:None)
        duration=sum(c['end']-c['start'] for c in wide['clips'])
        self.assertGreater(duration,180);self.assertLessEqual(duration,300)
        self.assertEqual(len(full['clips']),20)

    def test_youtube_copy_omits_music_source_and_short_tags_in_long_format(self):
        for code in ('kk','ru','en'):
            for output_format in ('shorts','landscape'):
                text=publishing.youtube_text('North FC','South FC','2:1','https://example.com/original','Stadium_Ignition',code,output_format)
                self.assertNotIn('Stadium_Ignition',text);self.assertNotIn('https://example.com/original',text)
                if output_format=='landscape':
                    self.assertNotIn('shorts',text.lower());self.assertNotIn('шортс',text.lower())
                else:self.assertIn('#Shorts',text)

    def test_workflow_defaults_to_five_minutes_and_preserves_unlimited_on_resume(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d,'source.mp4');source.write_bytes(b'source');checkpoints=[]
            analysis=dict(score='2:1',clips=[dict(start=0,end=2,reason='fixture')],warnings=[])
            def render(*args,**kw):Path(args[3]).write_bytes(b'wide')
            with patch('workflow.core.analyze',return_value=analysis) as analyze,patch('workflow.core.render',side_effect=render) as export:
                result=workflow.create_project(d,local_video=str(source),title_hint='A — B',settings={'output_format':'landscape'},log=lambda _:None)
                self.assertEqual(result['project']['settings']['target'],300)
                self.assertEqual(analyze.call_args.args[1],297)
                self.assertEqual(export.call_args.kwargs['output_format'],'landscape')
            with patch('workflow.core.analyze',return_value=analysis),patch('workflow.core.render',side_effect=core.Cancelled()):
                with self.assertRaises(core.Cancelled):
                    workflow.create_project(d,local_video=str(source),title_hint='A — B',settings={'output_format':'landscape','target':None},on_checkpoint=checkpoints.append,log=lambda _:None)
            with patch('workflow.core.analyze',side_effect=AssertionError('reuse analysis')),patch('workflow.core.render',side_effect=render) as export:
                result=workflow.resume_project(checkpoints[-1]['directory'],log=lambda _:None)
                self.assertIsNone(export.call_args.kwargs['max_seconds'])
                self.assertEqual(export.call_args.kwargs['output_format'],'landscape')
                self.assertIsNone(workflow.load_project(result['directory'])['settings']['target'])

    def test_template_and_graphics_use_native_widescreen_geometry(self):
        with tempfile.TemporaryDirectory() as d:
            record=TemplateStore(d).save('Long video',{'output_format':'landscape','target':None})
            self.assertEqual(record['settings']['output_format'],'landscape');self.assertIsNone(record['settings']['target'])
            for code in ('kk','ru','en'):
                files=visuals.intro_layers(d,'North FC — South FC',[],language=code,output_format='landscape')
                final=Path(d,'final.png');visuals.card(final,'North FC — South FC','2:1',final=True,language=code,output_format='landscape')
                for path in (*files,final):
                    with Image.open(path) as im:self.assertEqual(im.size,(1280,720))


@unittest.skipUnless(os.environ.get('FOOTSHORTS_GUI_TESTS')=='1','Native media integration job')
class WideRenderTests(unittest.TestCase):
    def test_actual_widescreen_intro_goal_replay_final_preserves_full_pitch(self):
        import cv2
        with tempfile.TemporaryDirectory() as d:
            source=Path(d,'source.mp4');out=Path(d,'wide.mp4')
            core.run([core.ffmpeg(),'-v','error','-f','lavfi','-i','color=c=green:s=320x180:r=30:d=4',
                      '-vf','drawbox=x=0:y=0:w=80:h=180:color=red:t=fill,drawbox=x=240:y=0:w=80:h=180:color=blue:t=fill',
                      '-c:v','libx264','-pix_fmt','yuv420p','-y',source])
            clip=dict(start=0,end=4,kind='goal',goal_at=2,zoom=2,focus_points=[dict(time=0,x=.9,y=.5)])
            with patch('logos.pair',return_value=[]),patch('camera.track_details',side_effect=AssertionError('Wide must keep full field')):
                core.render(str(source),None,[clip],out,title='A — B',score='2:1',language='en',output_format='landscape',
                            action_camera=True,crop_top=.3,max_seconds=300,log=lambda _:None)
            info=core.metadata(out);self.assertEqual((info['width'],info['height']),(1280,720))
            self.assertAlmostEqual(info['duration'],18,delta=.15)
            cap=cv2.VideoCapture(str(out))
            try:
                for sec in (3.5,8):
                    cap.set(cv2.CAP_PROP_POS_MSEC,sec*1000);ok,frame=cap.read();self.assertTrue(ok)
                    self.assertGreater(frame[250:300,40:120,2].mean(),150)
                    self.assertGreater(frame[250:300,1160:1240,0].mean(),150)
            finally:cap.release()

    def test_actual_unlimited_export_passes_three_minutes(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d,'source.mp4');out=Path(d,'long.mp4')
            core.run([core.ffmpeg(),'-v','error','-f','lavfi','-i','color=c=green:s=160x90:r=30:d=184',
                      '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-y',source])
            core.render(str(source),None,[dict(start=0,end=183,kind='highlight')],out,
                        output_format='landscape',max_seconds=None,intro=False,show_final=False,replays=False,log=lambda _:None)
            info=core.metadata(out);self.assertEqual((info['width'],info['height']),(1280,720))
            self.assertAlmostEqual(info['duration'],183,delta=.2)
