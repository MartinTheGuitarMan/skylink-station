"""Forecasters. One interface: after the true value for second s is known (and was already
scored), `step` returns forecasts {horizon: yhat for second s+horizon}. Test-then-train is
enforced by the engine: scoring for target s always happens before `step(s, ...)`.

Direct models learn one regressor per horizon on increments (y[s+h] - y[s]) from features at s,
so an untrained model equals persistence."""
from __future__ import annotations

import math
from collections import deque

import numpy as np
from river import compose, drift, forest, linear_model, optim, preprocessing, time_series, tree

DAY = 86400.0


class History:
    """Ring of the last `size` one-second aggregates, addressed by absolute second."""

    def __init__(self, size: int):
        self.size = size
        self.vals = np.full(size, np.nan)
        self.stamps = np.full(size, -1, dtype=np.int64)

    def put(self, s: int, y: float) -> None:
        self.vals[s % self.size] = y
        self.stamps[s % self.size] = s

    def get(self, s: int) -> float | None:
        if s < 0:
            return None
        i = s % self.size
        return float(self.vals[i]) if self.stamps[i] == s else None


class FeatHist:
    """Feature dicts of the last few seconds, to pair x[s-h] with the outcome y[s]."""

    def __init__(self, size: int):
        self.size, self.items = size, [None] * size

    def put(self, s: int, x: dict) -> None:
        self.items[s % self.size] = (s, x)

    def get(self, s: int) -> dict | None:
        it = self.items[s % self.size] if s >= 0 else None
        return it[1] if it and it[0] == s else None


class Features:
    """Cheap online features shared by all direct models of one stream."""

    def __init__(self):
        self.ema: dict[int, float] = {}
        self.vol = 0.0

    def update(self, s: int, y: float, hist: History) -> dict:
        x: dict[str, float] = {}
        for k in (1, 5, 30, 120):
            p = hist.get(s - k)
            x[f"d{k}"] = 0.0 if p is None else y - p
        for tau in (10, 60, 300):
            e = self.ema.get(tau)
            e = y if e is None else e + (y - e) / tau
            self.ema[tau] = e
            x[f"e{tau}"] = y - e
        self.vol += (abs(x["d1"]) - self.vol) / 60.0
        x["vol"] = self.vol
        ph = 2 * math.pi * (s % DAY) / DAY
        x["sin"], x["cos"] = math.sin(ph), math.cos(ph)
        return x


class Persistence:
    name = "persistence"

    def __init__(self, horizons, cfg, params):
        self.horizons = horizons

    def step(self, s, y, hist, x, fh):
        return {h: y for h in self.horizons}


class SeasonalNaive:
    name = "seasonal_naive"

    def __init__(self, horizons, cfg, params):
        self.horizons = horizons
        self.period = int(cfg["day_s"])

    def step(self, s, y, hist, x, fh):
        out = {}
        for h in self.horizons:
            v = hist.get(s + h - self.period)
            if v is not None:
                out[h] = v
        return out


class SeasonalAnchor:
    """Seasonal naive anchored to the present: y[s] + (y[s+h-P] - y[s-P]). Immune to level offsets."""
    name = "seasonal_anchor"

    def __init__(self, horizons, cfg, params):
        self.horizons = horizons
        self.period = int(cfg["day_s"])

    def step(self, s, y, hist, x, fh):
        base = hist.get(s - self.period)
        if base is None:
            return {}
        out = {}
        for h in self.horizons:
            v = hist.get(s + h - self.period)
            if v is not None:
                out[h] = y + v - base
        return out


class Holt:
    """Double exponential smoothing: level + h * trend."""
    name = "holt"

    def __init__(self, horizons, cfg, params):
        self.horizons = horizons
        self.a, self.b = params.get("alpha", 0.02), params.get("beta", 0.0003)
        self.level = self.trend = None

    def step(self, s, y, hist, x, fh):
        if self.level is None:
            self.level, self.trend = y, 0.0
        else:
            prev = self.level
            self.level = self.a * y + (1 - self.a) * (self.level + self.trend)
            self.trend = self.b * (self.level - prev) + (1 - self.b) * self.trend
        return {h: self.level + h * self.trend for h in self.horizons}


class Snarimax:
    """River SNARIMAX on the 1 s series. Forecasting every second to 3600 s is costly, so it
    forecasts every `stride` seconds."""
    name = "snarimax"

    def __init__(self, horizons, cfg, params):
        self.horizons, self.max_h = horizons, max(horizons)
        self.stride = params.get("stride", 10)
        self.m = time_series.SNARIMAX(p=params.get("p", 10), d=params.get("d", 1), q=params.get("q", 0),
                                      regressor=_snar_reg())

    def step(self, s, y, hist, x, fh):
        self.m.learn_one(y)
        if s % self.stride:
            return {}
        fc = self.m.forecast(self.max_h)
        return {h: fc[h - 1] for h in self.horizons}


