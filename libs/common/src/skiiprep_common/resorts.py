from pathlib import Path
from typing import Literal
from skiiprep_common.settings import RESORTS_FILE
import yaml
from pydantic import BaseModel, ConfigDict, Field


class Point(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation_m: int


class Resort(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)
    id: str
    name: str
    state: str
    pass_: Literal["ikon", "epic", "indy", "none"] = Field(alias="pass")  # `pass` is a Python keyword
    timezone: str
    points: tuple[Point, ...]


class ResortsConfig(BaseModel):
    resorts: list[Resort]


def load_resorts(path: Path = RESORTS_FILE) -> dict[str, Resort]:
    with open(path, "r") as f:
        yaml_data = yaml.safe_load(f)

    cfg = ResortsConfig.model_validate(yaml_data)
    return {r.id: r for r in cfg.resorts}

