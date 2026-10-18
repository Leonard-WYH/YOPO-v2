# YOPO-v2 中文复现

本仓库基于 [TJU-Aerial-Robotics/YOPO-Tracker](https://github.com/TJU-Aerial-Robotics/YOPO-Tracker)，整理了 Linux 本地复现、全部 demo 的启动脚本、数据采集、训练和 TensorRT 部署流程。复现使用现有 Conda `yopo` 环境，ROS 2 Humble 通过 RoboStack 安装到同一环境，本机已完成验证，无需 Docker。

上游基线：`d313f8610195dc986caceff7a3616f63d7e6f31f`。原版英文说明见 [README.upstream.md](README.upstream.md)，控制器说明见 [Controller/src/readme.md](Controller/src/readme.md)。原项目版权和 [MIT 许可证](LICENSE) 保留。

## 1. 快速开始

已有可用的 `yopo` 环境时，在桌面终端执行：

```bash
git clone https://github.com/Leonard-WYH/YOPO-v2.git
cd YOPO-v2
./setup.sh
./run_demo.sh
```

`setup.sh` 下载并校验两套官方 Unity 仿真器和 FPS 权重，安装 Python 依赖，编译 Controller 与 ROS-TCP-Endpoint。`run_demo.sh` 自动激活 `yopo`，启动通信桥、控制器、Unity、规划器和 RViz，并自动点击 Connect。

默认追踪中，人物以 3 米/秒按“走 8 秒、停 3 秒”持续循环；到达目标或导航停滞后自动重新选择可行目标。Unity 窗口默认 1600×900。终端按 **Ctrl+C** 或在另一个终端执行 `./run_demo.sh stop`，可停止本次启动的进程。

## 2. 已验证环境

以下是 2026-10-18 本机实际运行环境，并非对所有操作系统和显卡的兼容性承诺。

| 项目 | 已验证配置 |
| --- | --- |
| 系统 | Ubuntu 20.04，Linux x86_64，X11 图形桌面 |
| 显卡 | NVIDIA GeForce RTX 5070 Ti，16 GB |
| NVIDIA 驱动 | 580.105.08 |
| Conda 环境 | `yopo`，Python 3.9.15 |
| ROS 2 | RoboStack Humble，rclpy 3.3.4 |
| PyTorch / torchvision | 2.8.0+cu128 / 0.23.0+cu128 |
| NumPy / OpenCV | 1.22.3 / 4.11.0 |
| TensorRT（可选） | 10.9.0.34 |

已有 ROS Noetic 不影响本项目；脚本会清理继承的 ROS 1 路径，再加载 Conda 中的 ROS 2。Unity demo 需要图形桌面和有效的 `DISPLAY`；纯控制器示例可使用 `--no-rviz` 在无窗口环境运行。

系统工具：

```bash
sudo apt-get update
sudo apt-get install curl xserver-xephyr imagemagick
```

Conda 已存在 `yopo` 时，先确认其 Python 和 GPU 可用：

```bash
conda run -n yopo python --version
conda run -n yopo python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

如果从零配置，可参考不含机器绝对路径的 [environment.yml](environment.yml)：

```bash
conda env create -f environment.yml
conda activate yopo
python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
./setup.sh
```

上面的环境文件提供本次使用的 ROS、Python 和编译依赖组合；现有 `yopo` 不需要重复创建。PyTorch 的 CUDA 版本需匹配显卡和驱动，版本对应关系见 [PyTorch 官方历史版本说明](https://pytorch.org/get-started/previous-versions/)。Python 依赖固定在 [requirements-reproduction.txt](requirements-reproduction.txt)，安装脚本不会主动替换已有 PyTorch。

## 3. 目录与路径约定

```text
YOPO-v2/
├── README.md                       # 中文复现说明
├── README.upstream.md              # 上游原版说明
├── environment.yml                 # 可迁移的 Conda 依赖声明
├── requirements-reproduction.txt   # 已验证的 Python 依赖
├── setup.sh                        # 安装依赖、下载资源、编译 ROS 工作区
├── run_demo.sh                     # 一键启动入口
├── verify_all.sh                   # 顺序验证全部流程
├── scripts/                        # 环境隔离、资源下载、UI 操作、运行监测
├── YOPO/
│   ├── config/paths.py             # 统一解析项目相对路径
│   ├── config/traj_opt.yaml         # 模型、训练和数据集配置
│   ├── test_yopo_ros.py             # ROS 推理节点
│   ├── train_yopo.py                # 训练入口
│   ├── yopo_trt_transfer.py         # TensorRT 导出与数值验证
│   ├── policy/                     # 网络、数据集、轨迹与 EKF
│   └── saved/YOPO_1/epoch50.pth     # 上游普通追踪权重
├── Controller/src/                 # SO3 控制器、动力学和消息定义
├── UnityConnector/src/             # ROS-TCP-Endpoint
├── docs/                           # 上游图片和本次复现统计
├── simulators/                     # 自动下载，不进入 Git
├── dataset/                        # 本地采集，不进入 Git
├── logs/                           # 日志、截图、验证结果，不进入 Git
└── .reproduce/                     # 下载缓存、锁、环境备份，不进入 Git
```

**所有项目路径参数均以仓库根目录为基准**，包括 `--dataset`、`--trt_engine`、TensorRT 导出的 `--dir`、数据集绘图的 `--plot-output` 和环境变量 `YOPO_CONFIG`。例如 `--dataset dataset` 始终指向本仓库的数据目录，不随终端当前目录变化；也支持用户显式传入外部绝对路径。

Shell 入口先定位脚本自身目录，Python 从 `__file__` 定位仓库根目录。因此仓库可以重命名、换目录，也可以在父目录执行：

```bash
./YOPO-v2/run_demo.sh tracker --dataset dataset
```

项目中不保存开发机的用户主目录、Conda 安装位置或固定 CUDA 版本目录。Conda 使用自身的 `CONDA_PREFIX`；CUDA Toolkit 从 `YOPO_CUDA_ROOT`、`CUDA_HOME` 或 PATH 中的 `nvcc` 自动发现。ROS 的安装目录由 ament 查询。Unity 写入数据、ROS 加载资源等场景所需的绝对路径在运行时计算，结果报告保存项目相对路径。

移动含有编译产物的仓库后，先移走两个工作区的 `build/`、`install/`、`log/`，再运行 `./setup.sh` 生成当前位置的 ROS 工作区。`build/`、`install/`、`log/` 含编译器和 colcon 自动生成的路径，不应随源码搬运或提交。系统命令目录、X11 socket 和 ROS 资源 URI 属于运行环境，不是需要手动填写的项目路径。

## 4. 全部 demo 的一键命令

| 功能 | 命令 | 操作说明 |
| --- | --- | --- |
| 默认持续追踪 | `./run_demo.sh` | 自动换目标，持续走走停停 |
| 随机目标追踪 | `./run_demo.sh random` | 与默认 tracker 相同的持续循环 |
| 鼠标点选目标 | `./run_demo.sh click` | 点击 Unity 场景地面选择目标 |
| 键盘控制人物 | `./run_demo.sh keyboard` | W 前进，A/D 转向，Shift+W 跑步 |
| ROS 目标控制 | `./run_demo.sh ros --goal 55 -45 0` | 指定人物的世界坐标目标 |
| 位置控制器追踪 | `./run_demo.sh tracker --controller position` | 使用位置指令与参考状态规划 |
| 原生 C++ 控制示例 | `./run_demo.sh controller` | 位置、速度、加速度指令各运行 5 秒，循环切换 |
| FPS 人机追逐 | `./run_demo.sh fps` | 自动加载专用 YOPO_2 权重 |
| TensorRT 普通追踪 | `./run_demo.sh tracker --backend tensorrt` | 首次缺少引擎时自动构建 |
| TensorRT FPS | `./run_demo.sh fps --backend tensorrt` | 使用 FPS 专用引擎 |
| 采集与导出地图 | `./run_demo.sh collect --count 128` | 新建 scene-N，不覆盖已有场景 |
| 训练 | `./run_demo.sh train --epochs 50 --batch-size 16` | 在已采集数据上训练 |
| 采样分布图 | `./run_demo.sh dataset` | 输出 logs/sampling-distribution.png |
| EKF 示例 | `./run_demo.sh ekf` | 目标状态滤波示例 |
| TensorBoard | `./run_demo.sh tensorboard` | 浏览器访问 http://127.0.0.1:6006 |
| 环境与权重检查 | `./run_demo.sh check` | 检查 ROS 消息、CUDA、两套权重的真实推理 |
| 停止仿真 | `./run_demo.sh stop` | 清理本脚本启动的仿真进程 |

FPS 操作：W/A/S/D 移动，Shift+W 奔跑，鼠标转向，左键射击，R 换弹，P 重生，Esc 释放鼠标。普通追踪中的 Respawn 会重置人物、无人机及规划状态。

人物节奏和窗口大小可以调整：

```bash
./run_demo.sh tracker --walk-seconds 10 --stop-seconds 4 --person-speed 2
./run_demo.sh --window-size 1920 1080
./run_demo.sh --window-size 1280 720
./run_demo.sh tracker --no-rviz --duration 35
```

窗口使用 16:9 分辨率，最低 960×540，以保持自动点击的 UI 坐标一致。`--duration 0` 为持续运行，也是默认值；设置正数时运行结束会保存统计和截图。`--no-rviz` 关闭 RViz，`--manual-connect` 保留手动 Connect。

## 5. 高 DPI 显示与进程管理

默认 `--display auto` 检查桌面 DPI。高 DPI、多屏桌面上，通过独立 96 DPI Xephyr 窗口运行 Unity，避免按钮显示位置与点击区域不一致；使用 Vulkan 在 NVIDIA GPU 上渲染，RViz 留在主桌面。

```bash
./run_demo.sh --display nested       # 强制独立窗口，默认 Vulkan
./run_demo.sh --display native       # 使用主桌面，默认 OpenGL
./run_demo.sh --display nested --graphics vulkan
```

同一仓库只允许一个仿真运行，以避免抢占 Unity Endpoint 的 TCP 10000 端口和 ROS 话题。默认 `ROS_DOMAIN_ID=42`、`ROS_LOCALHOST_ONLY=1`；可通过 `YOPO_ROS_DOMAIN_ID` 修改 domain。启动另一个 demo 前先结束当前仿真。

每次仿真的产物位于 `logs/时间-demo-backend/`，`logs/latest/` 指向最新一次：

- `endpoint.log`、`controller.log`、`planner.log`：各组件日志。
- `unity-player.log`：Unity 渲染、连接和人物状态。
- `unity-start.png`、`unity-final.png`：定时验证截图。
- `result.json`：消息计数、位置变化、非有限数检查、人物走停阶段和运行状态。

## 6. 数据采集与训练

```bash
./run_demo.sh collect --count 128 --dataset dataset
./run_demo.sh dataset --dataset dataset
./run_demo.sh train --dataset dataset --epochs 1 --batch-size 4 --no-imagenet
./run_demo.sh tensorboard
```

第三条命令用于快速验证训练管线，不下载 ImageNet 初始化权重。正式训练可去掉 `--no-imagenet` 并增大 epoch 数。验证 1 个 epoch 不代表从零训练达到论文效果；跟踪 demo 使用官方预训练模型。

采集脚本依次填写保存目录、导出完整森林 PLY、采集 RGB-D 和标签。地图导出在本机约半分钟，导出期间 Unity 暂停响应属于原仿真器行为。每次自动新建下一个 `scene-N`：

```text
dataset/
├── scene-0/
│   ├── rgb/                # RGB 图像
│   ├── depth/              # 深度 PNG
│   ├── labels.csv          # 无人机位姿与目标标签
│   └── environment.ply     # 环境点云
└── scene-1/
```

配置文件中的 `dataset_path`、`val_dataset_path`、`public_dataset_path` 均相对于仓库根目录。验证集不存在时跳过验证；公共检测数据不存在时自动禁用混合采样，不影响仅使用 Unity 数据训练。训练会新建 `YOPO/saved/YOPO_N/`，保留官方 YOPO_1 和 YOPO_2。

## 7. TensorRT 导出与推理

普通 PyTorch demo 不依赖 TensorRT。本机已验证 TensorRT 10.9.0.34；其他机器可先按照 [NVIDIA 安装说明](https://docs.nvidia.com/deeplearning/tensorrt/latest/installing-tensorrt/install-pip.html) 配置兼容版本，例如 CUDA 12 对应包：

```bash
conda activate yopo
python -m pip install tensorrt-cu12==10.9.0.34
python -c "import tensorrt as trt; print(trt.__version__)"
./run_demo.sh export --trial 1
./run_demo.sh export --trial 2
./run_demo.sh tracker --backend tensorrt
./run_demo.sh fps --backend tensorrt
```

使用原生 TensorRT 10 接口，通过 ONNX 导出，不要求安装旧版 torch2trt。每次导出都会比较 PyTorch/TensorRT 输出、检查数值并记录推理时间：

| 模式 | 引擎 | 数值与测速报告 |
| --- | --- | --- |
| 普通追踪 | YOPO/yopo_tracker_trt.engine | [YOPO/yopo_tracker_trt.json](YOPO/yopo_tracker_trt.json) |
| FPS | YOPO/yopo_fps_trt.engine | [YOPO/yopo_fps_trt.json](YOPO/yopo_fps_trt.json) |

本机 FP16 单网络测试约为普通追踪 0.297 ms、FPS 0.204 ms，不代表整套 ROS 闭环延迟。引擎不进入 Git；换显卡或 TensorRT 版本后应在目标机器重新导出。

## 8. 验证与复现结果

运行完整顺序验证：

```bash
./verify_all.sh
```

脚本依次运行环境检查、普通/鼠标/键盘/ROS 追踪、两种控制器、TensorRT、两种 FPS 后端、原生 C++ 控制、数据采集、采样图、EKF 和 1 个 epoch 的训练，最后生成 `logs/reproduction-report.json`。验证会新建采集场景和训练检查点；Unity 窗口需保持可见，不要在自动操作期间点击其他控件。

本次复现的统计快照见 [docs/reproduction-results.json](docs/reproduction-results.json)：

| 验证项目 | 已验证结果 |
| --- | --- |
| 仿真/控制组合 | 9/9 通过，包含 PyTorch、TensorRT、普通/FPS 和原生 C++ 控制 |
| 数据采集 | 两个场景，共 128 组真实 RGB-D/标签，每个场景均有环境 PLY |
| 训练 | 完成 1 个 epoch，检查点及损失均为有限数 |
| TensorBoard | 本机 HTTP 200，训练曲线可读取 |
| 持续走停 | 连续 60 秒，6 段行走、5 次停留、4 次目标选择；稳定停留阶段速度为 0 |
| 放大窗口 | 1600×900 普通追踪、1920×1080 FPS 已验证 |
| 目录迁移 | 仓库外重编译 5+1 个 ROS 包；相对路径绘图、训练、TensorRT 导出、普通/FPS 追踪及采集均通过 |

统计快照只保存测试结果和相对证据路径，不包含原始本地日志、数据集、训练产物或下载缓存。当前运行结果以 `logs/` 下新生成的记录为准。

## 9. 常见问题

**找不到 Conda、ROS 消息或 rclpy：** 在能使用 Conda 的桌面终端执行 `./setup.sh`，不要在另一个 ROS 发行版环境中单独启动组件。需要手动使用 ROS 命令时先执行 `source scripts/env.sh`，确保各终端的 ROS domain 一致。

**Unity 按钮点不中或窗口太小：** 使用 `--display nested`，并通过 `--window-size 1600 900` 或 `1920 1080` 调整。普通追踪脚本会根据图像话题确认连接，首次渲染较慢时自动重试 Connect。

**启动提示端口占用或已有 demo：** 先执行 `./run_demo.sh stop`。脚本只管理自身启动的进程；其他项目占用的 TCP 10000 需要在对应项目中停止。

**没有训练场景：** 先执行 `./run_demo.sh collect --dataset dataset`，确认场景内有 RGB、深度、`labels.csv` 和 `environment.ply`，再训练。

**移动仓库后 ROS 仍指向旧目录：** 移走或清理两个工作区的 `build/`、`install/`、`log/` 后重新执行 `./setup.sh`。不要把生成的工作区当源码复制到另一台机器。

**下载中断：** 重新执行 `./setup.sh`。资源下载支持续传和重试，并使用 SHA256 校验；资源 URL 与校验值保存在 `scripts/fetch_assets.py` 和生成的 `.reproduce/assets.json` 中。

## 10. 上游与许可

算法、官方权重、Unity 仿真器和原始图示来自 [YOPO-Tracker](https://github.com/TJU-Aerial-Robotics/YOPO-Tracker)。本仓库新增了本机环境适配、统一相对路径、自动启动与清理、走停循环、高 DPI 窗口和验证脚本。仿真器仍从上游 Releases 下载，未把二进制包放入 Git。

论文：*YOPOv2-Tracker: An End-to-End Agile Tracking and Navigation Framework*，IEEE Transactions on Robotics，2026。原论文信息与引用格式见 [上游说明](README.upstream.md)。源码遵循 [MIT License](LICENSE)，第三方 ROS-TCP-Endpoint、Boost/Odeint 等组件保留各自目录中的许可证。
