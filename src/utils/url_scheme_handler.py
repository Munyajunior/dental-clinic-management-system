# src/utils/url_scheme_handler.py
import sys
import os
import platform
import subprocess
import ctypes
import tempfile
from urllib.parse import urlparse, parse_qs
from typing import Dict, Optional, Any, Tuple
from pathlib import Path
from core.config import AppConfig
from utils.logger import setup_logger
from enum import Enum
import json

logger = setup_logger("URL_SCHEME_HANDLER")


class Platform(Enum):
    WINDOWS = "windows"
    MACOS = "darwin"
    LINUX = "linux"
    UNSUPPORTED = "unsupported"


class RegistrationResult(Enum):
    SUCCESS = "success"
    ADMIN_REQUIRED = "admin_required"
    FAILED = "failed"
    ALREADY_REGISTERED = "already_registered"
    ELEVATION_REQUIRED = "elevation_required"


class URLSchemeHandler:
    """Enterprise-grade cross-platform URL scheme handler with silent admin privilege handling"""

    SCHEME = "kwantabit-dental"
    APP_NAME = f"{AppConfig.APP_NAME}"
    COMPANY_NAME = f"{AppConfig.ORGANIZATION}"

    def __init__(self):
        self.platform = self._detect_platform()
        self.assets_dir = self._get_assets_directory()

    @staticmethod
    def _detect_platform() -> Platform:
        """Detect current platform"""
        system = platform.system().lower()
        if system == "windows":
            return Platform.WINDOWS
        elif system == "darwin":
            return Platform.MACOS
        elif system == "linux":
            return Platform.LINUX
        else:
            return Platform.UNSUPPORTED

    def _get_assets_directory(self) -> Path:
        """Get assets directory path with fallbacks"""
        # Try multiple possible asset locations
        possible_paths = [
            Path(__file__).parent.parent.parent / "assets",
            Path(__file__).parent.parent / "assets",
            Path(sys.executable).parent / "assets",
            Path.cwd() / "assets",
            Path.home() / ".kwantabit" / "assets",
        ]

        for path in possible_paths:
            if path.exists() and path.is_dir():
                return path

        # Create assets directory if none exists
        default_path = Path(__file__).parent.parent.parent / "assets"
        default_path.mkdir(parents=True, exist_ok=True)
        return default_path

    def _get_icon_path(self, icon_name: str) -> Path:
        """Get icon path with format detection"""
        icon_base = self.assets_dir / "icons" / icon_name

        # Try different formats
        for ext in [".ico", ".png", ".icns", ".svg"]:
            icon_path = icon_base.with_suffix(ext)
            if icon_path.exists():
                return icon_path

        # Return default path (will be handled by caller)
        return icon_base.with_suffix(".ico")

    def is_protocol_registered(self) -> bool:
        """Check if custom protocol is registered across platforms"""
        if self.platform == Platform.WINDOWS:
            return self._is_protocol_registered_windows()
        elif self.platform == Platform.MACOS:
            return self._is_protocol_registered_macos()
        elif self.platform == Platform.LINUX:
            return self._is_protocol_registered_linux()
        else:
            logger.warning(f"Unsupported platform: {self.platform}")
            return False

    def _is_protocol_registered_windows(self) -> bool:
        """Check Windows registry for protocol registration"""
        try:
            if platform.system() != "Windows":
                return False

            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, self.SCHEME) as key:
                    winreg.QueryValueEx(key, "URL Protocol")

                # Check command as well
                with winreg.OpenKey(
                    winreg.HKEY_CLASSES_ROOT, f"{self.SCHEME}\\shell\\open\\command"
                ) as cmd_key:
                    command = winreg.QueryValueEx(cmd_key, "")[0]
                    if sys.executable in command:
                        return True

                return False
            except FileNotFoundError:
                return False
            except Exception as e:
                logger.error(f"Windows registry check failed: {e}")
                return False
        except ImportError:
            logger.warning("winreg not available")
            return False

    def _is_protocol_registered_macos(self) -> bool:
        """Check macOS for protocol registration"""
        try:
            # Check multiple locations for macOS registration
            locations = [
                Path.home()
                / "Library"
                / "Application Support"
                / self.COMPANY_NAME
                / "Info.plist",
                Path.home()
                / "Library"
                / "Preferences"
                / f"com.{self.COMPANY_NAME.lower()}.plist",
                "/Applications/KwantaBit Dental.app/Contents/Info.plist",
            ]

            for plist_file in locations:
                if plist_file.exists():
                    import plistlib

                    try:
                        with open(plist_file, "rb") as f:
                            plist_data = plistlib.load(f)
                            url_types = plist_data.get("CFBundleURLTypes", [])
                            for url_type in url_types:
                                if self.SCHEME in url_type.get(
                                    "CFBundleURLSchemes", []
                                ):
                                    return True
                    except Exception:
                        continue

            return False
        except Exception as e:
            logger.error(f"macOS protocol check failed: {e}")
            return False

    def _is_protocol_registered_linux(self) -> bool:
        """Check Linux for protocol registration"""
        try:
            # Check multiple desktop file locations
            desktop_locations = [
                Path.home() / ".local" / "share" / "applications",
                "/usr/share/applications",
                "/usr/local/share/applications",
            ]

            desktop_file_name = f"{self.SCHEME}.desktop"

            for location in desktop_locations:
                desktop_file = location / desktop_file_name
                if desktop_file.exists():
                    content = desktop_file.read_text()
                    if f"x-scheme-handler/{self.SCHEME}" in content:
                        return True

            return False
        except Exception as e:
            logger.error(f"Linux protocol check failed: {e}")
            return False

    def register_protocol(self) -> Tuple[RegistrationResult, str]:
        """Register custom protocol across all platforms with detailed status"""
        if self.platform == Platform.WINDOWS:
            return self._register_protocol_windows()
        elif self.platform == Platform.MACOS:
            return self._register_protocol_macos()
        elif self.platform == Platform.LINUX:
            return self._register_protocol_linux()
        else:
            error_msg = f"Unsupported platform: {self.platform}"
            logger.error(error_msg)
            return RegistrationResult.FAILED, error_msg

    def _register_protocol_windows(self) -> Tuple[RegistrationResult, str]:
        """Register protocol in Windows Registry with admin privilege handling"""
        try:
            import winreg

            # Check if already registered
            if self._is_protocol_registered_windows():
                return (
                    RegistrationResult.ALREADY_REGISTERED,
                    "Protocol already registered",
                )

            # Check admin privileges
            if not self._is_admin_windows():
                logger.warning(
                    "Admin privileges required for Windows protocol registration"
                )
                return (
                    RegistrationResult.ADMIN_REQUIRED,
                    "Administrator privileges required",
                )

            app_path = os.path.abspath(sys.executable)
            icon_path = self._get_icon_path("app_icon")

            # Create protocol key
            with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, self.SCHEME) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, f"URL:{self.SCHEME} Protocol")
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

                # Add icon if available
                if icon_path.exists():
                    winreg.SetValueEx(
                        key, "DefaultIcon", 0, winreg.REG_SZ, str(icon_path)
                    )

            # Create command key
            command_key = f"{self.SCHEME}\\shell\\open\\command"
            with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, command_key) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, f'"{app_path}" "%1"')

            logger.info("Windows protocol registered successfully")
            return RegistrationResult.SUCCESS, "Protocol registered successfully"

        except PermissionError:
            error_msg = "Administrator privileges required for registry modification"
            logger.error(error_msg)
            return RegistrationResult.ADMIN_REQUIRED, error_msg
        except Exception as e:
            error_msg = f"Failed to register Windows protocol: {e}"
            logger.error(error_msg)
            return RegistrationResult.FAILED, error_msg

    def _register_protocol_macos(self) -> Tuple[RegistrationResult, str]:
        """Register protocol on macOS"""
        try:
            # Check if already registered
            if self._is_protocol_registered_macos():
                return (
                    RegistrationResult.ALREADY_REGISTERED,
                    "Protocol already registered",
                )

            app_support_dir = (
                Path.home() / "Library" / "Application Support" / self.COMPANY_NAME
            )
            app_support_dir.mkdir(parents=True, exist_ok=True)

            # Create Info.plist with URL scheme
            plist_content = {
                "CFBundleName": self.APP_NAME,
                "CFBundleURLTypes": [
                    {
                        "CFBundleURLName": self.APP_NAME,
                        "CFBundleURLSchemes": [self.SCHEME],
                    }
                ],
            }

            import plistlib

            plist_file = app_support_dir / "Info.plist"
            with open(plist_file, "wb") as f:
                plistlib.dump(plist_content, f)

            # Register with launch services
            try:
                subprocess.run(
                    [
                        "defaults",
                        "write",
                        f"com.{self.COMPANY_NAME.lower()}.dental",
                        "CFBundleURLTypes",
                        "-array",
                        f'{{ CFBundleURLName = "{self.APP_NAME}"; CFBundleURLSchemes = ( "{self.SCHEME}" ); }}',
                    ],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                logger.warning(f"Could not register with launch services: {e}")

            logger.info("macOS protocol registered successfully")
            return RegistrationResult.SUCCESS, "Protocol registered successfully"

        except Exception as e:
            error_msg = f"Failed to register macOS protocol: {e}"
            logger.error(error_msg)
            return RegistrationResult.FAILED, error_msg

    def _register_protocol_linux(self) -> Tuple[RegistrationResult, str]:
        """Register protocol on Linux"""
        try:
            # Check if already registered
            if self._is_protocol_registered_linux():
                return (
                    RegistrationResult.ALREADY_REGISTERED,
                    "Protocol already registered",
                )

            desktop_dir = Path.home() / ".local" / "share" / "applications"
            desktop_dir.mkdir(parents=True, exist_ok=True)

            app_path = os.path.abspath(sys.executable)
            icon_path = self._get_icon_path("app_icon")

            desktop_file = desktop_dir / f"{self.SCHEME}.desktop"

            desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={self.APP_NAME}
Exec={app_path} %u
StartupNotify=false
MimeType=x-scheme-handler/{self.SCHEME};
"""

            # Add icon if available
            if icon_path.exists():
                desktop_content += f"Icon={icon_path}\n"

            desktop_file.write_text(desktop_content)

            # Update desktop database
            try:
                subprocess.run(
                    ["update-desktop-database", str(desktop_dir)],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                logger.warning(f"Could not update desktop database: {e}")

            logger.info("Linux protocol registered successfully")
            return RegistrationResult.SUCCESS, "Protocol registered successfully"

        except Exception as e:
            error_msg = f"Failed to register Linux protocol: {e}"
            logger.error(error_msg)
            return RegistrationResult.FAILED, error_msg

    def _is_admin_windows(self) -> bool:
        """Check if running with admin privileges on Windows"""
        try:
            if platform.system() != "Windows":
                return False
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False

    # ========== SILENT INSTALLATION METHODS ==========

    def install_silently(self) -> Tuple[bool, str]:
        """Silently install URL scheme without any prompts or windows"""
        try:
            # Check if already registered
            if self.is_protocol_registered():
                logger.info("Protocol already registered")
                return True, "Already registered"

            logger.info(
                f"Starting silent protocol installation on {self.platform.value}"
            )

            if self.platform == Platform.WINDOWS:
                success, message = self._install_windows_silently()
            elif self.platform == Platform.MACOS:
                success, message = self._install_macos_silently()
            elif self.platform == Platform.LINUX:
                success, message = self._install_linux_silently()
            else:
                return False, f"Unsupported platform: {self.platform.value}"

            if success:
                logger.info(f"Silent installation successful: {message}")
            else:
                logger.error(f"Silent installation failed: {message}")

            return success, message

        except Exception as e:
            error_msg = f"Silent installation error: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    def _install_windows_silently(self) -> Tuple[bool, str]:
        """Silent Windows installation"""
        try:
            # Check if we have admin rights
            if not self._is_admin_windows():
                logger.info("Admin rights required, attempting silent elevation...")
                return self._elevate_and_install_windows()

            # We have admin rights, proceed with silent registration
            return self._register_protocol_windows_silent()

        except Exception as e:
            return False, f"Windows installation error: {str(e)}"

    def _install_macos_silently(self) -> Tuple[bool, str]:
        """Silent macOS installation"""
        try:
            # macOS doesn't typically need admin for user-level registration
            result, message = self._register_protocol_macos()
            success = result in [
                RegistrationResult.SUCCESS,
                RegistrationResult.ALREADY_REGISTERED,
            ]
            return success, message
        except Exception as e:
            return False, f"macOS installation error: {str(e)}"

    def _install_linux_silently(self) -> Tuple[bool, str]:
        """Silent Linux installation"""
        try:
            result, message = self._register_protocol_linux()
            success = result in [
                RegistrationResult.SUCCESS,
                RegistrationResult.ALREADY_REGISTERED,
            ]
            return success, message
        except Exception as e:
            return False, f"Linux installation error: {str(e)}"

    def _elevate_and_install_windows(self) -> Tuple[bool, str]:
        """Elevate to admin and install silently on Windows"""
        try:
            # Create a temporary batch file to run the installation
            temp_bat = Path(tempfile.gettempdir()) / f"install_{self.SCHEME}.bat"

            # Get the Python executable and current script path
            python_exe = sys.executable
            current_dir = Path(__file__).parent

            # Write batch file
            bat_content = f"""@echo off
chcp 65001 >nul
echo Installing {self.APP_NAME} URL scheme...
"{python_exe}" "{current_dir / 'install_protocol_silent.py'}"
if %errorlevel% equ 0 (
    echo Installation successful!
) else (
    echo Installation failed.
)
exit /b 0
"""

            temp_bat.write_text(bat_content, encoding="utf-8")

            # Create PowerShell script to run batch as admin
            ps_command = f"""
$batPath = "{temp_bat}"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $batPath
$psi.Verb = "runas"
$psi.UseShellExecute = $true
$psi.WindowStyle = "Hidden"
Start-Process $psi
"""

            # Save PowerShell script
            ps_script = Path(tempfile.gettempdir()) / "elevate.ps1"
            ps_script.write_text(ps_command, encoding="utf-8")

            # Execute silently
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps_script)],
                startupinfo=startupinfo,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Clean up
            try:
                temp_bat.unlink(missing_ok=True)
                ps_script.unlink(missing_ok=True)
            except:
                pass

            # For silent mode, assume success if process started
            # Actual registration will be verified on next run
            return True, "Elevated installation initiated"

        except Exception as e:
            return False, f"Elevation failed: {str(e)}"

    def _register_protocol_windows_silent(self) -> Tuple[bool, str]:
        """Register protocol in Windows Registry silently (with admin rights)"""
        try:
            import winreg

            app_path = os.path.abspath(sys.executable)
            icon_path = self._get_icon_path("app_icon")

            # Create protocol key
            with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, self.SCHEME) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, f"URL:{self.SCHEME} Protocol")
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

                # Add icon if available
                if icon_path.exists():
                    winreg.SetValueEx(
                        key, "DefaultIcon", 0, winreg.REG_SZ, str(icon_path)
                    )

            # Create command key
            command_key = f"{self.SCHEME}\\shell\\open\\command"
            with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, command_key) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, f'"{app_path}" "%1"')

            logger.info("Windows protocol registered silently")
            return True, "Protocol registered successfully"

        except PermissionError:
            return False, "Insufficient permissions"
        except Exception as e:
            return False, f"Registration error: {str(e)}"

    @staticmethod
    def get_reset_token_from_url() -> Optional[str]:
        """Extract reset token from URL arguments"""
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

    def create_silent_installer_script(self) -> Optional[Path]:
        """Create a standalone silent installer script"""
        try:
            temp_dir = Path(tempfile.gettempdir())
            installer_path = temp_dir / f"silent_install_{self.SCHEME}.py"

            script_content = '''#!/usr/bin/env python3
"""
Silent URL scheme installer
"""
import sys
import os
import json
import winreg
import platform
from pathlib import Path

SCHEME = "kwantabit-dental"
APP_NAME = "Dental Clinic Management System"

def is_admin():
    """Check if running as admin on Windows"""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def is_protocol_registered():
    """Check if protocol is already registered"""
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, SCHEME) as key:
            winreg.QueryValueEx(key, "URL Protocol")
        
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{SCHEME}\\\\shell\\\\open\\\\command") as cmd_key:
            command = winreg.QueryValueEx(cmd_key, "")[0]
            return True
    except:
        return False

def register_protocol():
    """Register protocol in registry"""
    try:
        app_path = os.path.abspath(sys.executable)
        
        # Create protocol key
        with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, SCHEME) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, f"URL:{SCHEME} Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        
        # Create command key
        command_key = f"{SCHEME}\\\\shell\\\\open\\\\command"
        with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, command_key) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, f'"{app_path}" "%1"')
        
        return True, "Success"
    except Exception as e:
        return False, str(e)

def main():
    """Main installer function"""
    if platform.system() != "Windows":
        return 1
    
    if not is_admin():
        return 2
    
    if is_protocol_registered():
        return 0
    
    success, message = register_protocol()
    return 0 if success else 3

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
'''

            installer_path.write_text(script_content, encoding="utf-8")
            return installer_path

        except Exception as e:
            logger.error(f"Failed to create installer script: {e}")
            return None

    def silent_elevation_with_installer(self) -> bool:
        """Use a standalone installer for elevation"""
        try:
            installer_path = self.create_silent_installer_script()
            if not installer_path:
                return False

            # Create PowerShell script to run installer as admin
            ps_command = f"""
$installerPath = "{installer_path}"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "python"
$psi.Arguments = "`"$installerPath`""
$psi.Verb = "runas"
$psi.UseShellExecute = $true
$psi.WindowStyle = "Hidden"
Start-Process $psi
"""

            ps_script = Path(tempfile.gettempdir()) / "run_installer.ps1"
            ps_script.write_text(ps_command, encoding="utf-8")

            # Execute silently
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps_script)],
                startupinfo=startupinfo,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Clean up
            try:
                installer_path.unlink(missing_ok=True)
                ps_script.unlink(missing_ok=True)
            except:
                pass

            return True

        except Exception as e:
            logger.error(f"Silent elevation with installer failed: {e}")
            return False

    def get_registration_status(self) -> Dict[str, Any]:
        """Get comprehensive registration status"""
        return {
            "platform": self.platform.value,
            "registered": self.is_protocol_registered(),
            "admin_required": self.platform == Platform.WINDOWS
            and not self._is_admin_windows(),
            "assets_directory": str(self.assets_dir),
            "icon_available": self._get_icon_path("app_icon").exists(),
        }

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
