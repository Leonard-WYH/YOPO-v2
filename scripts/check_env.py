#!/usr/bin/env python3
"""Check the real ROS 2 messages, GPU and both released policy checkpoints."""
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'YOPO'))
import cv2
import numpy as np
import rclpy
import torch
from quadrotor_msgs.msg import PositionCommand
from config.config import cfg
from config.paths import relative_path
from policy.yopo_network import YopoNetwork


def main():
    if os.environ.get('CONDA_DEFAULT_ENV') != 'yopo':
        raise RuntimeError('Expected existing conda yopo environment')
    if any('/opt/ros/noetic' in p for p in sys.path):
        raise RuntimeError('ROS Noetic paths leaked into ROS 2 process')
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is not available')
    cfg['train'] = False
    rgbd = torch.zeros(1, 4, cfg['image_height'], cfg['image_width'], device='cuda')
    obs = torch.zeros(1, 6, cfg['vertical_num'], cfg['horizon_num'], device='cuda')
    policies = {}
    with torch.inference_mode():
        for trial in (1, 2):
            model = YopoNetwork().cuda().eval()
            weight = ROOT / f'YOPO/saved/YOPO_{trial}/epoch50.pth'
            model.load_state_dict(torch.load(weight, weights_only=True))
            for _ in range(10):
                outputs = model(rgbd, obs)
            torch.cuda.synchronize()
            start = time.perf_counter()
            for _ in range(100):
                outputs = model(rgbd, obs)
            torch.cuda.synchronize()
            assert all(t.isfinite().all().item() for t in outputs)
            policies[str(trial)] = {'weight': relative_path(weight), 'finite': True,
                                   'outputs': [list(t.shape) for t in outputs],
                                   'latency_ms': (time.perf_counter() - start) * 10}
    rclpy.init()
    node = rclpy.create_node('yopo_environment_check')
    publisher = node.create_publisher(PositionCommand, '/yopo_reproduction/check', 1)
    publisher.publish(PositionCommand())
    node.destroy_node()
    rclpy.shutdown()
    report = {'python': sys.version, 'prefix': '${CONDA_PREFIX}', 'torch': torch.__version__,
              'numpy': np.__version__, 'opencv': cv2.__version__,
              'rclpy': importlib.metadata.version('rclpy'),
              'gpu': torch.cuda.get_device_name(0), 'ros_domain': os.environ.get('ROS_DOMAIN_ID'),
              'policies': policies, 'status': 'passed'}
    destination = ROOT / 'logs/environment-check.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
