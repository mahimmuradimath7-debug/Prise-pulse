"""Reinforcement Learning Pricing Agents (Deep Q-Learning DQN & Tabular Q-Learning).

Implements the SOTA dynamic pricing requirement from the project brief:
"Implement Reinforcement Learning (Deep Q-Learning or PPO) for dynamic pricing that learns optimal policies through trial and error."

State  = Continuous feature vector [stock_ratio, days_left_ratio, comp_ratio_offset, is_weekend]
Action = Price multiplier vs the reference price [0.85, 0.92, 1.0, 1.08, 1.15, 1.25]
Reward = 0.5 * revenue + 0.5 * profit per day, learned in the ground-truth market simulator.
"""
from __future__ import annotations

from collections import deque
from datetime import date, timedelta

import numpy as np

from .data import true_demand, seasonal_mult

ACTIONS = [0.85, 0.92, 1.0, 1.08, 1.15, 1.25]
EP_LEN = 14


# ---------------------------------------------------------------------- State helpers
def _bucket_stock(stock, cap):
    r = stock / max(cap, 1)
    return 0 if r < 0.15 else 1 if r < 0.4 else 2 if r < 0.7 else 3


def _bucket_comp(c):
    return 0 if c < 0.95 else 1 if c < 1.05 else 2


def _continuous_state(stock, cap, t, comp_r, day):
    return np.array([
        stock / max(cap, 1.0),
        (EP_LEN - t) / EP_LEN,
        float(np.clip(comp_r - 1.0, -0.25, 0.25)),
        1.0 if day.weekday() >= 5 else 0.0,
    ], dtype=np.float64)


def _env_step(sku, price, comp_ratio, stock, day, rng):
    lam = true_demand(sku.base_demand, sku.ref_price, sku.true_elasticity, price, sku.ref_price * comp_ratio,
                      sku.ref_comp, seasonal_mult(sku.category, day))
    demand = rng.poisson(lam)
    sold = min(demand, stock)
    return sold, 0.5 * sold * price + 0.5 * sold * (price - sku.cost)


# ---------------------------------------------------------------------- Deep Q-Network (DQN)
class DeepQNetwork:
    """A vectorized 2-layer Neural Network with ReLU activations, Experience Replay, and Target Network."""

    def __init__(self, in_dim=4, hidden_dim=24, out_dim=len(ACTIONS), lr=0.002, seed=42):
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0, np.sqrt(2.0 / in_dim), (in_dim, hidden_dim)).astype(np.float64) * 0.5
        self.b1 = np.zeros(hidden_dim, dtype=np.float64)
        self.W2 = rng.normal(0, np.sqrt(2.0 / hidden_dim), (hidden_dim, out_dim)).astype(np.float64) * 0.5
        self.b2 = np.zeros(out_dim, dtype=np.float64)
        # Target network weights
        self.t_W1, self.t_b1 = self.W1.copy(), self.b1.copy()
        self.t_W2, self.t_b2 = self.W2.copy(), self.b2.copy()
        self.lr = lr

    def forward(self, x, target=False):
        with np.errstate(all="ignore"):
            w1, b1 = (self.t_W1, self.t_b1) if target else (self.W1, self.b1)
            w2, b2 = (self.t_W2, self.t_b2) if target else (self.W2, self.b2)
            x_clean = np.nan_to_num(x, nan=0.0)
            h = np.maximum(0, x_clean @ w1 + b1)
            q = h @ w2 + b2
            return np.nan_to_num(np.clip(q, -10.0, 10.0), nan=0.0), h

    def sync_target(self, tau=0.1):
        self.t_W1 = (1 - tau) * self.t_W1 + tau * self.W1
        self.t_b1 = (1 - tau) * self.t_b1 + tau * self.b1
        self.t_W2 = (1 - tau) * self.t_W2 + tau * self.W2
        self.t_b2 = (1 - tau) * self.t_b2 + tau * self.b2

    def train_batch(self, states, actions, targets):
        with np.errstate(all="ignore"):
            # Backprop through 2-layer MLP with numerical stability
            s_clean = np.nan_to_num(states, nan=0.0)
            h = np.maximum(0, s_clean @ self.W1 + self.b1)
            q = np.nan_to_num(np.clip(h @ self.W2 + self.b2, -10.0, 10.0), nan=0.0)
            batch_size = len(states)
            diff = np.zeros_like(q)
            for i, (a, targ) in enumerate(zip(actions, targets)):
                diff[i, a] = np.clip(q[i, a] - targ, -0.5, 0.5)
            # Output layer gradients
            grad_W2 = np.nan_to_num((h.T @ diff) / batch_size, nan=0.0)
            grad_b2 = np.nan_to_num(np.mean(diff, axis=0), nan=0.0)
            # Hidden layer gradients
            dh = (diff @ self.W2.T) * (h > 0)
            grad_W1 = np.nan_to_num((s_clean.T @ dh) / batch_size, nan=0.0)
            grad_b1 = np.mean(dh, axis=0)
            # Gradient update with clipping
            self.W2 = np.clip(self.W2 - self.lr * np.clip(grad_W2, -0.2, 0.2), -3.0, 3.0)
            self.b2 = np.clip(self.b2 - self.lr * np.clip(grad_b2, -0.2, 0.2), -3.0, 3.0)
            self.W1 = np.clip(self.W1 - self.lr * np.clip(grad_W1, -0.2, 0.2), -3.0, 3.0)
            self.b1 = np.clip(self.b1 - self.lr * np.clip(grad_b1, -0.2, 0.2), -3.0, 3.0)

    def to_dict(self):
        return dict(
            W1=self.W1.tolist(), b1=self.b1.tolist(),
            W2=self.W2.tolist(), b2=self.b2.tolist(),
        )

    @classmethod
    def from_dict(cls, d):
        net = cls()
        net.W1 = np.array(d["W1"], dtype=np.float64)
        net.b1 = np.array(d["b1"], dtype=np.float64)
        net.W2 = np.array(d["W2"], dtype=np.float64)
        net.b2 = np.array(d["b2"], dtype=np.float64)
        return net


