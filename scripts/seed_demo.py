"""Write two sample PDFs from generated demo data: python scripts/seed_demo.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from finbot.demo import build_demo  # noqa: E402
from datetime import date  # noqa: E402
from finbot.reports import dataset, monthly_pdf, yearly_pdf  # noqa: E402

demo = build_demo()
today = date(2026, 10, 31)
Path("demo-monthly.pdf").write_bytes(monthly_pdf.render(dataset.monthly(demo.repo, demo.settings, 2026, 10, today)))
Path("demo-yearly.pdf").write_bytes(yearly_pdf.render(dataset.yearly(demo.repo, demo.settings, 2026, today)))
print("wrote demo-monthly.pdf and demo-yearly.pdf")
