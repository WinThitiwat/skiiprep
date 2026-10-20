"""Command line entry point: `uv run ingest weather`.

One subcommand per source family, so `snow` and `roads` can be added later
next to `weather`.
"""
import argparse
import logging

from skiiprep_common.resorts import load_resorts

from skiiprep_ingestion import open_meteo


def _weather(args: argparse.Namespace) -> None:
    resorts = load_resorts()
    paths = open_meteo.ingest(resorts.values())
    logging.getLogger(__name__).info("Done: %d file(s) written to bronze", len(paths))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ingest", description="Fetch raw data into bronze.")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logs")
    subcommands = parser.add_subparsers(dest="command", required=True)

    weather = subcommands.add_parser("weather", help="Open-Meteo hourly forecast for every resort point")
    weather.set_defaults(func=_weather)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
