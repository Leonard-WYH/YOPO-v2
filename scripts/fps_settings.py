"""Configure the pinned FPS simulator and enable round-outcome logging."""
import hashlib
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
DRONE_EXPLOSION_LOG = 'Drone Explosion Sound'


def _enable_drone_outcome_log(data_dir):
    """Add one Debug.Log after DroneHealth first marks the drone as down.

    The pinned release already contains the marker string and Log(object)
    reference. Relocate its 102-byte Explode body to unused .text padding,
    inserting the ten-byte logging call after the down flag is set. Existing
    branches stay on the same side of the insertion, retaining their relative
    offsets. Explosion effects, sound and removal instructions are unchanged.
    Whole-file hashes guard the release layout and make this idempotent.
    """
    path = data_dir / 'Managed/Assembly-CSharp.dll'
    original_sha = '9d0d5b811dd5486d5a3fca4b80ddf1300fb68bb1a44d417a65b5de141c218615'
    patched_sha = '8eba015904590643add25dfd9347546e5813d481532eddf8f090399e2e68ca6a'
    original = path.read_bytes()
    current_sha = hashlib.sha256(original).hexdigest()
    if current_sha != patched_sha:
        if current_sha != original_sha:
            raise RuntimeError('FPS 程序与已验证版本不一致，未添加击落事件；请运行 setup.sh 恢复官方版本')
        body = bytearray(original[19212:19314])
        body[28:28] = b'\x72' + struct.pack('<I', 0x700005ba) + b'\x28' + struct.pack('<I', 0x0a0000ab)
        struct.pack_into('<I', body, 4, 100)  # Fat method header: new IL code size.
        if len(body) != 112 or original[236388:236544] != bytes(156):
            raise RuntimeError('FPS 击落事件补丁的代码空间校验失败')
        edited = bytearray(original)
        edited[236388:236500] = body
        struct.pack_into('<I', edited, 113430, 244068)  # Explode MethodDef RVA.
        struct.pack_into('<I', edited, 384, 235988)  # .text virtual size.
        if hashlib.sha256(edited).hexdigest() != patched_sha:
            raise RuntimeError('FPS 击落事件补丁校验失败，未写入程序')
        backup = ROOT / '.reproduce/backups/fps-settings/Assembly-CSharp.dll.original'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_bytes(original)
        path.write_bytes(edited)
    return {'marker': DRONE_EXPLOSION_LOG, 'assembly': path.relative_to(ROOT).as_posix(),
            'assembly_sha256': patched_sha}


def _position(text):
    match = re.search(r'(?m)^Position\s*=\s*(\[[^\n]*?\])', text)
    if not match:
        raise RuntimeError('FPS 出生配置中没有 Position 字段，请重新运行 setup.sh')
    return match, json.loads(match.group(1))


def configure_fps(game_dir, sensitivity, spawn_protection, drone_distance):
    """Apply scene settings and outcome logging to the pinned v0.1.1-alpha release.

    Unity's MonoBehaviour header is 32 bytes for these unnamed components.
    The release strips custom type trees, so identify scripts through their
    MonoScript pointers and validate the complete component sizes before using
    the known field offsets. Fixed-size edits preserve every other scene byte.
    """
    try:
        import UnityPy
    except ImportError as exc:
        raise RuntimeError('FPS 配置需要 UnityPy，请先运行 ./setup.sh 安装新增依赖') from exc

    game_dir = Path(game_dir).resolve()
    data_dir = game_dir / 'Tracker_Data'
    scene_path = data_dir / 'level0'
    original = scene_path.read_bytes()
    edited = bytearray(original)
    environment = UnityPy.load(str(scene_path), str(data_dir / 'sharedassets0.assets'))
    found = set()
    expected = {'CameraLook': (56, 32), 'PlayerDeath': (84, 76)}
    for obj in environment.objects:
        if obj.type.name != 'MonoBehaviour' or obj.assets_file.name != 'level0':
            continue
        component = obj.read(check_read=False)
        name = component.m_Script.read().m_ClassName
        if name not in expected:
            continue
        size, offset = expected[name]
        raw = obj.get_raw_data()
        if name in found or component.m_Name or len(raw) != size:
            raise RuntimeError(f'FPS {name} 场景格式与已验证版本不一致，未写入配置')
        if original[obj.byte_start:obj.byte_start + size] != raw:
            raise RuntimeError('FPS 场景对象偏移校验失败，未写入配置')
        if name == 'CameraLook':
            struct.pack_into('<ff', edited, obj.byte_start + offset, sensitivity, sensitivity)
        else:
            struct.pack_into('<f', edited, obj.byte_start + offset, spawn_protection)
        found.add(name)
    if found != set(expected):
        raise RuntimeError('FPS 缺少鼠标或重生组件，请检查官方仿真器版本')

    config_dir = game_dir / 'Configs'
    _, character = _position((config_dir / 'character_spawn_config.toml').read_text())
    drone_path = config_dir / 'drone_spawn_config.toml'
    drone_text = drone_path.read_text()
    match, drone = _position(drone_text)
    drone[0], drone[1] = character[0] - drone_distance, character[1]
    new_drone_text = drone_text[:match.start(1)] + json.dumps(drone) + drone_text[match.end(1):]

    backups = ROOT / '.reproduce/backups/fps-settings'
    backups.mkdir(parents=True, exist_ok=True)
    for path in (scene_path, drone_path):
        backup = backups / (path.name + '.original')
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    outcome_log = _enable_drone_outcome_log(data_dir)
    if edited != original:
        scene_path.write_bytes(edited)
    if new_drone_text != drone_text:
        drone_path.write_text(new_drone_text)
    settings = {'mouse_sensitivity': sensitivity, 'spawn_protection_sec': spawn_protection,
                'drone_distance_m': drone_distance, 'drone_spawn': drone,
                'scene': scene_path.relative_to(ROOT).as_posix(),
                'scene_sha256': hashlib.sha256(edited).hexdigest(), 'outcome_log': outcome_log}
    (ROOT / '.reproduce/fps-settings.json').write_text(json.dumps(settings, indent=2) + '\n')
    return settings
