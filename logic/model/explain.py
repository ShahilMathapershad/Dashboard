"""Feature contributions for the linear Huber model.

`compute_feature_contributions()` returns per-feature contributions
(coefficient × scaled-value) sorted by magnitude. The legacy
`predict_next_month()` computes these inline as part of its god-function
payload; this module exposes them under the new-API name Task 5 expects.
"""
from logic.model.inference import predict_next_month


def compute_feature_contributions(features=None):
    """Return per-feature contributions for the latest prediction.

    Args:
        features: Ignored (forward-compat with Task 5 signature). Always
            piggy-backs on the cached `predict_next_month()` result, which
            includes contributions computed against the latest engineered
            row from Supabase.

    Returns:
        list[dict] each with keys: feature, coefficient, unscaled_coefficient,
        category, scaled_value, contribution. Sorted by abs(contribution) desc.
    """
    result = predict_next_month()
    return result.get('contributions', [])
