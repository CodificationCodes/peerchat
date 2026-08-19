"""Allows `python -m peerchat` as a shorthand for `python -m peerchat.cli`."""

from .cli import main

if __name__ == '__main__':
    main()
