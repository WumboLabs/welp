#!/usr/bin/env python3
"""greet - mini fixture program for bounds calibration."""
import sys

from formatters import bold


def greet(name):
    return f"Hello, {name}!"


def main():
    print(bold(greet(sys.argv[1] if len(sys.argv) > 1 else "world")))


if __name__ == "__main__":
    main()
