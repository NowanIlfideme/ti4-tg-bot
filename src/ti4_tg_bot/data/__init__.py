"""Set up the data."""

from pathlib import Path

from pydantic_yaml import parse_yaml_file_as

from .models import GameInfo

__all__ = ["data_path", "base_game"]

data_path = Path(__file__).parent

base_game = parse_yaml_file_as(GameInfo, data_path / "base_game.yaml")
