import unittest
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from goal_evaluation import match_goals,evaluate_project,seconds


class GoalEvaluationTests(unittest.TestCase):
    def test_analysis_keeps_real_transitions_after_wrong_ocr_state(self):
        import core
        cap=Mock();cap.time=0
        cap.set.side_effect=lambda _,ms:setattr(cap,'time',ms/1000)
        cap.read.return_value=(True,np.zeros((32,64,3),dtype=np.uint8))
        def ocr(_):
            a,b=(0,0) if cap.time<40 else (8,8) if cap.time<48 else (1,0) if cap.time<98 else (2,0)
            return ([[[[0,0],[30,0],[30,10],[0,10]],f'{a}-{b}',.99]],None)
        engine=SimpleNamespace(RapidOCR=lambda **_:ocr)
        with patch.dict(sys.modules,{'rapidocr_onnxruntime':engine}),patch('core.metadata',return_value=dict(duration=200,width=64,height=32,fps=30)),patch('cv2.VideoCapture',return_value=cap),patch('core.run',side_effect=RuntimeError('No audio in fixture')),patch('highlight_signals.inspect_candidates',side_effect=lambda video,candidates,*_:candidates):
            analysis=core.analyze('synthetic-test.mp4',log=lambda _:None)
        self.assertEqual(analysis['score'],'2:0')
        self.assertEqual(len(analysis['ignored_score_states']),1)
        result=evaluate_project(dict(analysis=analysis,clips=analysis['clips']),[42,92])
        self.assertEqual(result['detection']['true_positives'],2)
        self.assertEqual(result['selection']['coverage'],1)
        cap.release.assert_called_once()

    def test_cli_writes_report_and_refuses_overwriting_labels(self):
        script=Path(__file__).parent/'scripts/evaluate_goals.py'
        with tempfile.TemporaryDirectory(prefix='Football goal evaluation ') as d:
            folder=Path(d);project=folder/'project.json';labels=folder/'goal labels.json';output=folder/'report.json'
            project.write_text(json.dumps(dict(analysis=dict(detected_goals=[dict(goal_at=20)]),clips=[dict(start=10,end=30)])),encoding='utf-8')
            labels.write_text('{"goals":["00:20"]}',encoding='utf-8')
            result=subprocess.run([sys.executable,str(script),str(project),str(labels),'--output',str(output)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(output.read_text())['detection']['true_positives'],1)
            result=subprocess.run([sys.executable,str(script),str(project),str(labels),'--output',str(labels)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(json.loads(labels.read_text()),{'goals':['00:20']})

    def test_counts_misses_and_false_alarms_independently(self):
        r=match_goals([20,80],[21,150],5)
        self.assertEqual((r['true_positives'],r['false_positives'],r['false_negatives']),(1,1,1))
        self.assertEqual(r['missed'],[80]);self.assertEqual(r['extra'],[150])
        self.assertEqual(r['precision'],.5);self.assertEqual(r['recall'],.5)

    def test_one_detection_cannot_match_two_goals(self):
        r=match_goals([20,25],[22],10)
        self.assertEqual(r['true_positives'],1);self.assertEqual(r['false_negatives'],1)

    def test_global_matching_does_not_lose_a_valid_pair(self):
        r=match_goals([0,5],[4,9],5)
        self.assertEqual(r['true_positives'],2)

    def test_no_goals_does_not_report_invented_perfect_accuracy(self):
        r=match_goals([],[])
        self.assertIsNone(r['precision']);self.assertIsNone(r['recall']);self.assertIsNone(r['f1'])
        self.assertEqual(match_goals([],[50])['false_positives'],1)

    def test_selection_budget_is_separate_from_detection(self):
        p=dict(analysis=dict(info={'duration':100},detected_goals=[{'goal_at':20},{'goal_at':80}]),
               clips=[dict(start=10,end=30)])
        r=evaluate_project(p,['00:20','01:20'])
        self.assertEqual(r['detection']['recall'],1)
        self.assertEqual(r['selection']['coverage'],.5)
        self.assertEqual(r['selection']['missing_goal_times'],[80])

    def test_old_projects_use_explicitly_identified_fallback(self):
        p=dict(analysis=dict(score_events=[{'time':0,'score':[0,0]},{'time':26,'score':[1,0]}]),clips=[])
        self.assertEqual(evaluate_project(p,[20])['prediction_source'],'score_events_fallback')

    def test_timestamp_validation(self):
        self.assertEqual(seconds('01:02:03.5'),3723.5)
        for bad in ('1:75',float('nan'),-1,True,'abc'):
            with self.assertRaises(ValueError):seconds(bad)
        with self.assertRaises(ValueError):match_goals([20,20],[])
        with self.assertRaises(ValueError):evaluate_project({'analysis':{'info':{'duration':5}}},[20])
