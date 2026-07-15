#!/usr/bin/env python3
"""Generate a new provider skeleton.

Usage:
    python scripts/create_provider.py --name my_source --markets CN --types news,reports
    python scripts/create_provider.py --name my_source --markets CN --types news --custom
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TEMPLATE = '''\
"""{class_name} - TODO: Describe this provider"""

from __future__ import annotations

import logging

from backend.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class {class_name}(BaseProvider):
    """TODO: Describe your data source"""

    name = "{name}"
    markets = {markets}
    data_types = {data_types}
    priority = {priority}
    license_level = "research_only"
    data_class = "fundamental"
    freshness = "daily"
    cost_tier = "free"
    rate_limit = {{"per_minute": 60, "per_day": None}}
    requires_key = False

    @classmethod
    def is_available(cls) -> bool:
        return True

{methods}
'''

METHOD_TEMPLATE = '''\
    def get_{method}(self, query: dict, **kwargs) -> list[dict]:
        """Fetch {method} data.

        Args:
            query: {{"market": "CN", "symbol": "600519", "limit": 30, ...}}

        Returns:
            List of dicts
        """
        raise NotImplementedError
'''

ALL_METHODS = [
    "news",
    "reports",
    "announcements",
    "prices",
    "fundamentals",
    "fund_flow",
]


def main():
    parser = argparse.ArgumentParser(description="Generate a new AlphaScope provider")
    parser.add_argument("--name", required=True, help="Provider name (snake_case)")
    parser.add_argument("--markets", default="CN", help="Comma-separated markets (CN,HK,US,ALL)")
    parser.add_argument(
        "--types",
        default="news",
        help="Comma-separated data types (news,reports,announcements,prices,fundamentals,fund_flow)",
    )
    parser.add_argument("--priority", type=int, default=50, help="Default priority (0-100)")
    parser.add_argument(
        "--custom",
        action="store_true",
        help="Place in custom_providers/ instead of backend/providers/",
    )
    args = parser.parse_args()

    name = args.name.lower().strip()
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Provider"
    markets = repr([m.strip().upper() for m in args.markets.split(",")])
    data_types = [t.strip() for t in args.types.split(",")]

    # Validate data types
    valid_types = set(ALL_METHODS)
    for dt in data_types:
        if dt not in valid_types:
            print(
                f"Error: invalid data type '{dt}'. Valid: {', '.join(sorted(valid_types))}",
                file=sys.stderr,
            )
            sys.exit(1)

    methods = "\n".join(METHOD_TEMPLATE.format(method=dt) for dt in data_types)

    content = TEMPLATE.format(
        class_name=class_name,
        name=name,
        markets=markets,
        data_types=repr(data_types),
        priority=args.priority,
        methods=methods,
    )

    target_dir = Path("custom_providers" if args.custom else "backend/providers")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{name}_provider.py"

    if target_file.exists():
        print(f"Error: {target_file} already exists", file=sys.stderr)
        sys.exit(1)

    target_file.write_text(content, encoding="utf-8")
    print(f"Created: {target_file}")
    print()
    print("Next steps:")
    print(f"  1. Edit {target_file} to implement data fetching")
    print("  2. Add config entry in config/data_sources.yaml:")
    print(f"     {data_types[0]}_providers:")
    print(f"       {name}:")
    print("         enabled: true")
    print(f"         priority: {args.priority}")
    print("  3. Restart the application")


if __name__ == "__main__":
    main()
