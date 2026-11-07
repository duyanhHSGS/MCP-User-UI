"""Flet desktop entry point for MCP User UI."""

import flet as ft

from app import main


if __name__ == "__main__":
    ft.run(main, view=ft.AppView.FLET_APP)
