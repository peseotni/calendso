"""Command line entry point: ``python -m audiobook_studio``."""

from __future__ import annotations

import argparse


def main() -> None:
    from .config import get_config

    config = get_config()
    parser = argparse.ArgumentParser(description="Audiobook Studio server")
    parser.add_argument("--host", default=config.host)
    parser.add_argument("--port", type=int, default=config.port)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (development)")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "audiobook_studio.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
