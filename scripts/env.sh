#!/usr/bin/env bash
# Source this file; isolate ROS 2 from the ROS Noetic setup in ~/.bashrc.
YOPO_TRACKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export YOPO_TRACKER_ROOT
unset ROS_DISTRO ROS_VERSION
if [[ "${CONDA_DEFAULT_ENV:-}" != yopo ]]; then
    _yopo_conda="${CONDA_EXE:-$(command -v conda || true)}"
    if [[ -z "$_yopo_conda" ]]; then
        echo '找不到 conda，请先安装/初始化 conda。' >&2
        return 1
    fi
    eval "$("$_yopo_conda" shell.bash hook)"
    conda activate yopo
    unset _yopo_conda
fi
unset PYTHONPATH CMAKE_PREFIX_PATH AMENT_PREFIX_PATH COLCON_PREFIX_PATH
unset ROS_PACKAGE_PATH ROS_ROOT ROS_ETC_DIR ROS_MASTER_URI ROS_VERSION ROS_DISTRO
# Discover the toolkit before clearing inherited ROS 1 paths. PyTorch wheels
# already provide their CUDA runtime; a separate toolkit is optional.
_yopo_nvcc="$(command -v nvcc || true)"
_yopo_cuda_root="${YOPO_CUDA_ROOT:-${CUDA_HOME:-}}"
if [[ -z "$_yopo_cuda_root" && -n "$_yopo_nvcc" ]]; then
    _yopo_cuda_root="$(dirname "$(dirname "$(readlink -f "$_yopo_nvcc")")")"
fi
export PATH="$CONDA_PREFIX/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib"
if [[ -n "$_yopo_cuda_root" && -d "$_yopo_cuda_root/bin" ]]; then
    export PATH="$_yopo_cuda_root/bin:$PATH"
    if [[ -d "$_yopo_cuda_root/lib64" ]]; then
        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$_yopo_cuda_root/lib64"
    fi
fi
unset _yopo_nvcc _yopo_cuda_root
export PYTHONNOUSERSITE=1
export QT_QPA_PLATFORM_PLUGIN_PATH="$CONDA_PREFIX/plugins"
export ROS_DOMAIN_ID="${YOPO_ROS_DOMAIN_ID:-42}"
export ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-4}"
if [[ -f "$CONDA_PREFIX/setup.bash" ]]; then
    source "$CONDA_PREFIX/setup.bash"
fi
if [[ -f "$YOPO_TRACKER_ROOT/Controller/install/setup.bash" ]]; then
    source "$YOPO_TRACKER_ROOT/Controller/install/setup.bash"
fi
if [[ -f "$YOPO_TRACKER_ROOT/UnityConnector/install/setup.bash" ]]; then
    source "$YOPO_TRACKER_ROOT/UnityConnector/install/setup.bash"
fi
