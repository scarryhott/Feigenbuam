"""
Skill: create_histogram_from_floats
Creates a histogram from a list of float values and specified bins, useful for data analysis and visualization.
"""

from typing import List, Dict

def create_histogram_from_floats(vals: List[float], bins: List[float]) -> Dict[str, int]:
    """
    Create a histogram from a list of float values and specified bins.

    :param vals: List of float values to be binned.
    :param bins: List of bin edges.
    :return: A dictionary representing the histogram with bin ranges as keys.
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