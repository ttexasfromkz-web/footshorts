import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import ImageDraw
import content_language as language
import publishing
import visuals
import workflow
from channel_templates import TemplateStore


class ContentLanguageTests(unittest.TestCase):
    def test_source_title_language_does_not_choose_output_language(self):
        for code,heading,score in [('kk','ВИДЕО АТАУЫ','Есеп'),('ru','НАЗВАНИЕ ВИДЕО','Счёт'),('en','VIDEO TITLE','Score')]:
            with self.subTest(language=code):
                text=publishing.youtube_text('North FC','South FC','2:1','https://example.com/video','Music',code)
                self.assertTrue(text.startswith(heading+'\n'))
                self.assertIn(score+': 2:1',text)
                self.assertIn(language.strings(code)['highlights'],text)
                self.assertNotIn('Music',text);self.assertNotIn('https://example.com/video',text)
                self.assertIn('North FC — South FC',text)
                self.assertLessEqual(len(text.splitlines()[1]),100)
                self.assertLessEqual(len(text.split(language.strings(code)['tags']+'\n')[1].strip()),500)
                if code=='en':self.assertFalse(any('\u0400'<=ch<='\u04ff' for ch in text))

    def test_unknown_teams_score_and_logo_credits_are_localized(self):
        with tempfile.TemporaryDirectory() as d:
            for code in language.LANGUAGES.values():
                p=dict(title='Unidentified video',score=None,settings={'language':code},directory=d)
                text=workflow.project_text(p);t=language.strings(code)
                self.assertIn(t['unknown_score'],text);self.assertIn(t['unknown_teams'],text)
                self.assertIn(t['score']+': '+t['unknown'],text)
                self.assertNotIn(t['score']+': 0:0',text)
                folder=Path(d,'source/logos');folder.mkdir(parents=True,exist_ok=True)
                (folder/'credit.json').write_text(json.dumps(dict(name='North FC',source='https://example.com/logo')))
                p.update(title='North FC — South FC',score='2:1')
                self.assertIn(t['logo_sources'],workflow.project_text(p))

    def test_language_persists_in_templates_and_export_package(self):
        with tempfile.TemporaryDirectory() as d:
            TemplateStore(d).save('English channel',dict(language='en'))
            self.assertEqual(TemplateStore(d).get('English channel')['settings']['language'],'en')
            def render(*args,**kw):Path(args[3]).write_bytes(b'video')
            with patch('core.render',side_effect=render) as export:
                result=publishing.export_package(d,'source',None,[],'North FC','South FC','2:1',language='ru')
            self.assertEqual(export.call_args.kwargs['language'],'ru')
            self.assertIn('Счёт: 2:1',Path(result['text']).read_text(encoding='utf-8-sig'))

    def test_language_change_rerenders_without_downloading_or_analyzing(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d,'original.mp4');source.write_bytes(b'source')
            def render(*args,**kw):Path(args[3]).write_bytes(kw['language'].encode())
            analysis=dict(score='2:1',clips=[dict(start=0,end=2)],warnings=[])
            with patch('workflow.core.analyze',return_value=analysis) as analyze,patch('workflow.core.render',side_effect=render) as export,patch('workflow.downloader.download') as download:
                result=workflow.create_project(d,local_video=str(source),title_hint='North FC — South FC',settings={'language':'en'},log=lambda _:None)
                self.assertEqual(Path(result['video']).read_bytes(),b'en')
                self.assertIn('Score: 2:1',Path(result['text']).read_text(encoding='utf-8-sig'))
                workflow.rerender(result['directory'],'2:1',settings={'language':'ru'},log=lambda _:None)
                self.assertEqual(export.call_args.kwargs['language'],'ru')
                self.assertEqual(Path(result['video']).read_bytes(),b'ru')
                self.assertIn('Счёт: 2:1',Path(result['text']).read_text(encoding='utf-8-sig'))
                self.assertEqual(workflow.load_project(result['directory'])['settings']['language'],'ru')
                self.assertEqual(analyze.call_count,1);download.assert_not_called()

    def test_video_assets_have_selected_language_including_goal_and_replay(self):
        with tempfile.TemporaryDirectory() as d:
            for code in language.LANGUAGES.values():
                t=language.strings(code)
                with patch('visuals.centered',wraps=visuals.centered) as put:
                    visuals.intro_layers(d,'Unknown',[],language=code)
                    visuals.card(Path(d,'final.png'),'A — B','2:1',final=True,language=code)
                    visuals.card(Path(d,'unknown.png'),'A — B','?',final=True,language=code)
                    visuals.card(Path(d,'replay.png'),'A — B',label=t['replay']+' • 0.5×',language=code)
                drawn=[call.args[1] for call in put.call_args_list]
                for text in [t['highlights'].upper(),t['football_highlights'].upper(),t['team_a'],t['team_b'],t['final'],t['unknown_final'],t['replay']+' • 0.5×']:
                    self.assertIn(text,drawn)
                original=ImageDraw.ImageDraw.text
                with patch.object(ImageDraw.ImageDraw,'text',autospec=True,side_effect=original) as draw:
                    visuals.goal_frame(.8,language=code)
                self.assertIn(t['goal'],[call.args[2] for call in draw.call_args_list])

    def test_saved_queue_checkpoint_keeps_its_language_on_resume(self):
        import core
        with tempfile.TemporaryDirectory() as d:
            source=Path(d,'original.mp4');source.write_bytes(b'source');checkpoints=[]
            analysis=dict(score='2:1',clips=[dict(start=0,end=2)],warnings=[])
            with patch('workflow.core.analyze',return_value=analysis),patch('workflow.core.render',side_effect=core.Cancelled()):
                with self.assertRaises(core.Cancelled):
                    workflow.create_project(d,local_video=str(source),title_hint='A — B',settings={'language':'en'},on_checkpoint=checkpoints.append,log=lambda _:None)
            def render(*args,**kw):Path(args[3]).write_bytes(kw['language'].encode())
            with patch('workflow.core.analyze',side_effect=AssertionError('reuse analysis')),patch('workflow.core.render',side_effect=render):
                result=workflow.resume_project(checkpoints[-1]['directory'],log=lambda _:None)
            self.assertEqual(Path(result['video']).read_bytes(),b'en')
            self.assertIn('Score: 2:1',Path(result['text']).read_text(encoding='utf-8-sig'))

    def test_old_projects_default_to_kazakh_and_invalid_languages_fail(self):
        self.assertEqual(language.normalize('English'),'en')
        self.assertEqual(language.label('ru'),'Русский')
        self.assertEqual(workflow.DEFAULTS['language'],'kk')
        text=workflow.project_text(dict(title='A — B',score='2:1',directory='',settings={'intro':False}))
        self.assertIn('Есеп: 2:1',text)
        with self.assertRaises(ValueError):publishing.youtube_text('A','B','2:1',language='xx')


