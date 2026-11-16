"""Model architectures and loading for the images pipeline.

Ported from amber-inferences (AMI-system, MIT licence), so the same weights give the same results:
https://github.com/AMI-system/amber-inferences . The order classifier architecture follows
Bjerge et al. (https://github.com/kimbjerge/MCC24-trap).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torchvision
from torchvision import transforms

# All three classifiers take the same 300 x 300 crop, scaled to [-1, 1] (as amber-inferences does).
CROP_TRANSFORM = transforms.Compose([
    transforms.Resize((300, 300)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
])


class SpeciesResNet50(nn.Module):
    def __init__(self, num_classes: int):
        super().__init__()
        backbone = torchvision.models.resnet50(weights=None)
        out_dim = backbone.fc.in_features
        self.backbone = nn.Sequential(*list(backbone.children())[:-2])
        self.avgpool = nn.AdaptiveAvgPool2d(output_size=(1, 1))
        self.classifier = nn.Linear(out_dim, num_classes, bias=False)

    def forward(self, x):
        x = self.avgpool(self.backbone(x))
        return self.classifier(x.view(x.size(0), -1))


class OrderResNet50(nn.Module):
    def __init__(self, num_classes: int = 16):
        super().__init__()
        self.model_ft = torchvision.models.resnet50(weights=None)
        self.model_ft.fc = nn.Identity()
        self.drop = nn.Dropout(p=0.5)
        self.linear_lvl1 = nn.Linear(512 * 4, 512)
        self.relu_lv1 = nn.ReLU(inplace=False)
        self.softmax_reg1 = nn.Linear(512, num_classes)

    def forward(self, x):
        x = self.drop(self.model_ft(x))
        return self.softmax_reg1(self.relu_lv1(self.linear_lvl1(x)))


def _state(path, device):
    ckpt = torch.load(str(path), map_location=device, weights_only=True)
    return ckpt.get("model_state_dict") or ckpt


def load_binary(weights, labels, device):
    import timm
    m = timm.create_model("tf_efficientnetv2_b3", num_classes=2, pretrained=False)
    m.load_state_dict(_state(weights, device))
    names = {v: k for k, v in json.loads(open(labels).read()).items()} if labels else {0: "moth", 1: "nonmoth"}
    return m.to(device).eval(), [names[i] for i in range(len(names))]


def load_order(weights, thresholds_csv, device):
    labels = pd.read_csv(thresholds_csv)["ClassName"].tolist()
    m = OrderResNet50(num_classes=len(labels))
    m.load_state_dict(_state(weights, device))
    return m.to(device).eval(), labels


def load_species(weights, labels_json, device):
    cmap = json.loads(open(labels_json, encoding="utf-8").read())      # {label: index}
    m = SpeciesResNet50(num_classes=len(cmap))
    m.load_state_dict(_state(weights, device))
    if m.classifier.out_features != len(cmap):
        raise SystemExit(f"Species model has {m.classifier.out_features} outputs but its list has {len(cmap)} names")
    names = {i: label for label, i in cmap.items()}
    return m.to(device).eval(), [names[i] for i in range(len(names))]


def load_flatbug(weights, device):
    from flat_bug.predictor import Predictor
    dtype = "float16" if str(device).startswith("cuda") else "float32"
    return Predictor(model=str(weights) if weights else "flat_bug_M.pt", device=device, dtype=dtype)


def detect_flatbug(predictor, image_path) -> list[tuple[float, float, float, float, float, int]]:
    """Boxes as (x_min, y_min, x_max, y_max, score, label), in detector order."""
    out = predictor(str(image_path)).json_data
    boxes, scores = out.get("boxes", []), out.get("confs", out.get("scores", []))
    labels = out.get("classes", out.get("labels", [0] * len(boxes)))
    return [(float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(s), int(lab))
            for b, s, lab in zip(boxes, scores, labels)]


@torch.no_grad()
def classify(model, batch) -> np.ndarray:
    """Softmax probabilities, one row per crop."""
    return torch.nn.functional.softmax(model(batch), dim=1).cpu().numpy()


@torch.no_grad()
def species_scores(model, batch) -> tuple[np.ndarray, np.ndarray]:
    """(softmax probabilities, L2-normalised raw outputs). The normalised outputs are what tracking
    compares between images (as amber-inferences does)."""
    out = model(batch)
    probs = torch.nn.functional.softmax(out, dim=1).cpu().numpy()
    norm = out.norm(p=2, dim=1, keepdim=True)
    emb = torch.where(norm > 0, out / norm, out).cpu().numpy()
    return probs, emb