def _clip(x: dict) -> dict:
    """Standardised features are cut at +-5 sigma: a spike fault must not blow up a linear learner."""
    return {k: max(-5.0, min(5.0, v)) for k, v in x.items()}


def _lin_sgd():
    return preprocessing.StandardScaler() | compose.FuncTransformer(_clip) | linear_model.LinearRegression(
        optimizer=optim.SGD(0.003), l2=0.0, intercept_lr=0.001)


def _lin_pa(C=0.05):
    return lambda: preprocessing.StandardScaler() | compose.FuncTransformer(_clip) | linear_model.PARegressor(C=C, mode=2)


def _lin_bayes():
    return preprocessing.StandardScaler() | compose.FuncTransformer(_clip) | linear_model.BayesianLinearRegression(alpha=1.0, beta=1.0)


_lin = _lin_bayes


def _snar_reg():
    # SNARIMAX feature sets grow over time, so the Bayesian model (fixed dimension) cannot be used here.
    return preprocessing.StandardScaler() | compose.FuncTransformer(_clip) | linear_model.LinearRegression(
        optimizer=optim.SGD(0.0005), loss=optim.losses.Huber(epsilon=1.0), l2=0.0, intercept_lr=0.0001)


class ForgettingRidge:
    """Exponentially forgetting ridge regression (RLS in batch form), river-style learn_one/predict_one.

    Keeps A = sum lam^k x x' and b = sum lam^k x y over standardised, clipped features plus an
    intercept, and solves (A + ridge I) w = b every `refit` learns. The ridge term does not decay,
    so a stuck sensor (constant features) cannot wind the covariance up the way textbook RLS does.
    Untrained, w = 0 and the forecast equals persistence (it predicts the increment).
    `boost(n)`: use the fast forgetting factor `lam_fast` for the next n learns, then return to `lam`."""

    def __init__(self, lam=0.9999, lam_fast=0.998, ridge=1.0, refit=5):
        self.lam, self.lam_fast, self.ridge, self.refit = lam, lam_fast, ridge, refit
        self.sc = preprocessing.StandardScaler()
        self.A = None
        self.b = self.w = None
        self.n = 0
        self.boost_left = 0

    def boost(self, n: int) -> None:
        self.boost_left = max(self.boost_left, n)

    def _z(self, x: dict) -> np.ndarray:
        t = self.sc.transform_one(x)
        z = np.fromiter((max(-5.0, min(5.0, v)) for v in t.values()), float, len(t))
        return np.append(z, 1.0)

    def learn_one(self, x: dict, y: float) -> None:
        self.sc.learn_one(x)
        z = self._z(x)
        if self.A is None:
            d = len(z)
            self.A, self.b, self.w = np.zeros((d, d)), np.zeros(d), np.zeros(d)
        lam = self.lam
        if self.boost_left > 0:
            lam, self.boost_left = self.lam_fast, self.boost_left - 1
        self.A = lam * self.A + np.outer(z, z)
        self.b = lam * self.b + z * y
        self.n += 1
        if self.n % self.refit == 0:
            self.w = np.linalg.solve(self.A + self.ridge * np.eye(len(z)), self.b)

    def predict_one(self, x: dict) -> float:
        if self.w is None:
            return 0.0
        return float(self._z(x) @ self.w)


