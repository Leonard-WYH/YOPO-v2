#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
mkdir -p logs .reproduce/backups
if ! conda env list | awk '{print $1}' | grep -qx yopo; then
    echo '需要已有的 conda yopo 环境。' >&2
    exit 1
fi
if [[ ! -f .reproduce/backups/yopo-conda-before.txt ]]; then
    conda list -n yopo --explicit > .reproduce/backups/yopo-conda-before.txt
    conda run -n yopo python -m pip freeze > .reproduce/backups/yopo-pip-before.txt
fi
if ! conda run -n yopo python -c 'import rclpy, ament_package' >/dev/null 2>&1; then
    echo '安装 Python 3.9 对应的 ROS 2 Humble，保留 yopo 的 CUDA/PyTorch。'
    conda install -y -n yopo --override-channels -c robostack-humble -c conda-forge \
        'python=3.9' 'numpy=1.22.3' 'libffi>=3.4' \
        ros-humble-ros-base ros-humble-rviz2 colcon-common-extensions \
        compilers 'cmake<3.24' make
fi
source scripts/env.sh
if [[ -f .reproduce/backups/libffi.so.7.1.0 ]]; then
    cp -an .reproduce/backups/libffi.so.7* "$CONDA_PREFIX/lib/"
fi
python -m pip install -r requirements-reproduction.txt
# Some historical RoboStack wheels carry Python 3.7-only metadata despite being pure Python.
python -m pip install --no-deps --force-reinstall \
    'colcon-library-path==0.2.1' 'colcon-test-result==0.3.8' 'colcon-notification==0.3.0' 'notify2==0.3.1'
python scripts/fetch_assets.py
echo '编译 Controller 和 UnityConnector ...'
(cd Controller && colcon build --symlink-install --parallel-workers 4 --event-handlers desktop_notification- \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DPython3_EXECUTABLE="$CONDA_PREFIX/bin/python" \
    '-DCMAKE_CXX_FLAGS=-include cstdint')
source Controller/install/setup.bash
(cd UnityConnector && colcon build --symlink-install --event-handlers desktop_notification-)
conda list --explicit > .reproduce/yopo-conda-lock.txt
python -m pip freeze > .reproduce/yopo-pip-lock.txt
echo '安装完成。运行 ./run_demo.sh，或 ./run_demo.sh --help。'
