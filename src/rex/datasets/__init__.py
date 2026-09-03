"""Data layer: dataset loading, normalization, stratified sampling."""
from rex.datasets.loader import load_code_contests, load_local, load_taco, save_local
from rex.datasets.sampling import difficulty_stats, sample_sizes, stratified_sample
from rex.datasets.schema import dump_questions, index_by_id, load_questions

__all__ = [
    "load_taco", "load_code_contests", "load_local", "save_local",
    "difficulty_stats", "stratified_sample", "sample_sizes",
    "load_questions", "dump_questions", "index_by_id",
]