@unittest.skipUnless(os.environ.get('FOOTSHORTS_GUI_TESTS')=='1','Native media integration job')
class LanguageRenderTests(unittest.TestCase):
    def test_english_intro_goal_replay_and_final_are_encoded(self):
        import core
        import cv2
        with tempfile.TemporaryDirectory() as d:
            source=Path(d,'source.mp4');out=Path(d,'english.mp4')
            core.run([core.ffmpeg(),'-v','error','-f','lavfi','-i','color=c=green:s=320x180:r=30:d=4',
                      '-c:v','libx264','-pix_fmt','yuv420p','-y',source])
            with patch('logos.pair',return_value=[]),patch('visuals.intro_layers',wraps=visuals.intro_layers) as intro,patch('visuals.goal_sequence',wraps=visuals.goal_sequence) as goal,patch('core.make_card',wraps=core.make_card) as card:
                core.render(str(source),None,[dict(start=0,end=4,kind='goal',goal_at=2)],out,
                            title='A — B',score='2:1',language='en',max_seconds=30,log=lambda _:None)
            self.assertEqual(intro.call_args.kwargs['language'],'en')
            self.assertEqual(goal.call_args.kwargs['language'],'en')
            self.assertTrue(all(c.kwargs['language']=='en' for c in card.call_args_list))
            self.assertTrue(any('REPLAY' in c.args[3] for c in card.call_args_list))
            self.assertAlmostEqual(core.metadata(out)['duration'],18,delta=.15)
            cap=cv2.VideoCapture(str(out));frames=0
            try:
                while cap.read()[0]:frames+=1
            finally:cap.release()
            self.assertGreaterEqual(frames,535)
