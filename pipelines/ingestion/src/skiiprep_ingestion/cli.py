"""Command line entry point: `uv run ingest weather`.

One subcommand per source family, so `snow` and `roads` can be added later
next to `weather`.
"""
import argparse
import logging

from skiiprep_common.resorts import load_resorts

from skiiprep_ingestion import open_meteo


def _weather(args: argparse.Namespace) -> None:
    """`ingest weather`: fetch the Open-Meteo forecast for every point of every
    resort in config/resorts.yaml and write one bronze file per point."""
    resorts = load_resorts()
    paths = open_meteo.ingest(resorts.values())
    logging.getLogger(__name__).info("Done: %d file(s) written to bronze", len(paths))


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the chosen subcommand.

    Registered as the `ingest` script in pyproject.toml. `argv` defaults to
    the real command line; tests can pass a list like `["weather"]`.
    """
    parser = argparse.ArgumentParser(prog="ingest", description="Fetch raw data into bronze.")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logs")
    subcommands = parser.add_subparsers(dest="command", required=True)

    weather = subcommands.add_parser("weather", help="Open-Meteo hourly forecast for every resort point")
    weather.set_defaults(func=_weather)  # each subcommand names the function that runs it

    args = parser.parse_args(argv)
    # Logging is configured here, at the entry point, not in library code:
    # the CLI decides how much to show; modules just log.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
