"""Load `config/resorts.yaml` into validated Pydantic models.

Resorts live in config, not code (guardrail 9): adding a resort means adding
a YAML entry. Pydantic checks the file when it's loaded, so a typo such as
`latitde` fails loudly instead of silently becoming `None`.
"""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from skiiprep_common.settings import RESORTS_FILE


class Point(BaseModel):
    """One spot at a resort that we fetch weather for, e.g. `base` or `summit`.

    `elevation_m` is sent to Open-Meteo so it adjusts temperature to this
    height (SD1); that's what decides rain vs snow.
    """

    # frozen: points can't be changed after loading. forbid: unknown keys
    # in the YAML are an error, which catches typos.
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str  # used in bronze folder names (`point=summit`), so keep it stable
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation_m: int


class Resort(BaseModel):
    """A ski resort and the points we fetch data for."""

    # populate_by_name lets code build a Resort with `pass_=` while the YAML
    # uses `pass:`.
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    id: str  # short stable key used in folder names and URLs, e.g. `crystal`
    name: str
    state: str
    pass_: Literal["ikon", "epic", "indy", "none"] = Field(alias="pass")  # `pass` is a Python keyword
    timezone: str  # IANA name, e.g. America/Los_Angeles; used only when serving (SD2)
    points: tuple[Point, ...]  # a tuple, not a list, so a frozen Resort stays unchangeable


class ResortsConfig(BaseModel):
    """The whole YAML file: a top-level `resorts:` key holding a list."""

    resorts: list[Resort]


def load_resorts(path: Path = RESORTS_FILE) -> dict[str, Resort]:
    """Read and validate the resorts file, keyed by resort id.

    `path` defaults to `config/resorts.yaml`; tests can pass their own file.
    Raises `pydantic.ValidationError` if the file doesn't match the models.

    >>> load_resorts()["crystal"].points[0].name
    'base'
    """
    with open(path, "r") as f:
        yaml_data = yaml.safe_load(f)  # safe_load never runs code from the file

    cfg = ResortsConfig.model_validate(yaml_data)
    return {r.id: r for r in cfg.resorts}
