#!/usr/bin/env python3
"""Launch all upstream YOPO-Tracker demos in the existing yopo environment."""
import argparse
from collections import defaultdict
from datetime import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
YOPO = ROOT / 'YOPO'
sys.path.insert(0, str(YOPO))
from config.paths import project_path, relative_path


class Processes:
    def __init__(self, logs):
        self.logs = logs
        self.children = []

    def start(self, name, argv, cwd=ROOT, env=None):
        stream = (self.logs / f'{name}.log').open('w')
        proc = subprocess.Popen([str(arg) for arg in argv], cwd=cwd, env=env,
                                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        stream.close()
        self.children.append((name, proc))
        print(f'启动 {name}: PID {proc.pid}', flush=True)
        return proc

    def check(self):
        for name, child in self.children:
            if child.poll() is not None:
                raise RuntimeError(f'{name} exited ({child.returncode}); see {self.logs / (name + ".log")}')

    def close(self):
        for name, child in reversed(self.children):
            if child.poll() is None and name != 'display':
                try:
                    os.killpg(child.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 8
        while any(child.poll() is None for name, child in self.children if name != 'display') and time.monotonic() < deadline:
            time.sleep(0.1)
        for _, child in reversed(self.children):
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for _, child in self.children:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


class Monitor:
    def __init__(self):
        import rclpy
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import Image
        from nav_msgs.msg import Odometry
        from quadrotor_msgs.msg import PositionCommand
        from geometry_msgs.msg import PoseStamped, Vector3
        from std_msgs.msg import Bool, Float32
        self.rclpy = rclpy
        rclpy.init()
        self.node = rclpy.create_node(f'yopo_demo_monitor_{os.getpid()}')
        self.counts = defaultdict(int)
        self.positions = {}
        self.origins = {}
        self.max_displacement = defaultdict(float)
        self.bad_values = 0
        self.allow_partial_commands = False
        self.command_modes = set()
        self.last_rgb = None
        self.last_depth = None
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        topics = [('rgb', Image, '/drone_0/rgb'), ('depth', Image, '/drone_0/depth'),
                  ('drone', Odometry, '/drone_0/odom'), ('character', Odometry, '/character_0/odom'),
                  ('command', PositionCommand, '/so3_control/pos_cmd'),
                  ('target', PoseStamped, '/yopo_net/target_pred')]
        self.subscriptions = [self.node.create_subscription(typ, topic,
                              lambda msg, key=key: self.receive(key, msg), qos)
                              for key, typ, topic in topics]
        self.goal = self.node.create_publisher(Vector3, '/character_0/nav_goal', 1)
        self.character_speed = self.node.create_publisher(Float32, '/characters/set_speed', 1)
        self.respawn = self.node.create_publisher(Bool, '/respawn', 1)

    def receive(self, key, msg):
        self.counts[key] += 1
        if key in ('drone', 'character'):
            p = msg.pose.pose.position
            values = (p.x, p.y, p.z)
            if not all(math.isfinite(v) for v in values):
                self.bad_values += 1
            self.positions[key] = values
            if key not in self.origins:
                self.origins[key] = values
            self.max_displacement[key] = max(self.max_displacement[key], math.dist(values, self.origins[key]))
        elif key == 'command':
            position = (msg.position.x, msg.position.y, msg.position.z)
            velocity = (msg.velocity.x, msg.velocity.y, msg.velocity.z)
            acceleration = (msg.acceleration.x, msg.acceleration.y, msg.acceleration.z)
            mode = 'position' if all(math.isfinite(v) for v in position) else (
                'velocity' if all(math.isfinite(v) for v in velocity) else 'acceleration')
            self.command_modes.add(mode)
            if not all(math.isfinite(v) for v in acceleration) or (
                    not self.allow_partial_commands and not all(math.isfinite(v) for v in position)):
                self.bad_values += 1
        elif key == 'rgb':
            self.last_rgb = msg
        elif key == 'depth':
            self.last_depth = msg

    def spin(self, seconds, processes=None):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.rclpy.spin_once(self.node, timeout_sec=0.05)
            if processes:
                processes.check()

    def send_goal(self, x, y, z=0):
        from geometry_msgs.msg import Vector3
        self.goal.publish(Vector3(x=float(x), y=float(y), z=float(z)))

    def reset(self):
        from std_msgs.msg import Bool
        self.respawn.publish(Bool(data=True))

    def set_character_speed(self, speed):
        from std_msgs.msg import Float32
        self.character_speed.publish(Float32(data=float(speed)))

    def report(self):
        return {'messages': dict(self.counts), 'positions': self.positions,
                'max_displacement_m': dict(self.max_displacement), 'nonfinite_values': self.bad_values,
                'command_modes': sorted(self.command_modes)}

    def close(self):
        self.node.destroy_node()
        self.rclpy.try_shutdown()


class WalkStopMotion:
    """Keep NavMesh navigation active, with deliberate pauses between walks."""

    def __init__(self, monitor, ui, walk_seconds, stop_seconds, speed):
        self.monitor, self.ui = monitor, ui
        self.walk_seconds, self.stop_seconds, self.speed = walk_seconds, stop_seconds, speed
        self.started = time.monotonic()
        self.phases = []
        self.goal_requests = 0
        self.last_sample = self.started
        self.last_position = monitor.positions.get('character')
        self.last_moving = self.started
        self.set_phase('walk', self.started)
        self.new_goal()

    def set_phase(self, phase, now):
        if self.phases:
            self.phases[-1]['ended_sec'] = round(now - self.started, 3)
        self.phase = phase
        self.phase_started = now
        self.deadline = now + (self.walk_seconds if phase == 'walk' else self.stop_seconds)
        self.last_moving = now
        self.monitor.set_character_speed(self.speed if phase == 'walk' else 0)
        self.phases.append({'phase': phase, 'started_sec': round(now - self.started, 3),
                            'distance_m': 0.0, 'steady_speeds_mps': []})
        print(f'人物：{"行走" if phase == "walk" else "停留"} '
              f'{self.walk_seconds if phase == "walk" else self.stop_seconds:g} 秒', flush=True)

    def new_goal(self):
        # Unity's button samples the NavMesh, so destinations avoid tree trunks
        # and other non-walkable ground. Only request another when needed.
        self.ui.click(1140, 160)
        self.goal_requests += 1
        self.last_moving = time.monotonic()
        print(f'人物：选择第 {self.goal_requests} 个随机导航目标', flush=True)

    def update(self):
        now = time.monotonic()
        if now >= self.deadline:
            self.set_phase('stop' if self.phase == 'walk' else 'walk', now)
        if now - self.last_sample < 0.5:
            return
        position = self.monitor.positions.get('character')
        if position is not None and self.last_position is not None:
            distance = math.dist(position, self.last_position)
            speed = distance / (now - self.last_sample)
            self.phases[-1]['distance_m'] += distance
            # Exclude acceleration/deceleration when measuring actual pauses.
            if now - self.phase_started >= 1:
                self.phases[-1]['steady_speeds_mps'].append(speed)
            if self.phase == 'walk':
                if speed > 0.15:
                    self.last_moving = now
                elif now - self.last_moving >= 2:
                    # Reaching a destination must not end the demo. This also
                    # recovers automatically after Respawn or an invalid path.
                    self.new_goal()
        self.last_sample, self.last_position = now, position

    def report(self):
        phases = []
        for phase in self.phases:
            entry = {key: value for key, value in phase.items() if key != 'steady_speeds_mps'}
            speeds = phase['steady_speeds_mps']
            entry.update(distance_m=round(phase['distance_m'], 3), samples=len(speeds),
                         mean_speed_mps=round(sum(speeds) / len(speeds), 3) if speeds else None,
                         max_speed_mps=round(max(speeds), 3) if speeds else None)
            phases.append(entry)
        return {'walk_seconds': self.walk_seconds, 'stop_seconds': self.stop_seconds,
                'speed_mps': self.speed, 'goal_requests': self.goal_requests, 'phases': phases}


def parser():
    p = argparse.ArgumentParser(description='YOPO-Tracker 一键启动（现有 conda yopo / 本机 ROS 2 Humble）')
    p.add_argument('demo', nargs='?', default='tracker',
                   choices=['tracker', 'random', 'click', 'keyboard', 'ros', 'fps', 'collect', 'controller',
                            'train', 'tensorboard', 'export', 'dataset', 'ekf', 'check', 'stop'])
    p.add_argument('--backend', choices=['torch', 'tensorrt'], default='torch')
    p.add_argument('--graphics', choices=['glcore', 'vulkan'])
    p.add_argument('--display', choices=['auto', 'native', 'nested'], default='auto',
                   help='auto 在高 DPI 桌面使用独立的 96 DPI Unity 窗口')
    p.add_argument('--window-size', nargs=2, type=int, default=(1600, 900), metavar=('WIDTH', 'HEIGHT'),
                   help='Unity 窗口尺寸，默认 1600 900，使用 16:9 分辨率')
    p.add_argument('--walk-seconds', type=float, default=8, help='tracker/random 每轮行走秒数')
    p.add_argument('--stop-seconds', type=float, default=3, help='tracker/random 每轮停留秒数')
    p.add_argument('--person-speed', type=float, default=3, help='tracker/random 人物行走速度，米/秒')
    p.add_argument('--controller', choices=['attitude', 'position'], default='attitude')
    p.add_argument('--no-rviz', action='store_true')
    p.add_argument('--manual-connect', action='store_true', help='手动点击 Unity Connect')
    p.add_argument('--duration', type=float, default=0, help='验证运行秒数，0 表示持续运行')
    p.add_argument('--goal', nargs=3, type=float, metavar=('X', 'Y', 'Z'))
    p.add_argument('--count', type=int, default=128, help='采集样本数')
    p.add_argument('--dataset', default='dataset', help='训练数据目录，相对于仓库根目录')
    p.add_argument('--epochs', type=int, default=50)
    p.add_argument('--batch-size', type=int, default=16)
    p.add_argument('--trial', type=int, choices=[1, 2], help='导出模型：1 普通追踪 / 2 FPS')
    p.add_argument('--no-imagenet', action='store_true')
    return p


def needs_nested_display():
    from Xlib import display, X
    connection = display.Display()
    try:
        root = connection.screen().root
        prop = root.get_full_property(connection.intern_atom('RESOURCE_MANAGER'), X.AnyPropertyType)
        resources = prop.value.decode(errors='replace') if prop is not None else ''
        match = re.search(r'Xft\.dpi:\s*([\d.]+)', resources)
        return bool(match and float(match.group(1)) > 120)
    finally:
        connection.close()


def simple_action(args):
    if args.demo == 'train':
        command = [sys.executable, 'train_yopo.py', '--dataset', args.dataset,
                   '--epochs', str(args.epochs), '--batch-size', str(args.batch_size)]
        if args.no_imagenet:
            command.append('--no-imagenet')
    elif args.demo == 'tensorboard':
        command = [sys.executable, '-m', 'tensorboard.main', '--logdir', str(YOPO / 'saved'),
                   '--host', '127.0.0.1', '--port', '6006']
    elif args.demo == 'export':
        trial = args.trial or 1
        command = [sys.executable, 'yopo_trt_transfer.py', '--trial', str(trial), '--dir',
                   'YOPO/yopo_fps_trt.engine' if trial == 2 else 'YOPO/yopo_tracker_trt.engine']
    elif args.demo == 'dataset':
        command = [sys.executable, 'policy/yopo_dataset.py', '--dataset', args.dataset,
                   '--plot-output', str(ROOT / 'logs/sampling-distribution.png'), '--skip-benchmark']
    elif args.demo == 'ekf':
        command = [sys.executable, 'policy/target_ekf.py']
    else:
        command = [sys.executable, str(ROOT / 'scripts/check_env.py')]
    return subprocess.call(command, cwd=YOPO)


def main():
    args = parser().parse_args()
    if args.demo == 'controller' and __debug__:
        # Early Humble Python message setters reject NaN in float64 fields.
        # The upstream C++ example intentionally uses NaN to disable lower-order
        # setpoints. -O omits those generated debug assertions in this monitor;
        # the explicit numerical checks above still validate the vehicle state.
        os.execv(sys.executable, [sys.executable, '-O', '-u', str(Path(__file__).resolve()), *sys.argv[1:]])
    if args.count <= 0 or args.duration < 0 or args.epochs <= 0 or args.batch_size <= 0:
        raise SystemExit('count/epochs/batch-size 必须 > 0；duration 必须 >= 0')
    if not all(math.isfinite(value) and value > 0 for value in
               (args.walk_seconds, args.stop_seconds, args.person_speed)):
        raise SystemExit('walk-seconds/stop-seconds/person-speed 必须是有限正数')
    width, height = args.window_size
    if width < 960 or height < 540 or width * 9 != height * 16:
        raise SystemExit('window-size 请使用至少 960×540 的 16:9 分辨率，例如 1600 900 或 1920 1080')
    state_dir = ROOT / '.reproduce'
    state_dir.mkdir(exist_ok=True)
    pid_file = state_dir / 'demo.pid'
    if args.demo == 'stop':
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pid_file.unlink(missing_ok=True)
            deadline = time.monotonic() + 20
            while pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            if pid_file.exists():
                raise RuntimeError('停止超时，请查看本次 demo 的进程与日志。')
            print('全部 demo 进程已停止。')
        else:
            print('当前没有由本脚本启动的仿真。')
        return 0
    if args.demo in ('train', 'tensorboard', 'export', 'dataset', 'ekf', 'check'):
        return simple_action(args)
    if not os.environ.get('DISPLAY') and not (args.demo == 'controller' and args.no_rviz):
        raise SystemExit('Unity 需要图形桌面 DISPLAY。请在本机桌面终端运行。')
    lock = (state_dir / 'demo.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('已有 demo 运行中；先执行 ./run_demo.sh stop。')
    with socket.socket() as port:
        port.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            port.bind(('127.0.0.1', 10000))
        except OSError:
            raise SystemExit('TCP 10000 端口已占用，请先停止其他 Unity Endpoint。')
    pid_file.write_text(str(os.getpid()))
    log_backend = 'cpp' if args.demo == 'controller' else args.backend
    log_dir = ROOT / 'logs' / f'{datetime.now():%Y%m%d-%H%M%S}-{args.demo}-{log_backend}'
    log_dir.mkdir(parents=True)
    latest = ROOT / 'logs/latest'
    latest.unlink(missing_ok=True)
    latest.symlink_to(log_dir.name, target_is_directory=True)
    processes = Processes(log_dir)
    monitor = None
    ui = None
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        monitor = Monitor()
        if args.demo == 'controller':
            return controller_demo(args, monitor, processes, log_dir)
        processes.start('endpoint', ['ros2', 'run', 'ros_tcp_endpoint', 'default_server_endpoint',
                                    '--ros-args', '-p', 'ROS_IP:=127.0.0.1'])
        if args.demo != 'collect':
            processes.start('controller', ['ros2', 'launch', 'so3_quadrotor_simulator',
                                          f'simulator_{args.controller}_control.launch.py'])
        monitor.spin(2, processes)
        simulator = ROOT / 'simulators' / ('fps' if args.demo == 'fps' else 'tracker')
        binaries = list(simulator.rglob('Tracker.x86_64'))
        if not binaries:
            raise RuntimeError('仿真器尚未安装，先运行 ./setup.sh')
        unity_env = dict(os.environ)
        unity_env['SDL_VIDEO_HIGHDPI_DISABLED'] = '1'
        for variable in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_PLUGIN_PATH'):
            unity_env.pop(variable, None)
        nested = args.display == 'nested' or (args.display == 'auto' and needs_nested_display())
        graphics = args.graphics or ('vulkan' if nested else 'glcore')
        if nested:
            for number in range(90, 110):
                if not Path(f'/tmp/.X11-unix/X{number}').exists():
                    break
            else:
                raise RuntimeError('没有可用的独立 X11 display')
            processes.start('display', ['Xephyr', f':{number}', '-screen', f'{width}x{height}', '-ac',
                                       '-noreset', '-nolisten', 'tcp', '-dpi', '96', '-title',
                                       f'YOPO-Tracker - {args.demo}'], env=unity_env)
            for _ in range(50):
                if Path(f'/tmp/.X11-unix/X{number}').exists():
                    break
                monitor.spin(0.1, processes)
            else:
                raise RuntimeError('Xephyr 没有启动，请查看 display.log')
            unity_env['DISPLAY'] = f':{number}'
            print(f'高 DPI 兼容窗口：{unity_env["DISPLAY"]}，GPU 渲染：{graphics}', flush=True)
        unity = processes.start('unity', [binaries[0], '-screen-fullscreen', '0',
                                         '-screen-width', str(width), '-screen-height', str(height),
                                         '-popupwindow', f'-force-{graphics}', '-logFile', log_dir / 'unity-player.log'],
                                cwd=binaries[0].parent, env=unity_env)
        from unity_ui import UnityUI
        ui = UnityUI(unity.pid, display_name=unity_env['DISPLAY'], window_size=args.window_size)
        monitor.spin(5, processes)
        if args.demo == 'fps':
            ui.tap('Escape')
            monitor.spin(0.5, processes)
        if not args.manual_connect:
            ui.connect()
        else:
            print('请在 Unity 左上角点击 Connect。', flush=True)
        monitor.spin(2, processes)
        # Higher resolutions can spend several seconds compiling the first
        # frame. Retry clicks until image topics confirm the UI accepted them.
        connect_deadline = time.monotonic() + 60
        next_connect = time.monotonic()
        while not (monitor.counts['rgb'] and monitor.counts['depth']):
            monitor.spin(0.2, processes)
            if time.monotonic() > connect_deadline:
                raise RuntimeError('Unity 连接超时，请检查 Connect、endpoint.log 和 unity-player.log')
            if not args.manual_connect and time.monotonic() >= next_connect:
                ui.connect()
                next_connect = time.monotonic() + 3
        if args.demo == 'fps':
            # The shooter gates movement on its own cursorLocked flag. Escape
            # toggles that flag; clicking alone only fires while already locked.
            ui.tap('Escape')
            ui.click(640, 360)
        if args.demo == 'collect':
            return collect(args, ui, monitor, processes, log_dir)
        trial = 2 if args.demo == 'fps' else 1
        planner = [sys.executable, '-u', 'test_yopo_ros.py', '--trial', str(trial), '--epoch', '50',
                   '--plan_from_reference', '1' if args.controller == 'position' else '0', '--verbose', '1']
        if args.backend == 'tensorrt':
            engine = YOPO / ('yopo_fps_trt.engine' if trial == 2 else 'yopo_tracker_trt.engine')
            if not engine.exists():
                print('首次启动：构建本机 TensorRT engine ...', flush=True)
                subprocess.run([sys.executable, 'yopo_trt_transfer.py', '--trial', str(trial),
                                '--dir', str(engine)], cwd=YOPO, check=True)
            planner += ['--use_tensorrt', '1', '--trt_engine', str(engine)]
        processes.start('planner', planner, cwd=YOPO)
        if not args.no_rviz:
            processes.start('rviz', ['rviz2', '-d', YOPO / 'yopo.rviz'])
        deadline = time.monotonic() + 60
        while not (monitor.counts['rgb'] >= 5 and monitor.counts['depth'] >= 5 and monitor.counts['command'] >= 3):
            monitor.spin(0.2, processes)
            if time.monotonic() > deadline:
                raise RuntimeError(f'闭环启动超时：{monitor.report()}；检查 Unity Connect 与日志。')
        print('RGB-D → YOPO → 控制器 → 无人机闭环已就绪。', flush=True)
        motion = None
        if args.demo in ('tracker', 'random'):
            motion = WalkStopMotion(monitor, ui, args.walk_seconds, args.stop_seconds, args.person_speed)
        elif args.demo == 'click':
            ui.click(1184, 320)
            if args.duration:
                ui.click(760, 480)
        elif args.demo == 'keyboard':
            ui.click(1184, 384)
            if args.duration:
                ui.key('w', True)
                try:
                    monitor.spin(2, processes)
                finally:
                    ui.key('w', False)
        elif args.demo == 'ros':
            goal = args.goal or [45, -35, 0]
            for _ in range(3):
                monitor.send_goal(*goal)
                monitor.spin(0.2, processes)
        elif args.demo == 'fps' and args.duration:
            ui.focus()
            ui.key('w', True)
            try:
                monitor.spin(2, processes)
            finally:
                ui.key('w', False)
        ui.screenshot(log_dir / 'unity-start.png')
        print(f'日志：{log_dir}\nCtrl+C 或 ./run_demo.sh stop 可停止全部进程。', flush=True)
        start = time.monotonic()
        while not args.duration or time.monotonic() - start < args.duration:
            monitor.spin(0.2, processes)
            if motion:
                motion.update()
        ui.screenshot(log_dir / 'unity-final.png')
        report = monitor.report()
        report.update({'demo': args.demo, 'backend': args.backend, 'controller': args.controller,
                       'duration_sec': time.monotonic() - start,
                       'display': 'nested' if nested else 'native', 'graphics': graphics,
                       'window_size': [ui.width, ui.height]})
        if motion:
            report['person_motion'] = motion.report()
        moved = report['max_displacement_m'].get('character', 0) >= 0.5
        require_movement = args.duration >= 5 and args.demo in ('tracker', 'random', 'click', 'keyboard', 'ros')
        report['status'] = 'passed' if not report['nonfinite_values'] and (not require_movement or moved) else 'failed'
        (log_dir / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
        if report['nonfinite_values']:
            raise RuntimeError('检测到非有限控制量或位置')
        if require_movement:
            if not moved:
                raise RuntimeError('人物没有按操作移动，交互验证失败，请检查 Unity 窗口')
        return 0
    except KeyboardInterrupt:
        print('\n正在停止本次 demo 的全部进程 ...', flush=True)
        return 0
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if ui:
            ui.close()
        processes.close()
        if monitor:
            monitor.close()
        pid_file.unlink(missing_ok=True)


def controller_demo(args, monitor, processes, log_dir):
    monitor.allow_partial_commands = True
    processes.start('controller', ['ros2', 'launch', 'so3_quadrotor_simulator',
                                  'simulator_position_control.launch.py',
                                  'tracker_x:=0.0', 'tracker_y:=0.0', 'tracker_z:=1.0'])
    monitor.spin(2, processes)
    processes.start('commands', ['ros2', 'run', 'so3_control', 'control_example', '--ros-args',
                                '-r', '/position_cmd:=/so3_control/pos_cmd'])
    if not args.no_rviz:
        processes.start('rviz', ['rviz2', '-d', YOPO / 'yopo.rviz'])
    print('原生 C++ 控制示例：位置 → 速度 → 加速度，每种模式 5 秒循环。', flush=True)
    start = time.monotonic()
    while not args.duration or time.monotonic() - start < args.duration:
        monitor.spin(0.1, processes)
    report = monitor.report()
    passed = (report['nonfinite_values'] == 0 and report['messages'].get('drone', 0) > 100 and
              set(report['command_modes']) == {'position', 'velocity', 'acceleration'})
    report.update({'demo': 'controller', 'backend': 'cpp', 'controller': 'position',
                   'duration_sec': time.monotonic() - start, 'status': 'passed' if passed else 'failed'})
    (log_dir / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    return 0 if passed else 1


def collect(args, ui, monitor, processes, log_dir):
    root = project_path(args.dataset)
    existing = [int(p.name.split('-')[1]) for p in root.glob('scene-*') if p.name.split('-')[1].isdigit()]
    scene = root / f'scene-{max(existing, default=-1) + 1}'
    scene.mkdir(parents=True)
    ui.text(340, 685, str(scene))
    ui.text(240, 627, str(args.count))
    ui.click(432, 565)  # Save PLY
    # Unity exports the full forest synchronously (~30 s on this machine).
    # Input events sent during that export are discarded.
    map_deadline = time.monotonic() + 180
    previous_size = -1
    while time.monotonic() < map_deadline:
        monitor.spin(2, processes)
        map_file = scene / 'environment.ply'
        size = map_file.stat().st_size if map_file.exists() else 0
        if size > 0 and size == previous_size:
            break
        previous_size = size
    else:
        raise RuntimeError(f'Unity 地图导出超时：{scene}')
    ui.click(140, 565)  # CollectData
    deadline = time.monotonic() + max(180, args.count * 2)
    while time.monotonic() < deadline:
        monitor.spin(1, processes)
        rgb = [p for p in (scene / 'rgb').glob('*') if p.suffix.lower() in ('.jpg', '.jpeg', '.png')]
        depth = list((scene / 'depth').glob('*.png'))
        labels = scene / 'labels.csv'
        if len(rgb) >= args.count and len(depth) >= args.count and labels.exists():
            monitor.spin(2, processes)
            ui.screenshot(log_dir / 'collection.png')
            report = {'scene': relative_path(scene), 'rgb': len(rgb), 'depth': len(depth),
                      'map_bytes': (scene / 'environment.ply').stat().st_size,
                      'labels': len(labels.read_text().splitlines()) - 1}
            (log_dir / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2), flush=True)
            return 0
    raise RuntimeError(f'采集超时，请查看 {scene} 和 {log_dir}')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f'启动失败：{exc}', file=sys.stderr)
        sys.exit(1)