class Direct:
    """One river regressor per horizon, trained on increments.

    `adwin`: an ADWIN detector watches each horizon's absolute error. On a detection a fresh
    challenger starts learning beside the champion; after `probation` paired samples the
    better one stays (no forgetting of what still works). `reset_on_drift` is the naive
    alternative (throw the model away), kept to measure how bad it is.
    `vn_boost` (RQ2, iteration 4): ADWIN on the *volatility-normalised* error (abs error divided by its
    own slow EWMA, clipped), and the response is soft: the model's forgetting is sped up for
    `boost_s` learns (`ForgettingRidge.boost`); nothing is reset or replaced.
    `static_after`: learning stops after that many seconds (the static arm for RQ2)."""

    def __init__(self, name, horizons, factory, adwin=False, reset_on_drift=False, static_after=None,
                 stride=1, probation=600, delta=0.002, vn_boost=False, vn_tau=1800.0, boost_s=600):
        self.name, self.horizons, self.factory = name, horizons, factory
        self.m = {h: factory() for h in horizons}
        self.adwin = {h: drift.ADWIN(delta=delta) for h in horizons} if adwin or reset_on_drift else None
        self.reset_on_drift, self.probation = reset_on_drift, probation
        self.vn = {h: drift.ADWIN(delta=delta) for h in horizons} if vn_boost else None
        self.vn_scale: dict[int, float] = {}
        self.vn_tau, self.boost_s = vn_tau, boost_s
        self.chal: dict[int, dict] = {}
        self.static_after, self.first_s, self.stride = static_after, None, stride
        self.events: list[tuple[int, int, str]] = []  # (second, horizon, kind), drained by the engine

    def recover(self) -> None:
        """After a library exception: start every horizon fresh rather than keep a broken model."""
        self.m = {h: self.factory() for h in self.horizons}
        self.chal.clear()

    def _on_score_vn(self, s: int, h: int, abs_err: float) -> None:
        sc = self.vn_scale.get(h)
        if sc is None:
            self.vn_scale[h] = max(abs_err, 1e-9)
            return
        z = min(abs_err / max(sc, 1e-9), 10.0)  # relative to what this horizon has been missing by lately
        self.vn_scale[h] = sc + (max(abs_err, 1e-9) - sc) / self.vn_tau
        d = self.vn[h]
        d.update(z)
        if d.drift_detected:
            self.events.append((s, h, "detected"))
            if hasattr(self.m[h], "boost"):
                self.m[h].boost(self.boost_s)
                self.events.append((s, h, "boost"))

    def on_score(self, s: int, h: int, abs_err: float) -> None:
        if self.vn is not None:
            self._on_score_vn(s, h, abs_err)
        if self.adwin is None:
            return
        d = self.adwin[h]
        d.update(abs_err)
        if not d.drift_detected:
            return
        self.events.append((s, h, "detected"))
        if self.reset_on_drift:
            self.m[h] = self.factory()
            self.events.append((s, h, "reset"))
        elif h not in self.chal:
            self.chal[h] = {"m": self.factory(), "e_new": 0.0, "e_old": 0.0, "n": 0}

    def _challenge(self, s, h, xo, target):
        c = self.chal[h]
        c["e_new"] += abs(c["m"].predict_one(xo) - target)
        c["e_old"] += abs(self.m[h].predict_one(xo) - target)
        c["n"] += 1
        c["m"].learn_one(xo, target)
        if c["n"] >= self.probation:
            if c["e_new"] < c["e_old"]:
                self.m[h] = c["m"]
                self.events.append((s, h, "swapped"))
            else:
                self.events.append((s, h, "kept"))
            del self.chal[h]

    def step(self, s, y, hist, x, fh):
        if self.first_s is None:
            self.first_s = s
        learning = self.static_after is None or s - self.first_s < self.static_after
        out = {}
        for h in self.horizons:
            if learning:
                xo, yo = fh.get(s - h), hist.get(s - h)
                if xo is not None and yo is not None:
                    if h in self.chal:
                        self._challenge(s, h, xo, y - yo)
                    self.m[h].learn_one(xo, y - yo)
            if s % self.stride == 0:
                out[h] = y + self.m[h].predict_one(x)
        return out


def _rls(lam, lam_fast=0.998):
    return lambda: ForgettingRidge(lam=lam, lam_fast=lam_fast)


def _hat():
    return tree.HoeffdingAdaptiveTreeRegressor(grace_period=100, seed=1)


def _arf(n):
    return lambda: forest.ARFRegressor(n_models=n, seed=1, grace_period=100)


def build(name: str, horizons, cfg, params):
    if name == "persistence": return Persistence(horizons, cfg, params)
    if name == "seasonal_naive": return SeasonalNaive(horizons, cfg, params)
    if name == "seasonal_anchor": return SeasonalAnchor(horizons, cfg, params)
    if name == "holt": return Holt(horizons, cfg, params)
    if name == "snarimax": return Snarimax(horizons, cfg, params)
    if name == "lin_sgd": return Direct(name, horizons, _lin_sgd)
    if name == "lin_pa": return Direct(name, horizons, _lin_pa(params.get("C", 0.05)))
    if name == "lin_bayes": return Direct(name, horizons, _lin_bayes)
    if name == "lin_lag": return Direct(name, horizons, _lin)
    if name == "lin_lag_adwin": return Direct(name, horizons, _lin, adwin=True)
    if name == "lin_lag_reset": return Direct(name, horizons, _lin, reset_on_drift=True)
    if name == "lin_lag_static": return Direct(name, horizons, _lin, static_after=int(params.get("static_after", 2 * DAY)))
    # RQ2 (iteration 4): forgetting instead of reset. lam 0.9999 = memory ~3 h, 0.99999 = ~28 h.
    if name == "lin_rls": return Direct(name, horizons, _rls(params.get("lam", 0.9999)))
    if name == "lin_rls_slow": return Direct(name, horizons, _rls(params.get("lam", 0.99999)))
    if name == "lin_rls_vn": return Direct(name, horizons, _rls(params.get("lam", 0.9999), params.get("lam_fast", 0.998)),
                                           vn_boost=True, vn_tau=params.get("vn_tau", 1800.0), boost_s=int(params.get("boost_s", 600)))
    if name == "hat": return Direct(name, horizons, _hat, stride=params.get("stride", 1))
    if name == "arf": return Direct(name, horizons, _arf(params.get("n_models", 5)), stride=params.get("stride", 1))
    raise KeyError(name)