# ---------------------------------------------------------------------- Episode runners
def _episode_tabular(sku, Q, eps, alpha, gamma, rng, learn=True, policy="q"):
    cap = sku.capacity
    stock = cap * rng.uniform(0.3, 1.0)
    comp_r = rng.uniform(0.9, 1.1)
    start = date.today() + timedelta(days=int(rng.integers(0, 300)))
    total = 0.0
    scale = max(sku.base_demand * sku.ref_price, 1.0)
    for t in range(EP_LEN):
        day = start + timedelta(days=t)
        s = (_bucket_stock(stock, cap), min(2, (EP_LEN - t) // 5), _bucket_comp(comp_r))
        if policy == "static":
            a = 2
        elif learn and rng.random() < eps:
            a = int(rng.integers(len(ACTIONS)))
        else:
            a = int(np.argmax(Q[s]))
        sold, reward = _env_step(sku, sku.ref_price * ACTIONS[a], comp_r, stock, day, rng)
        stock -= sold
        if t % 7 == 6:
            stock = cap
        comp_r = float(np.clip(comp_r + rng.normal(0, 0.025), 0.82, 1.2))
        t2 = t + 1
        s2 = (_bucket_stock(stock, cap), min(2, (EP_LEN - t2) // 5), _bucket_comp(comp_r))
        if learn:
            Q[s][a] += alpha * (reward / scale + gamma * (0 if t2 >= EP_LEN else Q[s2].max()) - Q[s][a])
        total += reward
    return total


def _episode_dqn(sku, dqn: DeepQNetwork, replay: deque, eps, gamma, rng, learn=True, policy="dqn"):
    cap = sku.capacity
    stock = cap * rng.uniform(0.3, 1.0)
    comp_r = rng.uniform(0.9, 1.1)
    start = date.today() + timedelta(days=int(rng.integers(0, 300)))
    total = 0.0
    scale = max(sku.base_demand * sku.ref_price, 1.0)
    for t in range(EP_LEN):
        day = start + timedelta(days=t)
        s = _continuous_state(stock, cap, t, comp_r, day)
        if policy == "static":
            a = 2
        elif learn and rng.random() < eps:
            a = int(rng.integers(len(ACTIONS)))
        else:
            q, _ = dqn.forward(s)
            a = int(np.argmax(q))
        sold, reward = _env_step(sku, sku.ref_price * ACTIONS[a], comp_r, stock, day, rng)
        stock -= sold
        if t % 7 == 6:
            stock = cap
        comp_r = float(np.clip(comp_r + rng.normal(0, 0.025), 0.82, 1.2))
        t2 = t + 1
        done = (t2 >= EP_LEN)
        s2 = _continuous_state(stock, cap, t2, comp_r, start + timedelta(days=t2))
        norm_r = float(reward / scale)
        if learn:
            replay.append((s, a, norm_r, s2, done))
            if len(replay) >= 48:
                # Sample minibatch
                idx = rng.choice(len(replay), size=32, replace=False)
                b_s = np.array([replay[i][0] for i in idx])
                b_a = [replay[i][1] for i in idx]
                b_r = np.array([replay[i][2] for i in idx])
                b_s2 = np.array([replay[i][3] for i in idx])
                b_done = np.array([replay[i][4] for i in idx])
                q_next, _ = dqn.forward(b_s2, target=True)
                targets = np.clip(b_r + (1.0 - b_done) * gamma * np.max(q_next, axis=1), -5.0, 5.0)
                dqn.train_batch(b_s, b_a, targets)
                dqn.sync_target(tau=0.01)
        total += reward
    return total


# ---------------------------------------------------------------------- Training entry point
def train(sku, episodes: int = 800, seed: int = 5, algo: str = "dqn") -> dict:
    rng = np.random.default_rng(seed)
    curve = []
    window = []
    labels_s = ["<15% stock", "15-40%", "40-70%", ">70%"]
    labels_c = ["competitor cheaper", "at par", "competitor pricier"]

    if algo == "tabular":
        Q = np.zeros((4, 3, 3, len(ACTIONS)))
        for ep in range(episodes):
            eps = max(0.05, 1.0 - ep / (episodes * 0.7))
            window.append(_episode_tabular(sku, Q, eps, 0.15, 0.95, rng))
            if (ep + 1) % max(episodes // 40, 1) == 0:
                curve.append(dict(episode=ep + 1, reward=round(float(np.mean(window)))))
                window = []
        r_rl = np.mean([_episode_tabular(sku, Q, 0, 0, 0, np.random.default_rng(1000 + i), learn=False) for i in range(250)])
        r_s = np.mean([_episode_tabular(sku, Q, 0, 0, 0, np.random.default_rng(1000 + i), learn=False, policy="static") for i in range(250)])
        policy = []
        for si in range(4):
            for ci in range(3):
                q = Q[si, 1, ci]
                policy.append(dict(stock=labels_s[si], competitor=labels_c[ci],
                                   multiplier=ACTIONS[int(np.argmax(q))] if q.any() else 1.0))
        return dict(sku=sku.sku, algo="tabular", episodes=episodes, curve=curve, policy=policy,
                    eval=dict(rl_reward=round(float(r_rl)), static_reward=round(float(r_s)),
                              uplift_pct=round(float((r_rl / r_s - 1) * 100), 2)),
                    actions=ACTIONS, Q=Q.tolist())

    # Default: Deep Q-Learning (DQN)
    dqn = DeepQNetwork(seed=seed)
    replay = deque(maxlen=2000)
    for ep in range(episodes):
        eps = max(0.05, 1.0 - ep / (episodes * 0.7))
        window.append(_episode_dqn(sku, dqn, replay, eps, 0.95, rng))
        if (ep + 1) % max(episodes // 40, 1) == 0:
            curve.append(dict(episode=ep + 1, reward=round(float(np.mean(window)))))
            window = []

    r_rl = np.mean([_episode_dqn(sku, dqn, replay, 0, 0.95, np.random.default_rng(1000 + i), learn=False) for i in range(250)])
    r_s = np.mean([_episode_dqn(sku, dqn, replay, 0, 0.95, np.random.default_rng(1000 + i), learn=False, policy="static") for i in range(250)])

    # Derive policy grid for visualization
    policy = []
    stock_levels = [0.10 * sku.capacity, 0.28 * sku.capacity, 0.55 * sku.capacity, 0.85 * sku.capacity]
    comp_offsets = [0.90, 1.00, 1.12]
    eval_day = date.today()
    for si, st_val in enumerate(stock_levels):
        for ci, comp_val in enumerate(comp_offsets):
            s_vec = _continuous_state(st_val, sku.capacity, 7, comp_val, eval_day)
            q_vals, _ = dqn.forward(s_vec)
            a_star = int(np.argmax(q_vals))
            policy.append(dict(stock=labels_s[si], competitor=labels_c[ci], multiplier=ACTIONS[a_star]))

    return dict(sku=sku.sku, algo="dqn", episodes=episodes, curve=curve, policy=policy,
                eval=dict(rl_reward=round(float(r_rl)), static_reward=round(float(r_s)),
                          uplift_pct=round(float((r_rl / r_s - 1) * 100), 2)),
                actions=ACTIONS, dqn_weights=dqn.to_dict())


def recommend(result: dict, sku, stock: float, comp_price: float) -> dict:
    if result.get("algo") == "tabular" and "Q" in result:
        Q = np.array(result["Q"])
        s = (_bucket_stock(stock, sku.capacity), 1, _bucket_comp(comp_price / sku.ref_price))
        a = int(np.argmax(Q[s])) if Q[s].any() else 2
        return dict(multiplier=ACTIONS[a], price=float(round(sku.ref_price * ACTIONS[a])), algo="tabular")

    # DQN recommendation
    if "dqn_weights" in result:
        dqn = DeepQNetwork.from_dict(result["dqn_weights"])
        s_vec = _continuous_state(stock, sku.capacity, 7, comp_price / max(sku.ref_price, 1e-6), date.today())
        q_vals, _ = dqn.forward(s_vec)
        a = int(np.argmax(q_vals))
        return dict(multiplier=ACTIONS[a], price=float(round(sku.ref_price * ACTIONS[a])), algo="dqn")

    return dict(multiplier=1.0, price=float(round(sku.ref_price)), algo="default")
