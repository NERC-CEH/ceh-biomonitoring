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


# Mila's 2024 moth / non-moth model looks at a 128 x 128 crop with ImageNet colour scaling.
RESNET128_TRANSFORM = transforms.Compose([
    transforms.ToTensor(),
    transforms.Resize((128, 128), antialias=True),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def load_binary(weights, labels, device, kind="efficientnetv2-b3-300"):
    """(model, labels, transform). The transform is None when the shared 300 px crop is used."""
    names = {v: k for k, v in json.loads(open(labels).read()).items()} if labels else {0: "moth", 1: "nonmoth"}
    if kind == "resnet50-128":
        m = torchvision.models.resnet50(weights=None)
        m.fc = nn.Linear(m.fc.in_features, len(names))
        transform = RESNET128_TRANSFORM
    else:
        import timm
        m = timm.create_model("tf_efficientnetv2_b3", num_classes=2, pretrained=False)
        transform = None
    m.load_state_dict(_state(weights, device))
    return m.to(device).eval(), [names[i] for i in range(len(names))], transform


def order_transform(crop):
    """The order model's own input (Bjerge et al., MCC24-trap): 128 x 128, values 0-1, no normalising."""
    import cv2
    arr = cv2.resize(np.asarray(crop), (128, 128))          # bilinear, as in orderClassifier.py
    return transforms.ToTensor()(arr)


def load_order(weights, thresholds_csv, device):
    """(model, labels, thresholds table with ClassName, Mean, Std, Threshold)."""
    table = pd.read_csv(thresholds_csv)
    labels = table["ClassName"].tolist()
    m = OrderResNet50(num_classes=len(labels))
    m.load_state_dict(_state(weights, device))
    return m.to(device).eval(), labels, table


@torch.no_grad()
def order_scores(model, batch, table) -> list[dict]:
    """Per crop: order_name, order_confidence (softmax), order_score (Bjerge's calibrated confidence:
    the normal CDF of the winning output given that group's mean and sd) and order_sure (output above
    the group's threshold), as in MCC24-trap."""
    from math import erf, sqrt
    out = model(batch).cpu().numpy()
    probs = torch.nn.functional.softmax(torch.from_numpy(out), dim=1).numpy()
    rows = []
    for o, pr in zip(out, probs):
        k = int(o.argmax())
        mu, sd, thr = (float(table.loc[k, c]) for c in ("Mean", "Std", "Threshold"))
        rows.append({"order_name": table.loc[k, "ClassName"], "order_confidence": float(pr[k]),
                     "order_score": 0.5 * (1 + erf((float(o[k]) - mu) / (sd * sqrt(2)))),
                     "order_sure": bool(o[k] >= thr)})
    return rows


def load_species(weights, labels_json, device):
    cmap = json.loads(open(labels_json, encoding="utf-8").read())      # {label: index}
    m = SpeciesResNet50(num_classes=len(cmap))
    m.load_state_dict(_state(weights, device))
    if m.classifier.out_features != len(cmap):
        raise SystemExit(f"Species model has {m.classifier.out_features} outputs but its list has {len(cmap)} names")
    names = {i: label for label, i in cmap.items()}
    return m.to(device).eval(), [names[i] for i in range(len(names))]


def load_flatbug(weights, device, score_threshold=None, min_size=None, precision="float32"):
    """flat-bug, optionally tuned: score_threshold (flat-bug's own cut-off, default 0.2), min_size
    (smallest insect it reports, as the square root of its box area in pixels; flat-bug's default is 32)
    and precision. float32 is the default: half precision (float16) is faster on a GPU but was seen to
    lose faint insects in UKCEH tests (2026). float16 is only allowed on a GPU."""
    from flat_bug.predictor import Predictor
    dtype = "float16" if (precision == "float16" and str(device).startswith("cuda")) else "float32"
    p = Predictor(model=str(weights), device=device, dtype=dtype)
    hyper = {}
    if score_threshold is not None:
        hyper["SCORE_THRESHOLD"] = float(score_threshold)
    if min_size is not None:
        hyper["MIN_MAX_OBJ_SIZE"] = (int(min_size), 10 ** 8)
    if hyper:
        p.set_hyperparameters(**hyper)
    return p


def flatbug_default_model() -> str:
    """The model the installed flat-bug package uses by default (its newest)."""
    import inspect
    from flat_bug.predictor import Predictor
    return str(inspect.signature(Predictor.__init__).parameters["model"].default)


def enhance(image_path, out_path):
    """Boost local contrast (CLAHE on lightness) so pale insects on a white sheet stand out.
    Only the detector sees this copy; crops are always cut from the original photo."""
    import cv2
    img = cv2.imread(str(image_path))
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    cv2.imwrite(str(out_path), cv2.cvtColor(lab, cv2.COLOR_LAB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
    return out_path


def detect_flatbug(predictor, image_path, overlay_path=None):
    """Boxes as (x_min, y_min, x_max, y_max, score, label, outline), in detector order.
    outline is a list of (x, y) points. With overlay_path, flat-bug's own overlay is saved there."""
    result = predictor(str(image_path))
    out = result.json_data
    boxes, scores = out.get("boxes", []), out.get("confs", out.get("scores", []))
    labels = out.get("classes", out.get("labels", [0] * len(boxes)))
    contours = out.get("contours", [None] * len(boxes))
    if overlay_path is not None:
        try:
            result.plot(outpath=str(overlay_path))
        except Exception as e:  # noqa: BLE001 - an overlay must never stop the run
            print(f"[warning] overlay not saved for {image_path}: {e}")
    rows = []
    for b, s_, lab, c in zip(boxes, scores, labels, contours):
        poly = None
        if c is not None:
            a = np.asarray(c.tolist() if hasattr(c, "tolist") else c, dtype=float)
            if a.ndim == 2 and a.shape[0] == 2 and a.shape[1] != 2:
                a = a.T                                  # flat-bug lists all x values, then all y values
            poly = a.reshape(-1, 2).tolist()
        rows.append((float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(s_), int(lab), poly))
    return rows


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
