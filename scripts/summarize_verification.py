#!/usr/bin/env python3
"""Gather actual demo results, collected data, TensorRT checks and training events."""
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'YOPO'))
from config.paths import portable_report
EXPECTED = [
    ('tracker', 'torch', 'attitude'), ('click', 'torch', 'attitude'),
    ('keyboard', 'torch', 'attitude'), ('ros', 'torch', 'attitude'),
    ('tracker', 'torch', 'position'), ('tracker', 'tensorrt', 'attitude'),
    ('fps', 'torch', 'attitude'), ('fps', 'tensorrt', 'attitude'),
    ('controller', 'cpp', 'position'),
]


def main():
    import numpy as np
    import torch
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    good = {}
    collections = []
    for path in sorted((ROOT / 'logs').glob('20*/result.json')):
        result = json.loads(path.read_text())
        result['evidence'] = str(path.relative_to(ROOT))
        if 'demo' not in result:
            collections.append(result)
            continue
        key = (result['demo'], result['backend'], result['controller'])
        messages = result.get('messages', {})
        if result['demo'] == 'controller':
            valid = result.get('status') == 'passed'
        else:
            valid = result['nonfinite_values'] == 0 and min(messages.get(t, 0) for t in ('rgb', 'depth', 'drone', 'command', 'target')) > 0
        if result['demo'] not in ('fps', 'controller'):
            valid = valid and result['max_displacement_m'].get('character', 0) > 0.5
        if valid:
            good[key] = result
    missing = [list(k) for k in EXPECTED if k not in good]

    datasets = []
    for scene in sorted((ROOT / 'dataset').glob('scene-*')):
        label_file = scene / 'labels.csv'
        if not label_file.exists():
            continue
        labels = np.atleast_2d(np.loadtxt(label_file, delimiter=',', skiprows=1))
        rgb = sorted(p.stem for p in (scene / 'rgb').glob('*') if p.suffix.lower() in ('.jpg', '.png', '.jpeg'))
        depth = sorted(p.stem for p in (scene / 'depth').glob('*.png'))
        assert rgb == depth and len(rgb) == len(labels)
        assert np.isfinite(labels[:, :7]).all()
        assert np.allclose(np.linalg.norm(labels[:, 3:7], axis=1), 1, atol=1e-3)
        datasets.append({'scene': str(scene.relative_to(ROOT)), 'samples': len(labels),
                         'visible_target_samples': int(np.isfinite(labels[:, 7:10]).all(axis=1).sum()),
                         'map_bytes': (scene / 'environment.ply').stat().st_size})

    training = []
    for directory in sorted((ROOT / 'YOPO/saved').glob('YOPO_*')):
        if directory.name in ('YOPO_1', 'YOPO_2'):
            continue
        checkpoints = list(directory.glob('epoch*.pth'))
        if not checkpoints:
            continue
        accumulator = EventAccumulator(str(directory))
        accumulator.Reload()
        losses = accumulator.Scalars('Train/TrajLoss')
        assert losses and all(math.isfinite(event.value) for event in losses)
        checkpoint = max(checkpoints, key=lambda p: p.stat().st_mtime)
        state = torch.load(checkpoint, weights_only=True, map_location='cpu')
        assert all(t.isfinite().all().item() for t in state.values())
        training.append({'checkpoint': str(checkpoint.relative_to(ROOT)),
                         'optimization_steps': max(event.step for event in losses) + 1,
                         'scalar_records': len(losses),
                         'all_losses_finite': True, 'checkpoint_finite': True,
                         'scalar_tags': accumulator.Tags()['scalars']})

    report = {
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'environment': json.loads((ROOT / 'logs/environment-check.json').read_text()),
        'demos': [good[k] for k in EXPECTED if k in good], 'missing_demos': missing,
        'collection_runs': collections, 'datasets': datasets, 'training': training,
        'tensorrt': [json.loads((ROOT / f'YOPO/yopo_{name}_trt.json').read_text()) for name in ('tracker', 'fps')],
        'tensorboard_http_200': (ROOT / 'logs/tensorboard-index.html').exists(),
        'dataset_plot': (ROOT / 'logs/sampling-distribution.png').exists(),
        'status': 'passed' if not missing and collections and training else 'incomplete',
    }
    destination = ROOT / 'logs/reproduction-report.json'
    destination.write_text(json.dumps(portable_report(report), indent=2) + '\n')
    print(f'{len(good)}/{len(EXPECTED)} demo combinations passed; {sum(d["samples"] for d in datasets)} real RGB-D samples')
    print(f'Report: {destination}')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
