"""Independent build profiles; never mutate the Cocos project's configuration."""
import copy
import json
import re


def effective_options(settings, root, task, original):
    return copy.deepcopy(settings.get('projects',{}).get(root,{}).get('buildOptions',{}).get(task,original))


def remember_options(settings, root, task, options):
    settings.setdefault('projects',{}).setdefault(root,{}).setdefault('buildOptions',{})[task]=copy.deepcopy(options)


def options_changed(original, edited):
    return json.dumps(original,sort_keys=True)!=json.dumps(edited,sort_keys=True)


def validate_options(options):
    scenes=options.get('scenes',[])
    if not scenes or options.get('startScene') not in [s.get('uuid') for s in scenes]:
        return 'Chọn ít nhất một scene và scene khởi động phải nằm trong danh sách build.'
    ios=options.get('packages',{}).get('ios',{})
    if ios.get('targetVersion') and not re.fullmatch(r'\d+(?:\.\d+){0,2}',str(ios['targetVersion'])):
        return 'Phiên bản iOS không hợp lệ, ví dụ 12.0.'
    if ios.get('orientation') and not any(ios['orientation'].values()):
        return 'Chọn ít nhất một hướng màn hình.'
    if options.get('packages',{}).get('native',{}).get('encrypted') and not options.get('packages',{}).get('native',{}).get('xxteaKey'):
        return 'Nhập khóa XXTEA khi bật mã hóa script.'
    return ''
