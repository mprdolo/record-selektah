"""Create a desktop shortcut for Public Diplomacy Records (Windows)."""
import os
import sys
import subprocess
import tempfile

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SHORTCUT_NAME = "Public Diplomacy Records.lnk"
OLD_SHORTCUT_NAME = "Record Selektah.lnk"  # pre-rebrand name
TARGET = os.path.join(APP_DIR, "start.pyw")
ICON = os.path.join(APP_DIR, "public_diplomacy_records.ico")


def get_desktop():
    """Return the actual Desktop path, handling OneDrive redirection."""
    # Try the Windows Shell folder registry (most reliable)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        desktop, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        # Expand environment variables like %USERPROFILE%
        desktop = os.path.expandvars(desktop)
        if os.path.isdir(desktop):
            return desktop
    except Exception:
        pass

    # Fallbacks
    for candidate in [
        os.path.join(os.environ["USERPROFILE"], "OneDrive", "Desktop"),
        os.path.join(os.environ["USERPROFILE"], "Desktop"),
    ]:
        if os.path.isdir(candidate):
            return candidate

    return os.path.join(os.environ["USERPROFILE"], "Desktop")


def create_shortcut():
    desktop = get_desktop()
    shortcut_path = os.path.join(desktop, SHORTCUT_NAME)

    # Find pythonw.exe next to the current python.exe
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = "pythonw.exe"

    # Use a temporary VBScript to create the shortcut (no extra dependencies)
    vbs = tempfile.NamedTemporaryFile(mode="w", suffix=".vbs", delete=False)
    try:
        vbs.write(
            'Set ws = WScript.CreateObject("WScript.Shell")\n'
            f'Set sc = ws.CreateShortcut("{shortcut_path}")\n'
            f'sc.TargetPath = "{pythonw}"\n'
            f'sc.Arguments = """{TARGET}"""\n'
            f'sc.WorkingDirectory = "{APP_DIR}"\n'
            f'sc.IconLocation = "{ICON},0"\n'
            f'sc.Description = "Launch Public Diplomacy Records"\n'
            "sc.Save\n"
        )
        vbs.close()
        subprocess.run(["cscript", "//NoLogo", vbs.name], check=True)
    finally:
        os.unlink(vbs.name)

    print(f"Desktop shortcut created: {shortcut_path}")

    # Remove the old "Record Selektah" shortcut so there aren't two.
    old_path = os.path.join(desktop, OLD_SHORTCUT_NAME)
    if os.path.exists(old_path):
        try:
            os.remove(old_path)
            print(f"Removed old shortcut: {old_path}")
        except OSError:
            print(f"Couldn't remove old shortcut, delete it by hand: {old_path}")


if __name__ == "__main__":
    if sys.platform != "win32":
        print("This installer is for Windows only.")
        sys.exit(1)

    if not os.path.exists(TARGET):
        print(f"Error: {TARGET} not found. Run from the record-selektah directory.")
        sys.exit(1)

    try:
        create_shortcut()
        print("Done! Double-click 'Public Diplomacy Records' on your desktop to launch.")
    except Exception as e:
        print(f"Error creating shortcut: {e}")
        sys.exit(1)
