"""Export the pretrained policy through ONNX and build a TensorRT 10 engine."""
import argparse
import json
from pathlib import Path
import time
import torch
from config.config import cfg
from config.paths import project_path, relative_path
from policy.yopo_network import YopoNetwork
from policy.tensorrt_runtime import TensorRTPolicy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=int, default=1)
    parser.add_argument('--epoch', type=int, default=50)
    parser.add_argument('--dir', default='YOPO/yopo_trt.engine', help='output path, relative to repository root')
    parser.add_argument('--fp16', type=int, choices=(0, 1), default=1)
    parser.add_argument('--iterations', type=int, default=200)
    args = parser.parse_args()
    import tensorrt as trt
    if not torch.cuda.is_available():
        raise RuntimeError('TensorRT conversion requires CUDA')
    cfg['train'] = False
    base = Path(__file__).resolve().parent
    weight = base / f'saved/YOPO_{args.trial}/epoch{args.epoch}.pth'
    output = project_path(args.dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    policy = YopoNetwork().cuda().eval()
    policy.load_state_dict(torch.load(weight, weights_only=True))
    torch.manual_seed(0)
    rgbd = torch.rand(1, 4, cfg['image_height'], cfg['image_width'], device='cuda')
    obs = torch.randn(1, 6, cfg['vertical_num'], cfg['horizon_num'], device='cuda') * 0.1
    onnx_path = output.with_suffix('.onnx')
    with torch.inference_mode():
        torch.onnx.export(policy, (rgbd, obs), str(onnx_path), opset_version=17,
                          input_names=['rgbd', 'obs'], output_names=list(TensorRTPolicy.output_names),
                          dynamo=False)
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    onnx_parser = trt.OnnxParser(network, logger)
    if not onnx_parser.parse(onnx_path.read_bytes()):
        raise RuntimeError('\n'.join(str(onnx_parser.get_error(i)) for i in range(onnx_parser.num_errors)))
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1 << 30)
    if args.fp16:
        config.set_flag(trt.BuilderFlag.FP16)
    print('Building TensorRT engine...', flush=True)
    engine = builder.build_serialized_network(network, config)
    if engine is None:
        raise RuntimeError('TensorRT build failed')
    output.write_bytes(bytes(engine))
    converted = TensorRTPolicy(output)
    with torch.inference_mode():
        reference = policy(rgbd, obs)
        actual = converted(rgbd, obs)
        torch.cuda.synchronize()
        errors = {name: {'mae': (a - b).abs().mean().item(), 'max_abs': (a - b).abs().max().item()}
                  for name, a, b in zip(TensorRTPolicy.output_names, reference, actual)}
        if not all(torch.isfinite(v).all().item() for v in actual):
            raise RuntimeError('Non-finite TensorRT output')
        for a, b in zip(reference, actual):
            torch.testing.assert_close(a, b, atol=0.05, rtol=0.03)

        def benchmark(model):
            for _ in range(20):
                model(rgbd, obs)
            torch.cuda.synchronize()
            start = time.perf_counter()
            for _ in range(args.iterations):
                model(rgbd, obs)
            torch.cuda.synchronize()
            return (time.perf_counter() - start) * 1000 / args.iterations

        report = {'trial': args.trial, 'gpu': torch.cuda.get_device_name(0),
                  'torch': torch.__version__, 'tensorrt': trt.__version__, 'fp16': bool(args.fp16),
                  'torch_ms': benchmark(policy), 'tensorrt_ms': benchmark(converted),
                  'errors': errors, 'engine': relative_path(output)}
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
