"""
Re-export all symbols from backend/generic_service.py.
Ensures both 'from services import generic_service' and
'import generic_service' work identically across the application.
"""

import sys
import os

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from generic_service import *
