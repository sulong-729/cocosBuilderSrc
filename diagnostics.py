"""Read Apple crash reports and resolve frames using UUID-matched local symbols."""
import json
import re
import subprocess
from pathlib import Path


def read_report(path):
    text = Path(path).read_text(errors='replace')
    header, end = json.JSONDecoder().raw_decode(text.lstrip())
    body = json.loads(text.lstrip()[end:]) if text.lstrip()[end:].strip() else header
    images = body.get('usedImages', [])
    threads = body.get('threads', [])
    index = body.get('faultingThread', next((i for i,t in enumerate(threads) if t.get('triggered')), 0))
    frames = []
    for frame in (threads[index].get('frames', []) if 0 <= index < len(threads) else []):
        i = frame.get('imageIndex', -1)
        image = images[i] if isinstance(i,int) and 0 <= i < len(images) else {}
        frames.append(dict(frame, image=image, address=image.get('base',0)+frame.get('imageOffset',0)))
    return dict(path=str(path), header=header, body=body, frames=frames, thread=index,
                name=body.get('procName',header.get('app_name','')), proc_path=body.get('procPath',''))


def matches(report, executable, device):
    return bool(executable and report['name'] == executable and
                (not device or f'/Devices/{device}/'.lower() in report['proc_path'].lower()))


def uuid_matches(output, uuid, arch):
    normalize = lambda s: s.replace('-','').lower()
    return any(normalize(u)==normalize(uuid) and a==arch
               for u,a in re.findall(r'UUID: ([A-Fa-f0-9-]+) \(([^)]+)\)',output))


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    return result.stdout.strip() if result.returncode == 0 else ''


def symbolicate(report, project):
    # Search only project build products; never trust another build's source lines.
    root = Path(project)/'build'
    candidates = list(root.glob('**/*.dSYM/Contents/Resources/DWARF/*'))
    candidates += [p for p in root.glob('**/*.app/*') if p.is_file() and p.name == report['name']]
    symbol_ids = [(p, command(["xcrun","dwarfdump","--uuid",str(p)])) for p in candidates]
    resolved = {}
    for frame in report['frames']:
        image = frame['image']; uuid = image.get('uuid',''); arch = image.get('arch','')
        key = (uuid,arch)
        if key not in resolved:
            resolved[key] = next((p for p, ids in symbol_ids if uuid and uuid_matches(ids,uuid,arch)),None)
        binary = resolved[key]
        frame['resolved'] = command(['xcrun','atos','-fullPath','-arch',arch,'-o',str(binary),'-l',hex(image.get('base',0)),hex(frame['address'])]) if binary else ''
    return report


def source_excerpt(path, line):
    try:
        lines = Path(path).read_text(errors='replace').splitlines()
        return '\n'.join(f'{">" if n==line else " "} {n:5}  {lines[n-1]}' for n in range(max(1,line-5),min(len(lines),line+5)+1))
    except OSError:
        return 'Không tìm thấy source tại đường dẫn trong symbol.'


def format_report(report):
    b = report['body']; exception = b.get('exception',{})
    lines = [f"{report['name']} · {report['header'].get('timestamp', b.get('captureTime',''))}",
             f"{exception.get('type','')} / {exception.get('signal','')} · Thread {report['thread']} crashed",
             f"Report: {report['path']}",
             'Stack là vị trí crash; cần điều tra để xác định nguyên nhân gốc.', '']
    for i,f in enumerate(report['frames']):
        symbol = f.get('resolved') or f.get('symbol') or hex(f['address'])
        lines.append(f"#{i}  {f['image'].get('name','?')}  {symbol}")
    lines += ['', 'Không có file/dòng: thiếu symbol hoặc UUID không khớp với bản đã crash.']
    return '\n'.join(lines)
