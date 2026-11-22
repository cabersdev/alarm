from __future__ import annotations

import math
from collections import deque
from typing import Optional, Protocol

import numpy as np
from scipy import stats as sps

from ..schema.sensor import SensorReading
from ..schema.stats import CorrectionMethod, WindowStats

from ..config import load_config

class StatsPublisher(Protocol):
    def publish(self, stats: WindowStats) -> None: ...

class StatsService:
    """Sliding-window t-test with multiple-testing corrections."""

    cfg = load_config()

    def __init__(
        self,
        publisher: StatsPublisher,
        *,
        window_size: int = cfg.stats.window_size,
        mu0: float = cfg.stats.mu0,
        alpha: float = cfg.stats.alpha,
        correction_method: CorrectionMethod = cfg.correction_method,
        p_history_size: int = cfg.stats.p_history_size,
        sensor_id: str = cfg.sensor.id,
    ) -> None:
        if window_size < 2:
            raise ValueError("window_size must be >= 2 (need df > 0)")
        if not 0 < alpha < 1:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        if correction_method == "holm" and p_history_size < 2:
            raise ValueError("Holm requires p_history_size >= 2")
        if correction_method == "bh" and p_history_size < 2:
            raise ValueError("BH requires p_history_size >= 2")

        self._publisher = publisher
        self._n = window_size
        self._mu0 = mu0
        self._alpha = alpha
        self._method = correction_method
        self._sensor_id = sensor_id

        self._window: deque[float] = deque(maxlen=window_size)
        self._window_ts: deque[float] = deque(maxlen=window_size)
        self._p_history: deque[float] = deque(maxlen=p_history_size)
        self._p_history_m: deque[int] = deque(maxlen=p_history_size)

        self._m_tests = 0
        self._window_seq = 0
        self._t_crit = float(sps.t.ppf(1.0 - alpha, window_size - 1))

        print(
            f"""stats service ready: 
            n={window_size}, 
            mu0={mu0} 
            alpha={alpha}, 
            method={correction_method}, 
            t_crit={self._t_crit}""",
        )

    # Public API
    def on_sample(self, reading: SensorReading) -> Optional[WindowStats]:
        """Called for every raw sample. Returns WindowStats when the window is full."""
        self._window.append(reading.value)
        self._window_ts.append(reading.timestamp)
        if len(self._window) < self._n:
            return None
        result = self._compute_stats()
        self._window_seq += 1
        self._publisher.publish(result)
        return result

    def reset(self) -> None:
        """Reset the m_tests counter and the p-value history (new session)."""
        self._m_tests = 0
        self._p_history.clear()
        self._p_history_m.clear()
        self._window.clear()
        self._window_ts.clear()
        self._window_seq = 0

    # Computation
    def _compute_stats(self) -> WindowStats:
        arr = np.asarray(self._window, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std(ddof=1))
        mse = std / math.sqrt(self._n)

        # Degenerate case: all samples identical (should not happen with N(mu, sigma^2), sigma>0)
        if mse > 0:
            t_stat = (mean - self._mu0) / mse
            cohens_d = (mean - self._mu0) / std
        else:
            if mean > self._mu0:
                t_stat, cohens_d = float("inf"), float("inf")
            elif mean < self._mu0:
                t_stat, cohens_d = float("-inf"), float("-inf")
            else:
                t_stat, cohens_d = 0.0, 0.0

        df = self._n - 1
        # One-sided: p = P(T > t | H0)
        p_raw = float(1.0 - sps.t.cdf(t_stat, df))

        # Multiple-testing corrections
        self._m_tests += 1
        m = self._m_tests

        p_bonf = min(1.0, m * p_raw)
        if p_raw >= 1.0:
            p_sidak = 1.0
        else:
            # Stable computation: 1 - (1-p)^m = -expm1(m * log1p(-p))
            p_sidak = float(-math.expm1(m * math.log1p(-p_raw)))
            p_sidak = min(1.0, max(0.0, p_sidak))

        # Append BEFORE computing Holm/BH so the history includes the current test
        self._p_history.append(p_raw)
        self._p_history_m.append(m)

        p_holm: Optional[float] = None
        p_bh: Optional[float] = None
        if len(self._p_history) >= 2:
            p_holm, p_bh = self._holm_bh(p_raw)

        p_adj = self._select_adjusted(p_raw, p_bonf, p_sidak, p_holm, p_bh)

        lb = mean - self._t_crit * mse

        return WindowStats(
            window_seq=self._window_seq,
            window_size=self._n,
            window_start_ts=self._window_ts[0],
            window_end_ts=self._window_ts[-1],
            sensor_id=self._sensor_id,
            n=self._n,
            mean=mean,
            std=std,
            mse=mse,
            min_value=float(arr.min()),
            max_value=float(arr.max()),
            median=float(np.median(arr)),
            mu0=self._mu0,
            alpha=self._alpha,
            t_stat=float(t_stat),
            df=df,
            p_value_raw=p_raw,
            t_crit=self._t_crit,
            lb=lb,
            ci_level=1.0 - self._alpha,
            cohens_d=float(cohens_d),
            m_tests=m,
            p_value_bonferroni=p_bonf,
            p_value_sidak=p_sidak,
            p_value_holm=p_holm,
            p_value_bh=p_bh,
            p_value_adj=p_adj,
            correction_method=self._method,
            reject_null=(p_adj < self._alpha),
        )

    def _holm_bh(self, p_current: float) -> tuple[float, float]:
        """Holm and BH adjusted p-values for the current test, over the p_history window."""
        pvals = np.asarray(self._p_history, dtype=float)
        M = len(pvals)
        order = np.argsort(pvals, kind="stable")
        sorted_p = pvals[order]

        # Holm: p_adj_(i) = max_{k<=i} min(1, (M-k+1) * p_(k))
        factors = (M - np.arange(M)) * sorted_p
        holm_sorted = np.minimum(np.maximum.accumulate(factors), 1.0)
        holm_unsorted = np.empty(M)
        holm_unsorted[order] = holm_sorted
        p_holm = float(holm_unsorted[-1])  # current test = last appended

        # BH: p_adj_(i) = min_{k>=i} min(1, M * p_(k) / k)
        bh_factors = M * sorted_p / np.arange(1, M + 1)
        bh_sorted = np.minimum(np.minimum.accumulate(bh_factors[::-1])[::-1], 1.0)
        bh_unsorted = np.empty(M)
        bh_unsorted[order] = bh_sorted
        p_bh = float(bh_unsorted[-1])

        return p_holm, p_bh

    def _select_adjusted(
        self,
        p_raw: float,
        p_bonf: float,
        p_sidak: float,
        p_holm: Optional[float],
        p_bh: Optional[float],
    ) -> float:
        if self._method == "raw":
            return p_raw
        if self._method == "bonferroni":
            return p_bonf
        if self._method == "sidak":
            return p_sidak
        if self._method == "holm":
            if p_holm is None:
                raise RuntimeError("Holm adjustment unavailable (history too short)")
            return p_holm
        if self._method == "bh":
            if p_bh is None:
                raise RuntimeError("BH adjustment unavailable (history too short)")
            return p_bh
        raise ValueError(f"Unknown correction method: {self._method!r}")