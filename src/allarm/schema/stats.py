"""Schema for the statistical summary of a sliding window of samples.

Each window produces:
- descriptive statistics of the n samples,
- a one-sided t-test H0: mu <= mu0 vs H1: mu > mu0,
- the dual formulation via the one-sided lower confidence bound LB,
- the effect size (Cohen's d),
- multiple-testing corrections (online: Bonferroni, Sidak; offline: Holm, BH),
- optional ground-truth fields (available because the source is simulated),
  which make the flag *measurable as a classifier* downstream.

The t-test assumes iid Gaussian samples. The simulator produces exactly that,
so no correction for non-normality is needed. The only corrections that matter
are for multiple testing: in continuous monitoring you run one test per window,
so the family-wise error rate (FWER) or the false discovery rate (FDR) grows
with the number of tests. The schema captures both the raw and the adjusted
p-values so the alarm can decide which criterion to use.
"""

from __future__ import annotations

import math
from typing import Literal, Optional
from pydantic import BaseModel, Field, computed_field, model_validator

CorrectionMethod = Literal["raw", "bonferroni", "sidak", "holm", "bh"]

class WindowStats(BaseModel):
    """Statistical summary of one sliding window of n samples."""

    # Window metadata
    window_seq: int = Field(..., ge=0, description="Monotonic window counter")
    window_size: int = Field(..., gt=1, description="Number of samples in the window")
    window_start_ts: float = Field(..., gt=0, description="Timestamp of the first sample")
    window_end_ts: float = Field(..., gt=0, description="Timestamp of the last sample")
    sensor_id: str = Field(default="pressure-01")

    # Basic statistics
    n: int = Field(..., gt=1, description="Number of samples (equals window_size)")
    mean: float = Field(..., description="Sample mean")
    std: float = Field(..., ge=0, description="Sample standard deviation (ddof=1)")
    sem: float = Field(..., ge=0, description="Standard error of the mean = std / sqrt(n)")
    min_value: float
    max_value: float
    median: float

    # One-sided t-test
    mu0: float = Field(..., description="Null-hypothesis value for the mean")
    alpha: float = Field(..., gt=0, lt=1, description="Nominal significance level")
    t_stat: float = Field(..., description="(mean - mu0) / sem")
    df: int = Field(..., gt=0, description="Degrees of freedom (n - 1)")
    p_value_raw: float = Field(..., ge=0, le=1, description="Uncorrected p-value")
    t_crit: float = Field(..., gt=0, description="t_{1-alpha, df}")
    lb: float = Field(..., description="One-sided lower confidence bound (mean - t_crit * sem)")
    ci_level: float = Field(..., gt=0, lt=1, description="Confidence level = 1 - alpha")

    # Effect size
    cohens_d: float = Field(..., description="(mean - mu0) / std; ±inf if std == 0")

    # Multiple testing corrections
    m_tests: int = Field(
        ...,
        ge=1,
        description="Total number of tests performed so far (this one included)",
    )
    p_value_bonferroni: float = Field(
        ..., ge=0, le=1, description="min(m * p_raw, 1)"
    )
    p_value_sidak: float = Field(
        ..., ge=0, le=1, description="1 - (1 - p_raw)^m"
    )
    p_value_holm: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Holm-adjusted p-value; requires the full p-value history, "
        "populated by the service when available",
    )
    p_value_bh: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Benjamini-Hochberg adjusted p-value; requires the full "
        "p-value history, populated by the service when available",
    )
    p_value_adj: float = Field(
        ..., ge=0, le=1, description="Final adjusted p-value used for the decision"
    )
    correction_method: CorrectionMethod = Field(
        default="raw",
        description="Which correction produced p_value_adj",
    )

    # Decision
    reject_null: bool = Field(
        ...,
        description="p_value_adj < alpha; this is the boolean that drives the alarm",
    )

    # Computed fields
    @computed_field
    @property
    def is_correct_decision(self) -> Optional[bool]:
        """Whether reject_null matches the ground truth (None if unknown)."""
        if self.h0_is_true is None:
            return None
        return self.reject_null == (not self.h0_is_true)

    @computed_field
    @property
    def is_true_positive(self) -> Optional[bool]:
        """True positive: reject_null and H0 is false."""
        if self.h0_is_true is None:
            return None
        return self.reject_null and (not self.h0_is_true)

    @computed_field
    @property
    def is_false_positive(self) -> Optional[bool]:
        """False positive: reject_null and H0 is true."""
        if self.h0_is_true is None:
            return None
        return self.reject_null and self.h0_is_true

    # Consistency validators
    @model_validator(mode="after")
    def _check_consistency(self) -> "WindowStats":
        if self.df != self.n - 1:
            raise ValueError("df must equal n - 1")
        if not math.isclose(self.ci_level, 1.0 - self.alpha, abs_tol=1e-12):
            raise ValueError("ci_level must equal 1 - alpha")

        # Bonferroni must be min(m * p_raw, 1)
        expected_bonf = min(1.0, self.m_tests * self.p_value_raw)
        if not math.isclose(self.p_value_bonferroni, expected_bonf, abs_tol=1e-9):
            raise ValueError(
                f"p_value_bonferroni inconsistent: expected {expected_bonf:.6e}"
            )

        # Sidak must be 1 - (1 - p)^m, computed stably
        if self.p_value_raw >= 1.0:
            expected_sidak = 1.0
        else:
            expected_sidak = -math.expm1(self.m_tests * math.log1p(-self.p_value_raw))
        if not math.isclose(self.p_value_sidak, expected_sidak, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                f"p_value_sidak inconsistent: expected {expected_sidak:.6e}"
            )

        # p_value_adj must match the declared correction_method (when computable)
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
                f"correction_method={self.correction_method} but the corresponding "
                "adjusted p-value is None; the service must populate it"
            )
        if not math.isclose(self.p_value_adj, expected_adj, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                f"p_value_adj inconsistent with correction_method={self.correction_method}"
            )

        # reject_null must be consistent with p_value_adj < alpha
        if self.reject_null != (self.p_value_adj < self.alpha):
            raise ValueError("reject_null must equal (p_value_adj < alpha)")

        # CI level sanity: lb = mean - t_crit * sem (up to floating point)
        expected_lb = self.mean - self.t_crit * self.sem
        if not math.isclose(self.lb, expected_lb, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(f"lb inconsistent: expected {expected_lb:.6e}")

        return self