"""Training and validation passes shared by the clients and the central models."""
import time

import numpy as np
import torch
from torch import nn

LOSS = nn.L1Loss()   # MAE (paper Table 2)


def train_epoch(model, data, optimizer, batch_size, generator=None):
    """One pass over the training windows of `data` (a NodeData or PooledData). Returns the mean loss."""
    model.train()
    total, count = 0.0, 0
    for x, y in data.batches("train", batch_size, shuffle=True, generator=generator):
        optimizer.zero_grad()
        loss = LOSS(model(x), y)
        loss.backward()
        optimizer.step()
        total += loss.item() * len(y)
        count += len(y)
    return total / count


@torch.no_grad()
def mean_loss(model, data, split, batch_size=4096):
    """MAE on scaled values over all windows of a split."""
    model.eval()
    total, count = 0.0, 0
    for x, y in data.batches(split, batch_size, shuffle=False):
        total += LOSS(model(x), y).item() * len(y)
        count += len(y)
    return total / count


@torch.no_grad()
def predict(model, node, split="test", batch_size=4096):
    """Real-unit predictions and true values, both (windows, HORIZON), for one node."""
    model.eval()
    predicted, real = [], []
    for x, y in node.batches(split, batch_size, shuffle=False):
        predicted.append(model(x).cpu())
        real.append(y.cpu())
    unscale = node.scaler.unscale_requests
    # Real requests are whole numbers. Rounding undoes the float32 scaling error,
    # so a minute with 0 requests is exactly 0 again (MAPE has to skip those).
    return unscale(torch.cat(predicted).numpy()), np.round(unscale(torch.cat(real).numpy()))


def train_central(model, pooled, epochs, patience, batch_size, lr, seed, log=print):
    """
    A central model on all nodes' training windows pooled: up to `epochs`
    epochs, stopping when the pooled validation loss has not improved for
    `patience` epochs. Returns (model with the best weights, history, cost).
    """
    generator = torch.Generator(device=pooled.nodes[0].series.device).manual_seed(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    best, best_loss, since_best, history = None, float("inf"), 0, []
    start = time.time()
    for epoch in range(1, epochs + 1):
        train = train_epoch(model, pooled, optimizer, batch_size, generator)
        val = mean_loss(model, pooled, "val")
        history.append({"epoch": epoch, "train_loss": train, "val_loss": val,
                        "seconds": round(time.time() - start, 1)})
        log(f"    epoch {epoch:3d}: train MAE {train:.5f}, val MAE {val:.5f} ({time.time() - start:.0f} s)")
        if val < best_loss:
            best = {k: v.detach().clone() for k, v in model.state_dict().items()}
            best_loss, since_best = val, 0
        else:
            since_best += 1
            if since_best >= patience:
                break
    model.load_state_dict(best)
    cost = {"epochs": len(history), "best_epoch": min(history, key=lambda h: h["val_loss"])["epoch"],
            "train_seconds": round(time.time() - start, 1), "best_val_loss": best_loss}
    return model, history, cost
