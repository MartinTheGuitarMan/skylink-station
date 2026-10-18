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


class ClearSky:
    """Ratio to a self-learned clear-sky envelope (backlog 4, solar).

    Solar loses to persistence because the daily ramp and noise add error that the cloud cliffs do not
    excuse. The envelope is the per-minute-of-day maximum of the 1-minute mean seen so far, decaying
    `decay` per day so seasonal changes are followed (nothing about the simulator's shape is built in).
    Clearness k = y / envelope, k_hat its mean over the last `k_win` values. Forecast for s+h, anchored
    (default): y + k_hat * (envelope(s+h) - envelope(s)), i.e. persistence plus the clear-sky ramp scaled by
    how cloudy it is now; unanchored (`anchor` = 0): envelope(s+h) * k_hat (persistence of the ratio). Regimes: when the envelope
    at s and at s+h is below `night_w` the sun is down and the forecast is persistence; the envelope
    needs `min_days` of history before it is trusted (before that: persistence)."""
    name = "clearsky"

    def __init__(self, horizons, cfg, params):
        self.horizons = horizons
        self.decay = params.get("decay", 0.97)
        self.k_win = int(params.get("k_win", 10))
        self.night_w = params.get("night_w", 15.0)
        self.anchor = bool(params.get("anchor", 1))
        self.gain = params.get("gain", 1.0)
        self.min_s = params.get("min_days", 1.0) * DAY
        self.env = np.zeros(1440)
        self.smooth = self.env
        self.smooth_bins = int(params.get("smooth_min", 10))  # the envelope is a moving average over 2n+1 minutes
        self.acc, self.acc_n, self.acc_bin = 0.0, 0, None
        self.first_s = None
        self.kbuf: deque = deque(maxlen=self.k_win)

    def _env_at(self, s: float) -> float:
        x = (s % DAY) / 60.0 - 0.5  # bin centres
        i = int(math.floor(x))
        f = x - i
        return float(self.smooth[i % 1440] * (1 - f) + self.smooth[(i + 1) % 1440] * f)

    def step(self, s, y, hist, x, fh):
        if self.first_s is None:
            self.first_s = s
        b = int((s % DAY) // 60)
        if self.acc_bin is not None and b != self.acc_bin:
            m = self.acc / max(self.acc_n, 1)
            self.env[self.acc_bin] = max(m, self.env[self.acc_bin] * self.decay)
            self.smooth = np.convolve(np.pad(self.env, self.smooth_bins, mode="wrap"),
                                      np.ones(2 * self.smooth_bins + 1) / (2 * self.smooth_bins + 1), mode="valid")
            self.acc, self.acc_n = 0.0, 0
        self.acc_bin = b
        self.acc += y
        self.acc_n += 1
        e0 = self._env_at(s)
        if e0 > self.night_w:
            self.kbuf.append(min(max(y / e0, 0.0), 1.5))
        trusted = s - self.first_s >= self.min_s and self.kbuf
        out = {}
        for h in self.horizons:
            eh = self._env_at(s + h)
            if trusted and e0 > self.night_w and eh > self.night_w:
                k = sum(self.kbuf) / len(self.kbuf)
                out[h] = max(y + self.gain * k * (eh - e0), 0.0) if self.anchor else eh * k
            else:
                out[h] = y
        return out


class ClearSkyShape:
    """Ratio to a fixed clear-sky shape: yhat(s+h) = y(s) * f(s+h) / f(s), f = max(cos(2 pi (t - noon) / P), 0) ^ p.

    Only the geometry of a day is assumed (sun peaks at local noon, no parameters are fitted). Where f(s) is
    below `floor` (night, deep dusk and dawn) the forecast is persistence, so is any step where the
    ratio would exceed `max_ratio`. Costs two cos() per horizon. `clearsky_adapt` (`adaptive` = 1) moves the
    noon of the shape to the centroid of the previous day's curve (blend 0.5 per day), which follows the
    seasonal phase shifts of the simulator; development seeds showed the fixed noon losing on seed 2."""
    name = "clearsky_shape"

    def __init__(self, horizons, cfg, params, name=None):
        self.name = name or self.name
        self.horizons = horizons
        self.p = params.get("p", 1.0)
        self.noon = params.get("noon_h", 12.0) * 3600
        self.floor = params.get("floor", 0.05)
        self.max_ratio = params.get("max_ratio", 2.0)
        # adaptive=1: the noon of the shape follows the centroid of yesterday's curve (phase shifts of the season)
        self.adaptive, self.blend = int(params.get("adaptive", 0)), params.get("blend", 0.5)
        self.day, self.sy, self.sty = None, 0.0, 0.0

    def _track(self, s: int, y: float) -> None:
        d = int(s // DAY)
        if self.day is not None and d != self.day:
            if self.sy > 0:
                self.noon += self.blend * (self.sty / self.sy - self.noon)
            self.sy = self.sty = 0.0
        self.day = d
        self.sy += y
        self.sty += y * (s % DAY)

    def _f(self, s: float) -> float:
        c = math.cos(2 * math.pi * (s - self.noon) / DAY)
        return c ** self.p if c > 0 else 0.0

    def step(self, s, y, hist, x, fh):
        if self.adaptive:
            self._track(s, max(y, 0.0))
        f0 = self._f(s)
        out = {}
        for h in self.horizons:
            if f0 < self.floor:
                out[h] = y
            else:
                out[h] = y * min(self._f(s + h) / f0, self.max_ratio)
        return out


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


class ShapeResidual(Direct):
    """Day regime only: a linear learner on the residual of the clear-sky-shape forecast (`ClearSkyShape`).

    Target for the pair (x at s-h, outcome y at s) = y - shape forecast made at s-h. At night (shape below
    `floor`) nothing is learned and the forecast is persistence. The question is whether anything is left
    for a learner once the deterministic ramp is removed; cloud cliffs say probably not."""

    def __init__(self, name, horizons, factory, params):
        super().__init__(name, horizons, factory)
        self.shape = ClearSkyShape(horizons, {}, params)

    def _base(self, y0, s0, s1):
        f0 = self.shape._f(s0)
        if f0 < self.shape.floor:
            return y0
        return y0 * min(self.shape._f(s1) / f0, self.shape.max_ratio)

    def step(self, s, y, hist, x, fh):
        out = {}
        for h in self.horizons:
            xo, yo = fh.get(s - h), hist.get(s - h)
            if xo is not None and yo is not None and self.shape._f(s - h) >= self.shape.floor:
                self.m[h].learn_one(xo, y - self._base(yo, s - h, s))
            base = self._base(y, s, s + h)
            out[h] = base + (self.m[h].predict_one(x) if self.shape._f(s) >= self.shape.floor else 0.0)
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
    if name == "lin_cs": return ShapeResidual(name, horizons, _lin, params)
    if name == "clearsky_adapt": return ClearSkyShape(horizons, cfg, {"adaptive": 1, **params}, name)
    if name == "clearsky_shape": return ClearSkyShape(horizons, cfg, params)
    if name == "clearsky": return ClearSky(horizons, cfg, params)
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
