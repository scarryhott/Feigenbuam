"""
Skill: compute_histogram_from_values
Compute a histogram from a list of values based on specified bins, returning the count of values within each bin range.
"""

from typing import List, Dict

def compute_histogram_from_values(vals: List[float], bins: List[float]) -> Dict[str, int]:
    """
    Compute a histogram from a list of values based on specified bins.

    Args:
        vals (List[float]): The list of values to analyze.
        bins (List[float]): The bin edges used to categorize the values.

    Returns:
        Dict[str, int]: A dictionary where keys represent the bin ranges and values represent the count of values in each bin.
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