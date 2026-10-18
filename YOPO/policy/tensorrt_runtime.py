"""TensorRT 10 named-I/O execution with PyTorch-owned CUDA buffers."""
from pathlib import Path
import numpy as np
import torch


class TensorRTPolicy:
    output_names = ('endstate', 'target', 'traj_cost', 'obj_score', 'traj_time')

    def __init__(self, path):
        import tensorrt as trt
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(Path(path).read_bytes())
        if self.engine is None:
            raise RuntimeError(f'Cannot load TensorRT engine {path}; rebuild on this GPU')
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError('Cannot create TensorRT execution context')
        self.outputs = []
        for name in self.output_names:
            shape = tuple(self.engine.get_tensor_shape(name))
            dtype = torch.from_numpy(np.empty((), dtype=trt.nptype(self.engine.get_tensor_dtype(name)))).dtype
            self.outputs.append(torch.empty(shape, dtype=dtype, device='cuda'))

    def __call__(self, rgbd, obs):
        inputs = (rgbd.contiguous(), obs.contiguous())
        for name, value in zip(('rgbd', 'obs'), inputs):
            if value.device.type != 'cuda' or tuple(value.shape) != tuple(self.engine.get_tensor_shape(name)):
                raise ValueError(f'Unexpected TensorRT input {name}: {value.device}, {value.shape}')
            self.context.set_tensor_address(name, value.data_ptr())
        for name, value in zip(self.output_names, self.outputs):
            self.context.set_tensor_address(name, value.data_ptr())
        stream = torch.cuda.current_stream()
        if not self.context.execute_async_v3(stream.cuda_stream):
            raise RuntimeError('TensorRT execution failed')
        for value in inputs:
            value.record_stream(stream)
        return tuple(self.outputs)
