from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IVI_LOOP_ROOT = ROOT / "ivi_voice_codex_loop"
if str(IVI_LOOP_ROOT) not in sys.path:
    sys.path.insert(0, str(IVI_LOOP_ROOT))
