"""Statistics service: sliding-window t-test with multiple-testing corrections."""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import Optional, Protocol

import numpy as np
from scipy import stats as sps

from ..schema.sensor import SensorReading
from ..schema.stats import CorrectionMethod, WindowStats

log = logging.getLogger(__name__)


class StatsPublisher(Protocol):
    def publish(self, stats: WindowStats) -> None: ...


class StatsService:
    def __init__(
        self,
        publisher: StatsPublisher,
        *,
        window_size: int,
        mu0: float,
        alpha: float,
        correction_method: CorrectionMethod,
        p_history_size: int = 1000,
        sensor_id: str = "pressure-01",
        compute_shapiro: bool = False,
        mu_true: Optional[float] = None,
        sigma_true: Optional[float] = None,
    ) -> None:
        if window_size < 2:
            raise ValueError("window_size must be >= 2 (need df > 0)")
        if not 0 < alpha < 1:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        if correction_method in ("holm", "bh") and p_history_size < 2:
            raise ValueError(f"{correction_method} requires p_history_size >= 2")

        self._publisher = publisher
        self._n = window_size
        self._mu0 = mu0
        self._alpha = alpha
        self._method = correction_method
        self._sensor_id = sensor_id
        self._compute_shapiro = compute_shapiro
        self._mu_true = mu_true
        self._sigma_true = sigma_true

        self._window: deque[float] = deque(maxlen=window_size)
        self._window_ts: deque[float] = deque(maxlen=window_size)
        self._p_history: deque[float] = deque(maxlen=p_history_size)
        self._p_history_m: deque[int] = deque(maxlen=p_history_size)

        self._m_tests = 0
        self._window_seq = 0
        self._t_crit = float(sps.t.ppf(1.0 - alpha, window_size - 1))

        log.info(
            "stats service ready: n=%d mu0=%.3f alpha=%.3f method=%s t_crit=%.4f",
            window_size, mu0, alpha, correction_method, self._t_crit,
        )

    def on_sample(self, reading: SensorReading) -> Optional[WindowStats]:
        self._window.append(reading.value)
        self._window_ts.append(reading.timestamp)
        if len(self._window) < self._n:
            return None
        result = self._compute_stats()
        self._window_seq += 1
        self._publisher.publish(result)
        return result

    def reset(self) -> None:
        self._m_tests = 0
        self._p_history.clear()
        self._p_history_m.clear()
        self._window.clear()
        self._window_ts.clear()
        self._window_seq = 0

    def _compute_stats(self) -> WindowStats:
        arr = np.asarray(self._window, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std(ddof=1))
        sem = std / math.sqrt(self._n)   # standard error of the mean

        if sem > 0:
            t_stat = (mean - self._mu0) / sem
            cohens_d = (mean - self._mu0) / std if std > 0 else 0.0
        else:
            if mean > self._mu0:
                t_stat, cohens_d = float("inf"), float("inf")
            elif mean < self._mu0:
                t_stat, cohens_d = float("-inf"), float("-inf")
            else:
                t_stat, cohens_d = 0.0, 0.0

        df = self._n - 1
        p_raw = float(1.0 - sps.t.cdf(t_stat, df))

        # Multiple testing
        self._m_tests += 1
        m = self._m_tests
        p_bonf = min(1.0, m * p_raw)
        p_sidak = (
            1.0 if p_raw >= 1.0
            else min(1.0, max(0.0, -math.expm1(m * math.log1p(-p_raw))))
        )

        self._p_history.append(p_raw)
        self._p_history_m.append(m)

        p_holm: Optional[float] = None
        p_bh: Optional[float] = None
        if len(self._p_history) >= 2:
            p_holm, p_bh = self._holm_bh()
        elif self._method in ("holm", "bh"):
            # First test: no correction possible, use raw
            p_holm = p_raw
            p_bh = p_raw

        p_adj = self._select_adjusted(p_raw, p_bonf, p_sidak, p_holm, p_bh)
        lb = mean - self._t_crit * sem

        shapiro_stat: Optional[float] = None
        shapiro_p: Optional[float] = None
        if self._compute_shapiro and self._n >= 3:
            shapiro_stat, shapiro_p = map(float, sps.shapiro(arr))

        h0_is_true: Optional[bool] = None
        if self._mu_true is not None:
            h0_is_true = self._mu_true <= self._mu0

        return WindowStats(
            window_seq=self._window_seq,
            window_size=self._n,
            window_start_ts=self._window_ts[0],
            window_end_ts=self._window_ts[-1],
            sensor_id=self._sensor_id,
            n=self._n,
            mean=mean,
            std=std,
            sem=sem,
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
            shapiro_stat=shapiro_stat,
            shapiro_pvalue=shapiro_p,
            mu_true=self._mu_true,
            sigma_true=self._sigma_true,
            h0_is_true=h0_is_true,
        )

    def _holm_bh(self) -> tuple[float, float]:
        pvals = np.asarray(self._p_history, dtype=float)
        M = len(pvals)
        order = np.argsort(pvals, kind="stable")
        sorted_p = pvals[order]

        factors = (M - np.arange(M)) * sorted_p
        holm_sorted = np.minimum(np.maximum.accumulate(factors), 1.0)
        holm_unsorted = np.empty(M)
        holm_unsorted[order] = holm_sorted
        p_holm = float(holm_unsorted[-1])

        bh_factors = M * sorted_p / np.arange(1, M + 1)
        bh_sorted = np.minimum(np.minimum.accumulate(bh_factors[::-1])[::-1], 1.0)
        bh_unsorted = np.empty(M)
        bh_unsorted[order] = bh_sorted
        p_bh = float(bh_unsorted[-1])

        return p_holm, p_bh

    def _select_adjusted(
        self, p_raw: float, p_bonf: float, p_sidak: float,
        p_holm: Optional[float], p_bh: Optional[float],
    ) -> float:
        if self._method == "raw":
            return p_raw
        if self._method == "bonferroni":
            return p_bonf
        if self._method == "sidak":
            return p_sidak
        if self._method == "holm":
            if p_holm is None:
                raise RuntimeError("Holm adjustment unavailable")
            return p_holm
        if self._method == "bh":
            if p_bh is None:
                raise RuntimeError("BH adjustment unavailable")
            return p_bh
        raise ValueError(f"Unknown correction method: {self._method!r}")