import unittest

class ConfigTests(unittest.TestCase):
    def test_override_isolated_per_project_and_task(self):
        from project_config import effective_options, remember_options
        settings={'projects':{}}
        original={'debug':True,'packages':{'ios':{'targetVersion':'12.0'}}}
        remember_options(settings,'/a','ios',{'debug':False})
        self.assertFalse(effective_options(settings,'/a','ios',original)['debug'])
        self.assertTrue(effective_options(settings,'/b','ios',original)['debug'])
        self.assertTrue(effective_options(settings,'/a','other',original)['debug'])
        self.assertTrue(original['debug'])
    def test_scene_validation(self):
        from project_config import validate_options
        self.assertTrue(validate_options({'scenes':[], 'startScene':''}))
        self.assertFalse(validate_options({'scenes':[{'uuid':'a'}],'startScene':'a','packages':{'ios':{'targetVersion':'12.0','orientation':{'portrait':True}}}}))
    def test_native_only_detects_changed_options(self):
        from project_config import options_changed
        self.assertTrue(options_changed({'debug':True},{'debug':False}))
        self.assertFalse(options_changed({'debug':True},{'debug':True}))
