"""brief-sim: run GAIA's real brief system over simulated days and report every mismatch.

python -m briefsim run --days 14 --out .context/brief-sim/<run>
python -m briefsim report --out .context/brief-sim/<run>
"""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from briefsim import oracle, report
from briefsim.run import run


def _next_monday() -> datetime:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return today + timedelta(days=7 - today.weekday())


def main() -> None:
    parser = argparse.ArgumentParser(prog="brief-sim")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run", help="boot the stack and simulate the founder")
    run_cmd.add_argument("--days", type=int, default=14)
    run_cmd.add_argument("--out", type=Path, required=True)
    report_cmd = commands.add_parser(
        "report", help="re-check a finished run and rebuild findings.json and report.html"
    )
    report_cmd.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out: Path = args.out.resolve()
    if args.command == "run":
        run(out, origin=_next_monday(), days=args.days)
    else:
        oracle.write_findings(out)
    report.write(out)


if __name__ == "__main__":
    main()
