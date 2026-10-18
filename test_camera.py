import unittest
import cv2
import numpy as np
import camera


class CameraTests(unittest.TestCase):
    def test_ball_on_pitch_and_no_pitch_fallback(self):
        frame=np.full((360,640,3),(35,125,35),np.uint8)
        cv2.circle(frame,(420,210),4,(255,255,255),-1)
        x,found=camera.focus(frame,.6)
        self.assertTrue(found);self.assertAlmostEqual(x,420/640,delta=.01)
        self.assertEqual(camera.focus(np.zeros_like(frame),.8),(.5,False))

    def test_smoothing_limits_false_detection_jump(self):
        samples=[(0,.5),(.5,.5),(1,1),(1.5,.5),(2,.5)]
        points=camera.smooth_targets(samples)
        for (a,x),(b,y) in zip(points,points[1:]):
            self.assertLessEqual(abs(x-y),.22*(b-a)+1e-8)
        self.assertLess(max(x for _,x in points),.6)

    def test_portrait_edges_and_slow_motion_time(self):
        expression=camera.crop_expression([(0,0),(2,1)],1000,300,.5)
        self.assertIn('lt(t,4.000)',expression)
        self.assertIn('700.000',expression)
        self.assertEqual(camera.crop_expression([(0,0)],1000,300),'0.000')


if __name__=='__main__':unittest.main()
