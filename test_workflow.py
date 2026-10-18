import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import workflow
import core

class WorkflowTests(unittest.TestCase):
    def fake_download(self,url,directory,*args):
        p=Path(directory)/'download.mp4';p.write_bytes(b'source')
        return dict(path=str(p),title='Ақтөбе 1-0 Ордабасы | Highlights',url=url)
    def fake_analyze(self,*args):
        return dict(score='1:3',clips=[dict(start=0,end=2,kind='goal',goal_at=1,reason='goal')],warnings=[])
    def fake_render(self,video,music,clips,output,**opts):Path(output).write_bytes(opts['score'].encode())


    def test_zoom_mode_defaults_off_and_can_be_changed_on_rerender(self):
        with tempfile.TemporaryDirectory() as d,patch('workflow.downloader.download',side_effect=self.fake_download),patch('workflow.core.analyze',side_effect=self.fake_analyze),patch('workflow.core.render',side_effect=self.fake_render) as render:
            result=workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',log=lambda _:None)
            self.assertFalse(render.call_args.kwargs['action_camera'])
            self.assertFalse(result['project']['settings']['action_camera'])
            workflow.rerender(result['directory'],'2:1',settings={'action_camera':True},log=lambda _:None)
            self.assertTrue(render.call_args.kwargs['action_camera'])
            workflow.rerender(result['directory'],'2:1',settings={'action_camera':False},log=lambda _:None)
            self.assertFalse(render.call_args.kwargs['action_camera'])


    def test_selected_login_reaches_downloader(self):
        with tempfile.TemporaryDirectory() as d,patch('workflow.downloader.download') as download,patch('workflow.core.analyze',side_effect=self.fake_analyze),patch('workflow.core.render',side_effect=self.fake_render):
            download.side_effect=lambda *args,**kwargs:self.fake_download(*args)
            workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',settings={'youtube_browser':'chrome'},log=lambda _:None)
            self.assertEqual(download.call_args.kwargs,{'browser':'chrome'})
            workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',settings={'youtube_cookie_file':'local-session.txt'},log=lambda _:None)
            self.assertEqual(download.call_args.kwargs,{'cookie_file':'local-session.txt'})

    def test_auto_then_correct_without_downloading_or_analyzing(self):
        with tempfile.TemporaryDirectory() as d,patch('workflow.downloader.download',side_effect=self.fake_download) as download,patch('workflow.core.analyze',side_effect=self.fake_analyze) as analyze,patch('workflow.core.render',side_effect=self.fake_render):
            a=workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',log=lambda _:None)
            project=Path(a['directory'])
            self.assertEqual(Path(a['video']).read_bytes(),b'1:3')
            self.assertTrue((project/'source/original.mp4').is_file())
            self.assertEqual(len(list(project.glob('*.txt'))),1)
            b=workflow.rerender(project,'2:3',log=lambda _:None)
            self.assertEqual(Path(b['video']).read_bytes(),b'2:3')
            self.assertIn('Есеп: 2:3',Path(b['text']).read_text(encoding='utf-8-sig'))
            self.assertNotIn('Есеп: 1:3',Path(b['text']).read_text(encoding='utf-8-sig'))
            self.assertEqual(download.call_count,1);self.assertEqual(analyze.call_count,1)
            self.assertEqual(len(list(project.glob('*.mp4'))),1)
            self.assertTrue(list((project/'source/history').rglob('*.mp4')))
            self.assertEqual(workflow.load_project(project)['revision'],2)

    def test_source_title_is_available_before_analysis_finishes(self):
        updates=[]
        def analyze(*args):
            self.assertEqual(len(updates),1)
            self.assertIn('Ақтөбе',updates[0]['title'])
            self.assertTrue(Path(updates[0]['video']).is_file())
            self.assertEqual(workflow.load_project(updates[0]['directory'])['title'],updates[0]['title'])
            raise RuntimeError('analysis stopped')
        with tempfile.TemporaryDirectory() as d,patch('workflow.downloader.download',side_effect=self.fake_download),patch('workflow.core.analyze',side_effect=analyze):
            with self.assertRaisesRegex(RuntimeError,'analysis stopped'):
                workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',log=lambda _:None,on_source=updates.append)
            self.assertEqual(len(updates),1)

    def test_new_project_preserves_previous(self):
        with tempfile.TemporaryDirectory() as d,patch('workflow.downloader.download',side_effect=self.fake_download),patch('workflow.core.analyze',side_effect=self.fake_analyze),patch('workflow.core.render',side_effect=self.fake_render):
            a=workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',log=lambda _:None)
            b=workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',log=lambda _:None)
            self.assertNotEqual(a['directory'],b['directory'])
            self.assertTrue(Path(a['video']).is_file())
            self.assertEqual(len(workflow.recent_projects(d)),2)

    def test_unknown_score_is_not_zero_zero(self):
        def download(url,directory,*args):
            p=Path(directory)/'v.mp4';p.write_bytes(b'src');return dict(path=str(p),title='Unidentified match',url=url)
        def analyze(*args):return dict(score=None,clips=[dict(start=0,end=2,reason='audio')],warnings=[])
        with tempfile.TemporaryDirectory() as d,patch('workflow.downloader.download',download),patch('workflow.core.analyze',analyze),patch('workflow.core.render',side_effect=self.fake_render):
            r=workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',log=lambda _:None)
            self.assertEqual(Path(r['video']).read_bytes(),b'?')
            t=Path(r['text']).read_text(encoding='utf-8-sig')
            self.assertIn('анықталмады',t);self.assertNotIn('Есеп: 0:0',t)

    def test_failed_correction_keeps_previous_pair(self):
        with tempfile.TemporaryDirectory() as d,patch('workflow.downloader.download',side_effect=self.fake_download),patch('workflow.core.analyze',side_effect=self.fake_analyze),patch('workflow.core.render',side_effect=self.fake_render):
            r=workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',log=lambda _:None)
            old_video=Path(r['video']).read_bytes();old_text=Path(r['text']).read_bytes()
            with patch('workflow.core.render',side_effect=RuntimeError('render failed')):
                with self.assertRaises(RuntimeError):workflow.rerender(r['directory'],'9:9',log=lambda _:None)
            self.assertEqual(Path(r['video']).read_bytes(),old_video)
            self.assertEqual(Path(r['text']).read_bytes(),old_text)

    def test_project_is_portable(self):
        with tempfile.TemporaryDirectory() as d,patch('workflow.downloader.download',side_effect=self.fake_download),patch('workflow.core.analyze',side_effect=self.fake_analyze),patch('workflow.core.render',side_effect=self.fake_render):
            r=workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',log=lambda _:None)
            moved=Path(d)/'moved';shutil.move(r['directory'],moved)
            p=workflow.load_project(moved)
            self.assertTrue(workflow.media_path(p,p['source_file']).is_file())
            workflow.rerender(moved,'0:0',log=lambda _:None)
            self.assertEqual(Path(workflow.output_files(workflow.load_project(moved))['video']).read_bytes(),b'0:0')

    def test_pair_commit_rollback_if_text_move_fails(self):
        with tempfile.TemporaryDirectory() as d,patch('workflow.downloader.download',side_effect=self.fake_download),patch('workflow.core.analyze',side_effect=self.fake_analyze),patch('workflow.core.render',side_effect=self.fake_render):
            r=workflow.create_project(d,'https://youtu.be/so5hJv_2cVQ',log=lambda _:None)
            real_replace=workflow.os.replace
            def replace(src,dest):
                if Path(src).name=='result.txt':raise OSError('simulated disk failure')
                return real_replace(src,dest)
            with patch('workflow.os.replace',side_effect=replace):
                with self.assertRaises(OSError):workflow.rerender(r['directory'],'4:4',log=lambda _:None)
            self.assertEqual(Path(r['video']).read_bytes(),b'1:3')
            self.assertIn('Есеп: 1:3',Path(r['text']).read_text(encoding='utf-8-sig'))

if __name__=='__main__':unittest.main()
