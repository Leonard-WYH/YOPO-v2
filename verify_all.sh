#!/usr/bin/env bash
# Runs the actual Unity/ROS/GPU demos sequentially on the desktop.
set -eo pipefail
cd "$(dirname "$0")"
./run_demo.sh check
./run_demo.sh tracker --duration 20
./run_demo.sh click --duration 12 --no-rviz
./run_demo.sh keyboard --duration 12 --no-rviz
./run_demo.sh ros --goal 45 -35 0 --duration 15 --no-rviz
./run_demo.sh tracker --controller position --duration 15 --no-rviz
./run_demo.sh tracker --backend tensorrt --duration 20 --no-rviz
./run_demo.sh fps --duration 15
./run_demo.sh fps --backend tensorrt --duration 15 --no-rviz
./run_demo.sh controller --duration 18 --no-rviz
./run_demo.sh collect --count 64
./run_demo.sh dataset
./run_demo.sh ekf
./run_demo.sh train --epochs 1 --batch-size 4 --no-imagenet
source scripts/env.sh
python scripts/summarize_verification.py
echo '全部验证完成；每次运行的统计与截图见 logs/。训练仅验证 1 个 epoch。'
