"""
Skill: histogram_from_intervals
Creates a histogram based on provided values and bins, counting occurrences in specified intervals.
"""

from typing import List, Dict

def histogram_from_intervals(vals: List[float], bins: List[float]) -> Dict[str, int]:
    """
    Construct a histogram by counting the number of values that fall into each bin interval.

    Args:
        vals (List[float]): A list of float values to be binned.
        bins (List[float]): A list of bin edges, which must be sorted in ascending order.

    Returns:
        Dict[str, int]: A dictionary where keys are interval ranges and values are counts of vals in those intervals.
    """
    hist: Dict[str, int] = {}
    for i in range(len(bins) - 1):
        hist[f"{bins[i]}-{bins[i+1]}"] = 0
    for v in vals:
        placed = False
        for i in range(len(bins) - 1):
            if bins[i] <= v < bins[i + 1]:
                hist[f"{bins[i]}-{bins[i+1]}"] += 1
                placed = True
                break
        if not placed and v >= bins[-1]:
            hist[f"{bins[-2]}-{bins[-1]}"] += 1
    return hist