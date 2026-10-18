from pathlib import Path
import io
import tempfile
import time
import unittest
from unittest.mock import patch
from PIL import Image
import logos
from timeline import plan_timeline


class IntroTests(unittest.TestCase):
    def test_intro_reserves_three_seconds_and_keeps_whole_replay(self):
        clip=dict(start=0,end=10,kind='goal',goal_at=5)
        p=plan_timeline([clip],31,True,True,.5,intro_seconds=3)
        self.assertEqual(p['duration'],30)
        self.assertEqual(len(p['segments']),2)
        p=plan_timeline([clip],29,True,True,.5,intro_seconds=3)
        self.assertEqual(p['duration'],16)
        self.assertEqual(len(p['segments']),1)
        self.assertTrue(p['notes'])

    def test_ambiguous_team_and_city_are_not_chosen(self):
        city=dict(id='Q1',label='Aktobe',description='city in Kazakhstan')
        with patch('logos.api',return_value={'search':[city]}):
            self.assertIsNone(logos.find_entity('Aktobe',time.monotonic()+10))
        items=[dict(id='Q2',label='FC Aktobe',description='football club'),
               dict(id='Q3',label='Aktobe',description='football club')]
        with patch('logos.api',return_value={'search':items}):
            self.assertIsNone(logos.find_entity('Aktobe',time.monotonic()+10))

    def test_logo_cache_avoids_network_and_preserves_source(self):
        def api(host,params,deadline):
            if params['action']=='wbgetentities':
                return {'entities':{'Q2':{'claims':{'P154':[{'mainsnak':{'datavalue':{'value':'Crest.svg'}}}]}}}}
            return {'query':{'pages':{'1':{'imageinfo':[dict(thumburl='https://upload.wikimedia.org/crest.png',
                descriptionurl='https://commons.wikimedia.org/wiki/File:Crest.svg',
                extmetadata={'Artist':{'value':'<b>Club</b>'},'LicenseShortName':{'value':'CC BY-SA'}})]}}}}
        raw=io.BytesIO();Image.new('RGBA',(50,50),'red').save(raw,format='PNG')
        with tempfile.TemporaryDirectory() as d,patch('logos.find_entity',return_value='Q2'),patch('logos.api',side_effect=api),patch('logos.fetch',return_value=raw.getvalue()) as fetch:
            a=logos.resolve('FC Aktobe',d,log=lambda _:None)
            self.assertTrue(Path(a['path']).is_file());self.assertEqual(a['artist'],'Club')
            b=logos.resolve('FC Aktobe',d,log=lambda _:None)
            self.assertEqual(a,b);self.assertEqual(fetch.call_count,1)

    def test_failed_logo_is_optional_and_urls_are_restricted(self):
        with tempfile.TemporaryDirectory() as d,patch('logos.find_entity',side_effect=TimeoutError):
            self.assertIsNone(logos.resolve('Aktobe',d,log=lambda _:None))
        for url in ['http://upload.wikimedia.org/x','https://example.com/x','https://user@upload.wikimedia.org/x']:
            with self.assertRaises(ValueError):logos.allowed(url)

    def test_chosen_logo_overrides_lookup_without_changing_source(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'choice.png';Image.new('RGBA',(80,90),'blue').save(source)
            original=source.read_bytes()
            path=logos.install('Aktobe',source,Path(d)/'cache')
            with patch('logos.find_entity',side_effect=AssertionError('No network expected')):
                result=logos.resolve('Aktobe',Path(d)/'cache')
            self.assertEqual(result['path'],str(path));self.assertTrue(result['manual'])
            self.assertEqual(source.read_bytes(),original)


if __name__=='__main__':unittest.main()
