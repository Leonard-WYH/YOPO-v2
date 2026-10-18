"""Scene folders in one fixed order, so YOPODataset's map_idx indexes SafetyLoss's ESDF maps.

dataset_path holds the training scenes and val_dataset_path the validation ones. The global index
is the position in the concatenated list, training root first, so the two roots may reuse scene
numbers. A missing val_dataset_path contributes nothing and validation is simply skipped.
"""
import os

from config.config import cfg
from config.paths import project_path

_ROOT_KEYS = {'train': "dataset_path", 'valid': "val_dataset_path"}


def _scan(mode):
    root = cfg[_ROOT_KEYS[mode]]          # read here, not at import, so cfg stays overridable
    if not root:
        return []
    path = project_path(root)
    if not path.is_dir():
        return []
    dirs = [f.path for f in os.scandir(path)
            if f.is_dir() and os.path.basename(f.path).startswith("scene-")]
    return sorted(dirs, key=lambda p: int(os.path.basename(p).split("-")[1]))


def scene_dirs():
    """[(mode, path)] for every scene, training scenes first."""
    return [(mode, path) for mode in ('train', 'valid') for path in _scan(mode)]


def scene_dirs_for(mode):
    """[(global index, path)] for one mode; the index is the map_idx SafetyLoss expects."""
    return [(i, path) for i, (m, path) in enumerate(scene_dirs()) if m == mode]
