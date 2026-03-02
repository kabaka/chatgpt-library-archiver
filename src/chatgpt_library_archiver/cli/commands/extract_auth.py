"""CLI command for extracting auth credentials from a browser."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ExtractAuthCommand:
    """Command that extracts auth credentials from a Chromium browser."""

    printer: Callable[[str], None]

    def register(self, subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
        parser = subparsers.add_parser(
            "extract-auth",
            help="Extract auth credentials from Edge or Chrome on macOS",
        )
        parser.add_argument(
            "--browser",
            choices=["edge", "chrome"],
            default="edge",
            help="Browser to extract credentials from (default: edge)",
        )
        parser.add_argument(
            "--output",
            default="auth.txt",
            help="Path to write the auth file (default: auth.txt)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print extracted values without writing (sensitive values masked)",
        )
        parser.add_argument(
            "--no-verify",
            action="store_true",
            help="Skip verifying that the token works via a test API call",
        )
        parser.set_defaults(command_handler=self.handle, command="extract-auth")
        return parser

    def handle(self, args: Namespace) -> int | None:
        from chatgpt_library_archiver.browser_extract import (
            BrowserExtractError,
            _mask,
            extract_auth_config,
            write_auth_from_browser,
        )

        browser: str = getattr(args, "browser", "edge")
        output: str = getattr(args, "output", "auth.txt")
        dry_run: bool = getattr(args, "dry_run", False)
        no_verify: bool = getattr(args, "no_verify", False)

        try:
            if dry_run:
                config = extract_auth_config(browser)
                self.printer("\nExtracted auth configuration (dry run):\n")
                _SENSITIVE_KEYS = {"authorization", "cookie"}
                for key, value in config.items():
                    display = _mask(value) if key in _SENSITIVE_KEYS else value
                    self.printer(f"  {key}={display}")
                self.printer(
                    "\nDry run — no file written. Remove --dry-run to save to disk.\n"
                )
            else:
                config = write_auth_from_browser(browser, output)
                self.printer(f"\nCredentials written to {output}.\n")

            if not no_verify:
                self._verify_token(config)

        except BrowserExtractError as exc:
            self.printer(f"\nError: {exc}\n")
            return 1

        return 0

    def _verify_token(self, config: dict[str, str]) -> None:
        """Make a lightweight API call to confirm the token works."""
        from chatgpt_library_archiver.http_client import HttpClient, HttpError
        from chatgpt_library_archiver.incremental_downloader import build_headers

        url = config["url"]
        headers = build_headers(config)

        with HttpClient() as client:
            try:
                data = client.get_json(url, headers=headers)
                items = data.get("items") if isinstance(data, dict) else None
                if isinstance(items, list):
                    self.printer(
                        f"Verification OK — API returned {len(items)} item(s)."
                    )
                else:
                    self.printer(
                        "Verification warning — unexpected API response shape."
                    )
            except HttpError as exc:
                self.printer(
                    f"Verification failed — API returned {exc.status_code}: "
                    f"{exc.reason}. The credentials may be invalid."
                )
