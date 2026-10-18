import os
import torch
import random
import argparse
import numpy as np


def configure_random_seed(seed):
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pretrained", type=int, default=0, help="use pre-trained model?")
    parser.add_argument("--trial", type=int, default=1, help="trial of pre-trained model")
    parser.add_argument("--epoch", type=int, default=50, help="epoch of pre-trained model")
    parser.add_argument("--epochs", type=int, default=50, help="number of training epochs")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--dataset", help="root containing scene-N directories")
    parser.add_argument("--no-imagenet", action="store_true")
    return parser


if __name__ == "__main__":
    args = parser().parse_args()
    from config.config import cfg
    from config.paths import project_path
    if args.dataset:
        cfg['dataset_path'] = str(project_path(args.dataset))
    if args.no_imagenet:
        cfg['pretrained_backbone'] = False
    from policy.yopo_trainer import YopoTrainer
    from policy.scene_index import scene_dirs_for
    if not scene_dirs_for('train'):
        raise SystemExit('No training scenes. Run ./run_demo.sh collect first, or pass --dataset ROOT.')
    configure_random_seed(0)    # set random seed

    # save the configuration and other files
    log_dir = os.path.dirname(os.path.abspath(__file__)) + "/saved"
    os.makedirs(log_dir, exist_ok=True)
    checkpoint_path = log_dir + "/YOPO_{}/epoch{}.pth".format(args.trial, args.epoch) if args.pretrained else ""

    trainer = YopoTrainer(
        learning_rate=1e-3,
        batch_size=args.batch_size,
        tensorboard_path=log_dir,
        checkpoint_path=checkpoint_path,
        save_on_exit=True,
    )

    trainer.train(epoch=args.epochs)
    trainer.save_model()
    trainer.tensorboard_log.close()
    del trainer

    print("Run YOPO Finish!")
