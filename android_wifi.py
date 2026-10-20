"""In-memory Android 11+ QR pairing, following the AOSP adb Wi-Fi protocol."""
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import re
import secrets
import string
import time

from backend import BuildError


@dataclass(frozen=True)
class PairingSession:
    service: str
    password: str = field(repr=False)

    @property
    def payload(self):
        return f'WIFI:T:ADB;S:{self.service};P:{self.password};;'


def new_pairing_session():
    alphabet = string.ascii_letters + string.digits
    random_text = lambda size: ''.join(secrets.choice(alphabet) for _ in range(size))
    return PairingSession('studio-' + random_text(10), random_text(24))


def qr_matrix(payload):
    """Return square bool rows including the required four-module quiet zone."""
    try:
        import qrcode
    except ImportError as error:
        raise BuildError('Thiếu thư viện QR. Chạy Setup Tool để cài requirements.txt rồi mở lại tool.') from error
    code = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(payload)
    code.make(fit=True)
    return [[bool(cell) for cell in row] for row in code.get_matrix()]


def _mdns_services(output):
    services = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        name, kind, endpoint = parts
        kind = kind.removesuffix('.').removesuffix('.local')
        if kind not in ('_adb-tls-pairing._tcp', '_adb-tls-connect._tcp'):
            continue
        try:
            host, port = endpoint.rsplit(':', 1)
            ipaddress.ip_address(host.strip('[]'))
            if not 1 <= int(port) <= 65535:
                continue
        except ValueError:
            continue
        name = name.removesuffix('.').removesuffix('.local')
        name = name.removesuffix('.' + kind)
        services.append((name, kind, endpoint))
    return services


def pair_qr(runner, session, timeout=120):
    """Pair the phone scanning this session; only return a proven matching serial.

    Pairing credentials are never passed in arguments, emitted, or persisted here.
    adb itself persists the trusted host key as part of normal pairing.
    """
    deadline = time.monotonic() + timeout

    def remaining():
        if runner.cancelled.is_set():
            raise BuildError('Đã dừng ghép đôi QR. Tạo QR mới để thử lại.')
        return deadline - time.monotonic()

    def command(args, **kwargs):
        budget = remaining()
        if budget <= 0:
            raise BuildError('QR hết thời gian. Tạo QR mới; bật Wireless debugging và dùng cùng mạng Wi-Fi, cho phép mDNS.')
        return runner.run([adb, *args], timeout=min(10, budget), announce=False, emit_output=False, **kwargs)

    remaining()
    adb = runner.tool('adb')
    runner.stage('Chờ quét QR trên Android')
    runner.write('Mở Wireless debugging → Pair device with QR code trên điện thoại và quét QR.')
    services = []
    while remaining() > 0:
        try:
            services = _mdns_services(command(['mdns', 'services']))
        except BuildError as error:
            remaining()
            raise BuildError('Không tìm được dịch vụ mDNS. Cập nhật Android SDK Platform Tools; kiểm tra cùng mạng Wi-Fi và quyền Local Network.') from error
        target = next((address for name, kind, address in services
                       if name == session.service and kind == '_adb-tls-pairing._tcp'), '')
        if target:
            break
        runner.cancelled.wait(min(1, max(0, remaining())))
    else:
        raise BuildError('QR hết thời gian. Tạo QR mới; bật Wireless debugging và dùng cùng mạng Wi-Fi, cho phép mDNS.')

    runner.stage('Ghép đôi Android qua QR')
    runner.secrets.append(session.password)
    try:
        try:
            output = command(['pair', target], input_text=session.password + '\n')
        except BuildError as error:
            remaining()
            raise BuildError('Ghép đôi QR thất bại hoặc quá thời gian. Tạo QR mới rồi quét lại; kiểm tra Wi-Fi và Wireless debugging.') from error
    finally:
        runner.secrets.remove(session.password)
    # Do not accept adb's "Failed: Successfully paired but ..." diagnostic.
    success = re.search(r'(?:^|\n)(?:Enter pairing code:\s*)?Successfully paired to\s+\S+(?:\s+\[guid=([^\]\s]+)\])?', output, re.I)
    if not success:
        raise BuildError('Ghép đôi QR thất bại. Tạo QR mới rồi quét lại; kiểm tra Wireless debugging và mạng Wi-Fi.')
    guid = success[1] or ''
    runner.stage('Đã ghép đôi; chờ kết nối Android')
    # The GUID is adb's authenticated pairing result, not the QR service name.
    # Without it, report paired only; guessing from newly visible devices is unsafe.
    while guid and remaining() > 0:
        from android_backend import parse_devices
        try:
            devices = parse_devices(command(['devices', '-l']))
        except BuildError:
            remaining()
            devices = []
        try:
            services = _mdns_services(command(['mdns', 'services']))
        except BuildError:
            remaining()
            services = []
        endpoints = {address for name, kind, address in services
                     if name == guid and kind == '_adb-tls-connect._tcp'}
        expected = {guid + '._adb-tls-connect._tcp', guid + '._adb-tls-connect._tcp.local.', *endpoints}
        for device in devices:
            if device['state'] == 'device' and device['kind'] == 'device' and device['serial'] in expected:
                return {'paired': True, 'serial': device['serial'], 'message': 'Đã ghép đôi QR và kết nối Android qua Wi-Fi.'}
        runner.cancelled.wait(min(1, max(0, remaining())))
    remaining()
    return {'paired': True, 'serial': '', 'message': 'Đã ghép đôi QR nhưng chưa xác nhận kết nối. Giữ Wireless debugging bật rồi Refresh; nếu cần, dùng Connect với IP:cổng kết nối trên điện thoại.'}
