"""Schema for the statistical summary of a sliding window of samples."""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field, model_validator


CorrectionMethod = Literal["raw", "bonferroni", "sidak", "holm", "bh"]


class WindowStats(BaseModel):
    """Statistical summary of one sliding window of n samples."""

    # Window metadata
    window_seq: int = Field(..., ge=0)
    window_size: int = Field(..., gt=1)
    window_start_ts: float = Field(..., gt=0)
    window_end_ts: float = Field(..., gt=0)
    sensor_id: str = Field(default="pressure-01")

    # Basic statistics
    n: int = Field(..., gt=1)
    mean: float
    std: float = Field(..., ge=0)
    sem: float = Field(..., ge=0, description="Standard error of the mean = std / sqrt(n)")
    min_value: float
    max_value: float
    median: float

    # One-sided t-test
    mu0: float
    alpha: float = Field(..., gt=0, lt=1)
    t_stat: float
    df: int = Field(..., gt=0)
    p_value_raw: float = Field(..., ge=0, le=1)
    t_crit: float = Field(..., gt=0)
    lb: float
    ci_level: float = Field(..., gt=0, lt=1)

    # Effect size
    cohens_d: float

    # Multiple testing
    m_tests: int = Field(..., ge=1)
    p_value_bonferroni: float = Field(..., ge=0, le=1)
    p_value_sidak: float = Field(..., ge=0, le=1)
    p_value_holm: Optional[float] = Field(default=None, ge=0, le=1)
    p_value_bh: Optional[float] = Field(default=None, ge=0, le=1)
    p_value_adj: float = Field(..., ge=0, le=1)
    correction_method: CorrectionMethod = Field(default="raw")

    # Decision
    reject_null: bool

    # Assumption checks (optional)
    shapiro_stat: Optional[float] = Field(default=None, ge=0)
    shapiro_pvalue: Optional[float] = Field(default=None, ge=0, le=1)

    # Ground truth (only available in simulation)
    mu_true: Optional[float] = Field(default=None)
    sigma_true: Optional[float] = Field(default=None, ge=0)
    h0_is_true: Optional[bool] = Field(
        default=None,
        description="Whether mu_true <= mu0 (true state of nature)",
    )

    # Computed fields
    @computed_field
    @property
    def is_correct_decision(self) -> Optional[bool]:
        if self.h0_is_true is None:
            return None
        return self.reject_null == (not self.h0_is_true)

    @computed_field
    @property
    def is_true_positive(self) -> Optional[bool]:
        if self.h0_is_true is None:
            return None
        return self.reject_null and (not self.h0_is_true)

    @computed_field
    @property
    def is_false_positive(self) -> Optional[bool]:
        if self.h0_is_true is None:
            return None
        return self.reject_null and self.h0_is_true

    @model_validator(mode="after")
    def _check_consistency(self) -> "WindowStats":
        if self.n != self.window_size:
            raise ValueError("n must equal window_size")
        if self.df != self.n - 1:
            raise ValueError("df must equal n - 1")
        if not math.isclose(self.ci_level, 1.0 - self.alpha, abs_tol=1e-12):
            raise ValueError("ci_level must equal 1 - alpha")

        expected_bonf = min(1.0, self.m_tests * self.p_value_raw)
        if not math.isclose(self.p_value_bonferroni, expected_bonf, abs_tol=1e-9):
            raise ValueError(f"p_value_bonferroni inconsistent: expected {expected_bonf:.6e}")

        if self.p_value_raw >= 1.0:
            expected_sidak = 1.0
        else:
            expected_sidak = -math.expm1(self.m_tests * math.log1p(-self.p_value_raw))
        if not math.isclose(self.p_value_sidak, expected_sidak, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(f"p_value_sidak inconsistent: expected {expected_sidak:.6e}")

        mapping = {
            "raw": self.p_value_raw,
            "bonferroni": self.p_value_bonferroni,
            "sidak": self.p_value_sidak,
            "holm": self.p_value_holm,
            "bh": self.p_value_bh,
        }
        expected_adj = mapping[self.correction_method]
        if expected_adj is None:
            raise ValueError(
                f"correction_method={self.correction_method} but corresponding p-value is None"
            )
        if not math.isclose(self.p_value_adj, expected_adj, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("p_value_adj inconsistent with correction_method")

        if self.reject_null != (self.p_value_adj < self.alpha):
            raise ValueError("reject_null must equal (p_value_adj < alpha)")

        expected_lb = self.mean - self.t_crit * self.sem
        if not math.isclose(self.lb, expected_lb, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(f"lb inconsistent: expected {expected_lb:.6e}")

        return self