"""
The two predictors (paper Table 2): 1 recurrent layer of 64 units, dropout
0.3, then a linear layer to the 5 future steps.

Table 2 also lists encoder, decoder and attention rows; a plain BiGRU has
none, so they are left out. Section 7.1 says 32 units, Table 2 says 64: 64 here.
"""
import torch
from torch import nn

from .data import FEATURES, HORIZON


class BiGRU(nn.Module):
    """Bidirectional GRU, merge mode "sum": forward and backward final states are added."""

    def __init__(self, units=64, dropout=0.3):
        super().__init__()
        self.rnn = nn.GRU(len(FEATURES), units, batch_first=True, bidirectional=True)
        self.dropout = nn.Dropout(dropout)
        self.out = nn.Linear(units, HORIZON)

    def forward(self, x):
        _, h = self.rnn(x)                  # h: (2, batch, units), forward and backward
        return self.out(self.dropout(h[0] + h[1]))


class LSTM(nn.Module):
    """One-directional LSTM, last hidden state."""

    def __init__(self, units=64, dropout=0.3):
        super().__init__()
        self.rnn = nn.LSTM(len(FEATURES), units, batch_first=True)
        self.dropout = nn.Dropout(dropout)
        self.out = nn.Linear(units, HORIZON)

    def forward(self, x):
        _, (h, _) = self.rnn(x)             # h: (1, batch, units)
        return self.out(self.dropout(h[-1]))


ARCHITECTURES = {"BiGRU": BiGRU, "LSTM": LSTM}


def parameter_count(model):
    return sum(p.numel() for p in model.parameters())


def model_bytes(model):
    """Bytes of all weights as float32: what a client uploads or downloads per round."""
    return sum(p.numel() * p.element_size() for p in model.parameters())


def get_weights(model):
    """The weights as a list of numpy arrays (the format Flower sends)."""
    return [v.detach().cpu().numpy().copy() for v in model.state_dict().values()]


def set_weights(model, weights):
    keys = model.state_dict().keys()
    model.load_state_dict({k: torch.tensor(w) for k, w in zip(keys, weights)})
