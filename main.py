"""A tiny, reusable Hello World program."""


def make_greeting(name: str = "World") -> str:
    """Build a friendly greeting for *name*."""
    return f"Hello, {name}!"


def main() -> None:
    """Print the default greeting."""
    print(make_greeting())


if __name__ == "__main__":
    main()


# TODO: Replace the demo greeting when this template gets a real purpose.
