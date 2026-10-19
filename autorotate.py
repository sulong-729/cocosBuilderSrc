"""Reversible override for the generated iOS ViewController, not native-templates."""
import re


def configure_rotation(source, enabled, orientation):
    clean=re.sub(r'\n// COCOS_BUILDER_AUTOROTATE_BEGIN\n.*?// COCOS_BUILDER_AUTOROTATE_END\n','',source,flags=re.S)
    if not enabled:return clean
    masks={'portrait':'UIInterfaceOrientationMaskPortrait','upsideDown':'UIInterfaceOrientationMaskPortraitUpsideDown',
           'landscapeLeft':'UIInterfaceOrientationMaskLandscapeLeft','landscapeRight':'UIInterfaceOrientationMaskLandscapeRight'}
    selected=[v for k,v in masks.items() if orientation.get(k)]
    if not selected:raise ValueError('Chọn ít nhất một hướng màn hình cho Auto Rotate.')
    rules=[(r'(-\s*\(BOOL\)\s*shouldAutorotate\s*\{)','return YES;'),
           (r'(-\s*\((?:NSUInteger|UIInterfaceOrientationMask)\)\s*supportedInterfaceOrientations\s*\{)','return '+' | '.join(selected)+';')]
    result=clean
    for pattern,statement in rules:
        block='\n// COCOS_BUILDER_AUTOROTATE_BEGIN\n    '+statement+'\n// COCOS_BUILDER_AUTOROTATE_END\n'
        result,count=re.subn(pattern,lambda m:m[1]+block,result,count=1)
        if not count:raise ValueError('ViewController không có phương thức orientation tương thích; chưa áp dụng Auto Rotate.')
    return result
