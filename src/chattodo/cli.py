"""CLI entrypoint for chattodo."""

from __future__ import annotations

import click
from chatstyle import add_tree_option

from chattodo import __version__


@click.group(name="chattodo", invoke_without_command=True, no_args_is_help=True)
@click.version_option(__version__, prog_name="chattodo")
@add_tree_option(renderer_options={"root_name": "chattodo"})
def main() -> None:
    """chattodo command line interface."""
    # Add package-specific commands here. Prefer ChatStyle helpers for
    # interactive input when a command needs recoverable user input.
    pass


if __name__ == "__main__":
    main()
