"""
FedAvg (paper Algorithm 2), in one process for now.

Client and Server talk only through weights (a list of numpy arrays) and
sample counts, the same as a Flower NumPyClient (fit / evaluate) and a
FedAvg strategy. Moving to Flower and Docker later means wrapping Client in
a NumPyClient and replacing run_fedavg with Flower's server loop.
"""
import time

import numpy as np
import torch

from .models import get_weights, model_bytes, set_weights
from .training import mean_loss, train_epoch


class Client:
    """One edge node: its own data and its own copy of the model."""

    def __init__(self, node, make_model, batch_size, lr, seed):
        self.node = node
        self.model = make_model()
        self.batch_size, self.lr = batch_size, lr
        self.generator = torch.Generator(device=node.series.device).manual_seed(seed)

    def fit(self, weights, epochs):
        """ClientUpdate: start from the global weights, train `epochs` local epochs.
        Returns (new weights, number of training windows, training loss)."""
        set_weights(self.model, weights)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.lr)   # fresh every round
        for _ in range(epochs):
            loss = train_epoch(self.model, self.node, optimizer, self.batch_size, self.generator)
        return get_weights(self.model), self.node.count("train"), loss

    def evaluate(self, weights):
        """Validation MAE (scaled) of the given weights, and number of validation windows."""
        set_weights(self.model, weights)
        return mean_loss(self.model, self.node, "val"), self.node.count("val")


class Server:
    """Holds the global weights and averages the clients' updates."""

    def __init__(self, initial_weights, fraction, seed):
        self.weights = initial_weights
        self.fraction = fraction
        self.rng = np.random.default_rng(seed)

    def per_round(self, clients):
        return max(1, round(self.fraction * len(clients)))

    def select(self, clients):
        """A random subset of the clients (all of them with fraction 1.0)."""
        chosen = self.rng.choice(len(clients), self.per_round(clients), replace=False)
        return [clients[i] for i in sorted(chosen)]

    @staticmethod
    def average(results):
        """Weighted average of (weights, n) pairs, by n."""
        total = sum(n for _, n in results)
        return [sum(w[i] * (n / total) for w, n in results) for i in range(len(results[0][0]))]


def run_fedavg(clients, make_model, rounds, local_epochs, fraction, patience, seed, log=print):
    """
    Rounds of FedAvg until the validation loss (all clients, weighted by their
    number of validation windows) has not improved for `patience` rounds, or
    `rounds` is reached. Returns (best global model, history, cost).
    """
    model = make_model()
    server = Server(get_weights(model), fraction, seed)
    size = model_bytes(model)
    best, best_loss, since_best, history, sent = server.weights, float("inf"), 0, [], 0
    start = time.time()
    for r in range(1, rounds + 1):
        chosen = server.select(clients)
        updates = [client.fit(server.weights, local_epochs) for client in chosen]
        server.weights = Server.average([(w, n) for w, n, _ in updates])
        sent += 2 * size * len(chosen)                    # download + upload, every chosen client
        # Validation loss of the new global model on every client, weighted by windows
        checks = [client.evaluate(server.weights) for client in clients]
        val = sum(loss * n for loss, n in checks) / sum(n for _, n in checks)
        train = sum(loss * n for _, n, loss in updates) / sum(n for _, n, _ in updates)
        history.append({"round": r, "train_loss": float(train), "val_loss": float(val),
                        "seconds": round(time.time() - start, 1)})
        log(f"    round {r:3d}: train MAE {train:.5f}, val MAE {val:.5f} "
            f"({time.time() - start:.0f} s)")
        if val < best_loss:
            best, best_loss, since_best = server.weights, val, 0
        else:
            since_best += 1
            if since_best >= patience:
                break
    set_weights(model, best)
    cost = {"rounds": len(history), "best_round": int(np.argmin([h["val_loss"] for h in history]) + 1),
            "clients_per_round": server.per_round(clients),
            "bytes_per_round": 2 * size * server.per_round(clients), "bytes_total": sent,
            "train_seconds": round(time.time() - start, 1), "best_val_loss": float(best_loss)}
    return model, history, cost
