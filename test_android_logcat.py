import unittest
from unittest.mock import patch
from android_backend import AndroidRunner


class AutomaticLogcatTests(unittest.TestCase):
    def test_selected_device_stream_does_not_require_app_pid_and_uses_shared_log(self):
        lines=[]
        runner=AndroidRunner({},lines.append,lambda _:None)
        calls=[]
        def adb(serial,args,**kwargs):
            calls.append((serial,args))
            runner.cancelled.set()
            return '10-20 11:12:13.100 123 456 E Cocos: runtime error'
        with patch.object(runner,'device_time',return_value='10-20 11:12:13.000'),patch.object(runner,'adb',side_effect=adb):
            runner.logcat('emulator-5554')
        self.assertEqual(calls[0][0],'emulator-5554')
        self.assertEqual(calls[0][1][0],'logcat')
        self.assertFalse(any(a.startswith('--pid') for a in calls[0][1]))
        self.assertTrue(any('runtime error' in line for line in lines))
        self.assertFalse(runner.monitoring)
