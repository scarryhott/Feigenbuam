"""
Skill: create_histogram_from_floats_v2
Generates a histogram from a list of float values based on specified bins, categorizing the values into defined ranges.
"""

from typing import List, Dict

def create_histogram_from_floats_v2(vals: List[float], bins: List[float]) -> Dict[str, int]:
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