# src/utils/url_scheme_handler.py
import sys
import os
import platform
import subprocess
from urllib.parse import urlparse, parse_qs
from typing import Dict, Optional, Any
from pathlib import Path
import logging

logger = logging.getLogger("URL_SCHEME_HANDLER")


class URLSchemeHandler:
    """Enterprise-grade cross-platform URL scheme handler"""

    SCHEME = "kwantabit-dental"

    @staticmethod
    def get_reset_token_from_url() -> Optional[str]:
        """Extract reset token from URL arguments - enterprise version"""
        try:
            if len(sys.argv) > 1:
                url = sys.argv[1]
                logger.info(f"Processing URL: {url}")

                parsed = urlparse(url)
                if parsed.scheme == URLSchemeHandler.SCHEME:
                    query_params = parse_qs(parsed.query)

                    # Handle different URL paths
                    if parsed.path == "/reset-password":
                        return query_params.get("token", [None])[0]
                    elif parsed.path == "/login":
                        return query_params.get("tenant", [None])[0]
                    elif parsed.path == "/verify-email":
                        return query_params.get("token", [None])[0]

            return None
        except Exception as e:
            logger.error(f"Error extracting token from URL: {e}")
            return None

    @staticmethod
    def parse_deep_link(url: str) -> Dict[str, Any]:
        """Parse deep link URL and return structured data"""
        try:
            parsed = urlparse(url)
            if parsed.scheme != URLSchemeHandler.SCHEME:
                return {}

            query_params = parse_qs(parsed.query)
            flattened_params = {k: v[0] if v else None for k, v in query_params.items()}

            return {
                "action": parsed.path.lstrip("/"),
                "params": flattened_params,
                "original_url": url,
            }
        except Exception as e:
            logger.error(f"Error parsing deep link: {e}")
            return {}

    @staticmethod
    def is_protocol_registered() -> bool:
        """Check if custom protocol is registered across platforms"""
        system = platform.system().lower()

        if system == "windows":
            return URLSchemeHandler._is_protocol_registered_windows()
        elif system == "darwin":  # macOS
            return URLSchemeHandler._is_protocol_registered_macos()
        elif system == "linux":
            return URLSchemeHandler._is_protocol_registered_linux()
        else:
            logger.warning(f"Unsupported platform: {system}")
            return False

    @staticmethod
    def _is_protocol_registered_windows() -> bool:
        """Check Windows registry for protocol registration"""
        try:
            if platform.system() != "Windows":
                return False

            import winreg

            try:
                with winreg.OpenKey(
                    winreg.HKEY_CLASSES_ROOT, URLSchemeHandler.SCHEME
                ) as key:
                    winreg.QueryValueEx(key, "URL Protocol")
                return True
            except FileNotFoundError:
                return False
            except Exception as e:
                logger.error(f"Windows registry check failed: {e}")
                return False
        except ImportError:
            logger.warning("winreg not available")
            return False

    @staticmethod
    def _is_protocol_registered_macos() -> bool:
        """Check macOS for protocol registration"""
        try:
            # Check Info.plist for registered URL schemes
            app_support_dir = (
                Path.home() / "Library" / "Application Support" / "KwantaBit Dental"
            )
            plist_file = app_support_dir / "Info.plist"

            if plist_file.exists():
                import plistlib

                with open(plist_file, "rb") as f:
                    plist_data = plistlib.load(f)
                    url_types = plist_data.get("CFBundleURLTypes", [])
                    for url_type in url_types:
                        if URLSchemeHandler.SCHEME in url_type.get(
                            "CFBundleURLSchemes", []
                        ):
                            return True
            return False
        except Exception as e:
            logger.error(f"macOS protocol check failed: {e}")
            return False

    @staticmethod
    def _is_protocol_registered_linux() -> bool:
        """Check Linux for protocol registration"""
        try:
            # Check desktop file for MIME types
            desktop_file = (
                Path.home()
                / ".local"
                / "share"
                / "applications"
                / "kwantabit-dental.desktop"
            )
            if desktop_file.exists():
                content = desktop_file.read_text()
                return f"x-scheme-handler/{URLSchemeHandler.SCHEME}" in content
            return False
        except Exception as e:
            logger.error(f"Linux protocol check failed: {e}")
            return False

    @staticmethod
    def register_protocol() -> bool:
        """Register custom protocol across all platforms"""
        system = platform.system().lower()

        if system == "windows":
            return URLSchemeHandler._register_protocol_windows()
        elif system == "darwin":
            return URLSchemeHandler._register_protocol_macos()
        elif system == "linux":
            return URLSchemeHandler._register_protocol_linux()
        else:
            logger.error(f"Unsupported platform for protocol registration: {system}")
            return False

    @staticmethod
    def _register_protocol_windows() -> bool:
        """Register protocol in Windows Registry"""
        try:
            import winreg
            import ctypes

            # Check if running as admin
            if not ctypes.windll.shell32.IsUserAnAdmin():
                logger.warning(
                    "Admin privileges required for Windows protocol registration"
                )
                return False

            app_path = os.path.abspath(sys.executable)

            # Create protocol key
            with winreg.CreateKey(
                winreg.HKEY_CLASSES_ROOT, URLSchemeHandler.SCHEME
            ) as key:
                winreg.SetValue(
                    key, "", winreg.REG_SZ, f"URL:{URLSchemeHandler.SCHEME} Protocol"
                )
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

            # Create command key
            command_key = f"{URLSchemeHandler.SCHEME}\\shell\\open\\command"
            with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, command_key) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, f'"{app_path}" "%1"')

            logger.info("Windows protocol registered successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to register Windows protocol: {e}")
            return False

    @staticmethod
    def _register_protocol_macos() -> bool:
        """Register protocol on macOS"""
        try:
            app_support_dir = (
                Path.home() / "Library" / "Application Support" / "KwantaBit Dental"
            )
            app_support_dir.mkdir(parents=True, exist_ok=True)

            # Create Info.plist with URL scheme
            plist_content = {
                "CFBundleURLTypes": [
                    {
                        "CFBundleURLName": "KwantaBit Dental Management",
                        "CFBundleURLSchemes": [URLSchemeHandler.SCHEME],
                    }
                ]
            }

            import plistlib

            plist_file = app_support_dir / "Info.plist"
            with open(plist_file, "wb") as f:
                plistlib.dump(plist_content, f)

            # Register with launch services
            subprocess.run(
                [
                    "defaults",
                    "write",
                    f"com.kwantabit.dental",
                    "CFBundleURLTypes",
                    "-array",
                    f'{{ CFBundleURLName = "KwantaBit Dental"; CFBundleURLSchemes = ( "{URLSchemeHandler.SCHEME}" ); }}',
                ],
                check=True,
            )

            logger.info("macOS protocol registered successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to register macOS protocol: {e}")
            return False

    @staticmethod
    def _register_protocol_linux() -> bool:
        """Register protocol on Linux"""
        try:
            desktop_dir = Path.home() / ".local" / "share" / "applications"
            desktop_dir.mkdir(parents=True, exist_ok=True)

            app_path = os.path.abspath(sys.executable)
            desktop_file = desktop_dir / "kwantabit-dental.desktop"

            desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=KwantaBit Dental Management
Exec={app_path} %u
Icon=kwantabit-dental
StartupNotify=false
MimeType=x-scheme-handler/{URLSchemeHandler.SCHEME};
"""

            desktop_file.write_text(desktop_content)

            # Update desktop database
            subprocess.run(["update-desktop-database", str(desktop_dir)], check=True)

            logger.info("Linux protocol registered successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to register Linux protocol: {e}")
            return False

    @staticmethod
    def create_deep_link(action: str, **params) -> str:
        """Create deep link URL for various actions"""
        base_url = f"{URLSchemeHandler.SCHEME}://{action}"

        if params:
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            return f"{base_url}?{query_string}"

        return base_url

    @staticmethod
    def get_supported_actions() -> Dict[str, str]:
        """Return supported deep link actions"""
        return {
            "login": "Open login screen with pre-filled tenant",
            "reset-password": "Open password reset screen",
            "verify-email": "Verify email address",
            "open-appointment": "Open specific appointment",
            "open-patient": "Open patient record",
        }
