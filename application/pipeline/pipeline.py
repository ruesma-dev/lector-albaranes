# application/pipeline/pipeline.py
from __future__ import annotations
# application/pipeline/pipeline.py

from typing import Any, Callable, Dict, List


class Pipeline:
    """
    Pipeline sencillo: lista de pasos callables (context -> context).
    """
    def __init__(self, steps: List[Callable[[Dict[str, Any]], Dict[str, Any]]]) -> None:
        self.steps = steps

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        for step in self.steps:
            context = step(context)
        return context
