"""report — Generator laporan Excel trading.

Modul:
  styles    — Konstanta warna dan helper styling openpyxl
  sheets    — Fungsi pembuatan tiap sheet
  generator — Entry point generate_report()
"""
from src.infra.report.generator import generate_report

__all__ = ["generate_report"]
