import sys
from pathlib import Path

# Ensure project root is on the path so `src.*` imports resolve correctly
sys.path.insert(0, str(Path(__file__).parent.parent))
