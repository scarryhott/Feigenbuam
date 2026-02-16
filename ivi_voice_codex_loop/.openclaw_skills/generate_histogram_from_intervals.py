"""
Skill: generate_histogram_from_intervals
Generates a histogram from a list of floating-point values based on specified intervals (bins).
"""

from typing import List, Dict

def generate_histogram_from_intervals(vals: List[float], bins: List[float]) -> Dict[str, int]:
    """
    Generates a histogram counting the number of values falling into each specified bin range.

    :param vals: List of floating-point values to be binned.
    :param bins: List of bin edges. Must be sorted in ascending order.
    :return: A dictionary where keys are bin ranges and values are the counts of values in each bin.
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