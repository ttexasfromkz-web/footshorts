import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import downloader
import core

class DownloadTests(unittest.TestCase):
    def test_url_validation(self):
        canonical='https://www.youtube.com/watch?v=so5hJv_2cVQ'
        for url in ['https://youtu.be/so5hJv_2cVQ?si=abcd','youtube.com/shorts/so5hJv_2cVQ',canonical+'&list=abc']:
            self.assertEqual(downloader.normalize_url(url),canonical)
        for url in ['https://youtube.com.evil.test/watch?v=so5hJv_2cVQ','file:///tmp/x','https://youtube.com/playlist?list=abc','https://youtube.com/watch?v=abc','https://user:pass@youtube.com/watch?v=so5hJv_2cVQ']:
            with self.assertRaises(ValueError):downloader.normalize_url(url)

    def test_cli_options(self):
        from yt_dlp.options import parseOpts
        with tempfile.TemporaryDirectory() as d:
            cmd=downloader.build_command('https://youtu.be/so5hJv_2cVQ',d,720)
            parseOpts(cmd[3:])
            self.assertIn('--no-playlist',cmd)
            self.assertIn('--ignore-config',cmd)
            self.assertIn('height<=720',cmd[cmd.index('-f')+1])
            self.assertNotIn('--cookies-from-browser',cmd)


    def test_selected_chrome_is_passed_to_ytdlp(self):
        from yt_dlp.options import parseOpts
        with tempfile.TemporaryDirectory() as d:
            cmd=downloader.build_command('https://youtu.be/so5hJv_2cVQ',d,browser='chrome')
            _,opts,_=parseOpts(cmd[3:])
            self.assertTrue(opts.cookiesfrombrowser)
            self.assertEqual(cmd[cmd.index('--cookies-from-browser')+1],'chrome')
            self.assertNotIn('--cookies',cmd)
            with self.assertRaises(ValueError):downloader.authentication_args(browser='unknown')

    def test_cookie_file_is_private_copy_and_original_survives_failure(self):
        with tempfile.TemporaryDirectory() as d:
            cookie=Path(d)/'cookies.txt';original='# Netscape HTTP Cookie File\n'
            cookie.write_text(original)
            captured=[]
            def command(url,workdir,height,**auth):
                copied=Path(auth['cookie_file']);captured.append(copied)
                self.assertNotEqual(copied,cookie)
                self.assertEqual(copied.read_text(),original)
                copied.write_text(original+'# changed by downloader\n')
                return [sys.executable,'-c',"import sys;print('ERROR: HTTP 429');sys.exit(1)"]
            dest=Path(d)/'downloads'
            with patch.object(downloader,'build_command',command):
                with self.assertRaisesRegex(RuntimeError,'429'):
                    downloader.download('https://youtu.be/so5hJv_2cVQ',dest,cookie_file=str(cookie),log=lambda _:None)
            self.assertEqual(cookie.read_text(),original)
            self.assertFalse(captured[0].exists());self.assertFalse(list(dest.iterdir()))

    def test_invalid_and_conflicting_login_options_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            cookie=Path(d)/'bad.txt';cookie.write_text('not a cookie file')
            with self.assertRaises(ValueError):downloader.authentication_args(cookie_file=str(cookie))
            with self.assertRaises(ValueError):downloader.authentication_args(browser='chrome',cookie_file=str(cookie))

    def test_login_errors_explain_chrome_lock_and_encryption(self):
        self.assertIn('Chrome',downloader.download_error(["ERROR: Sign in to confirm you're not a bot"]))
        self.assertIn('толық жауып',downloader.download_error(['ERROR: Could not copy Chrome cookie database']))
        self.assertIn('шифрлау',downloader.download_error(['ERROR: Failed to decrypt with DPAPI']))
        self.assertIn('Cookies файлы',downloader.download_error(['ERROR: Failed to decrypt with DPAPI']))

    def test_download_file_and_progress(self):
        # Exercise the real subprocess/queue/file-promotion path without YouTube.
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'fixture.mp4'
            core.run([core.ffmpeg(),'-v','error','-f','lavfi','-i','color=s=160x90:d=1',
                      '-c:v','libx264','-threads','1','-y',source])
            def command(url,workdir,height):
                code="import sys,shutil;from pathlib import Path;p=Path(sys.argv[2])/'video.mp4';shutil.copyfile(sys.argv[1],p);print('TITLE:Test Match',flush=True);print('DL:50%',flush=True);print('FILE:'+str(p),flush=True)"
                return [sys.executable,'-c',code,str(source),str(workdir)]
            logs=[]
            with patch.object(downloader,'build_command',command):
                result=downloader.download('https://youtu.be/so5hJv_2cVQ',Path(d)/'downloads',log=logs.append)
            self.assertTrue(Path(result['path']).is_file())
            self.assertEqual(result['title'],'Test Match')
            self.assertTrue(any('50%' in x for x in logs))
            self.assertEqual(len(list((Path(d)/'downloads').iterdir())),1)

    def test_cancel_subprocess_and_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            event=threading.Event();timer=threading.Timer(.5,event.set);timer.start()
            def command(*args):return [sys.executable,'-c','import time;time.sleep(30)']
            start=time.monotonic()
            with patch.object(downloader,'build_command',command):
                with self.assertRaises(core.Cancelled):
                    downloader.download('https://youtu.be/so5hJv_2cVQ',d,log=lambda _:None,cancel=event)
            timer.join();self.assertLess(time.monotonic()-start,8)
            self.assertFalse(list(Path(d).iterdir()))

    def test_failure_does_not_select_partial_file(self):
        with tempfile.TemporaryDirectory() as d:
            def command(*args):return [sys.executable,'-c',"import sys;print('ERROR: HTTP 429');sys.exit(1)"]
            with patch.object(downloader,'build_command',command):
                with self.assertRaisesRegex(RuntimeError,'429'):
                    downloader.download('https://youtu.be/so5hJv_2cVQ',d,log=lambda _:None)
            self.assertFalse(list(Path(d).iterdir()))
if __name__=='__main__':unittest.main()
