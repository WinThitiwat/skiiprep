"""Command line entry point: `uv run transform weather`.

One subcommand per table or job family, so more silver and gold jobs can be
added later next to `weather`. The logic lives in `jobs/`; this file only
parses arguments and calls it.
"""
import argparse
import logging

from skiiprep_transformation.jobs import weather_hourly


def _weather(args: argparse.Namespace) -> None:
    """`transform weather`: MERGE every bronze forecast file into silver_weather_hourly."""
    weather_hourly.execute()


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the chosen subcommand.

    Registered as the `transform` script in pyproject.toml. `argv` defaults to
    the real command line; tests can pass a list like `["weather"]`.
    """
    parser = argparse.ArgumentParser(prog="transform", description="Build silver tables from bronze.")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logs")
    subcommands = parser.add_subparsers(dest="command", required=True)

    weather = subcommands.add_parser("weather", help="Open-Meteo hourly forecasts into silver_weather_hourly")
    weather.set_defaults(func=_weather)  # each subcommand names the function that runs it

    args = parser.parse_args(argv)
    # Logging is configured here, at the entry point, not in library code.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
