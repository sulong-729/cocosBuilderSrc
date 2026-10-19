import unittest

class AutoRotateTests(unittest.TestCase):
    def test_enable_and_disable_restores_original_native_code(self):
        from autorotate import configure_rotation
        source='- (BOOL) shouldAutorotate {\n return allowRotate;\n}\n- (NSUInteger) supportedInterfaceOrientations{\n return oldMask;\n}\n'
        result=configure_rotation(source,True,{'portrait':True,'landscapeLeft':True})
        self.assertIn('return YES;',result)
        self.assertIn('UIInterfaceOrientationMaskPortrait | UIInterfaceOrientationMaskLandscapeLeft',result)
        self.assertEqual(configure_rotation(result,False,{}),source)
        self.assertEqual(configure_rotation(result,True,{'portrait':True,'landscapeLeft':True}),result)
    def test_unknown_controller_is_not_silently_accepted(self):
        from autorotate import configure_rotation
        with self.assertRaisesRegex(ValueError,'ViewController'):
            configure_rotation('custom controller',True,{'portrait':True})
