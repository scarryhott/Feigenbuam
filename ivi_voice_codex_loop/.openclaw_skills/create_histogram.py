"""
Skill: create_histogram
Generates a histogram from a list of values based on specified bins.
"""

from typing import List, Dict

def create_histogram(vals: List[float], bins: List[float]) -> Dict[str, int]:
    """
    Creates a histogram from a list of float values based on the given bins.

    :param vals: List of float values to categorize.
    :param bins: List of bin edges, must be sorted.
    :return: Dictionary with bin ranges as keys and counts as values.
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