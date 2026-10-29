"""Run the web app or generate a report without a browser."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stock_crawler", description="Create sourced, scenario-based stock research PDFs.")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="start the local web application")
    serve.add_argument("--host", default="127.0.0.1", help="listen address (default: 127.0.0.1)")
    serve.add_argument("--port", default=8000, type=int)
    report = commands.add_parser("report", help="generate a PDF from the command line")
    report.add_argument("ticker", nargs="?", help="Yahoo Finance symbol, e.g. AAPL or VOD.L")
    report.add_argument("--demo", action="store_true", help="use an entirely fictional, offline dataset")
    report.add_argument("--output", "-o", help="destination PDF path (defaults to reports/<ticker>-research.pdf)")
    backtest = commands.add_parser("backtest", help="reproduce the historical subset test from CSV files")
    backtest.add_argument("ticker", help="ticker label for the supplied history")
    backtest.add_argument("--prices", required=True, help="daily CSV with Date, Close and Adj Close columns")
    backtest.add_argument("--sector", default="", help="current provider sector; required to include macro factors")
    backtest.add_argument("--macro-dir", help="optional directory containing FRED DGS10.csv, UNRATE.csv and CPIAUCSL.csv")
    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn
        uvicorn.run("stock_crawler.app:app", host=args.host, port=args.port, log_level="info")
        return 0
    if args.command == "backtest":
        from stock_crawler.backtest_cli import backtest_from_csv, print_backtest
        try:
            result = backtest_from_csv(args.ticker, Path(args.prices), args.sector,
                                       Path(args.macro_dir) if args.macro_dir else None)
            print_backtest(args.ticker, result)
            return 0
        except (ValueError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    if not args.ticker and not args.demo:
        parser.error("report requires a ticker unless --demo is supplied")
    from stock_crawler.utils import normalize_ticker
    from stock_crawler.sources.market import MarketDataError
    try:
        ticker = normalize_ticker(args.ticker or "DEMO")
        from stock_crawler.analysis import analyze
        from stock_crawler.collector import collect
        from stock_crawler.report import create_report
        snapshot = collect(ticker, demo=args.demo, progress=lambda _p, stage: print(stage, file=sys.stderr))
        analysis = analyze(snapshot)
        output = Path(args.output or f"reports/{snapshot.ticker}-research.pdf").expanduser().resolve()
        pages = create_report(snapshot, analysis, output)
        from stock_crawler.archive import record_signal
        analysis.limitations.extend(record_signal(snapshot, analysis))
        print(f"Saved {pages}-page report: {output}")
        print(f"Conclusion: {analysis.verdict}; data coverage: {analysis.coverage:.0%}.")
        for warning in analysis.limitations:
            print(f"Note: {warning}", file=sys.stderr)
        return 0
    except (ValueError, MarketDataError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
