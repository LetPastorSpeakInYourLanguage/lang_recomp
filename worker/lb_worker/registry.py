"""Stage name -> handler.

A handler is ``fn(ctx) -> dict``. ``model_key`` groups stages that share loaded
weights: the loop runs queued jobs grouped by it, so one model loads once per
session instead of once per job.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Stage:
    name: str
    fn: Callable
    model_key: str = ""


STAGES: dict[str, Stage] = {}


def stage(name: str, model_key: str = ""):
    def deco(fn):
        STAGES[name] = Stage(name, fn, model_key or name)
        return fn

    return deco
