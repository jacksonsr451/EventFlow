"""EventFlow Work Management service: persistence, repositories and migrations.

This package owns the Work Management bounded context's storage. It must not
import Order Processing code or share tables with another bounded context
(ADR-006, ADR-008).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
