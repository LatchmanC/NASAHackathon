"""Securely save a replacement Gemini API key only on this local machine.

Creates a private .env in this project directory. Never puts secrets into the
web UI or bundled ZIP. Run once before launching run_demo.py.
"""
from getpass import getpass
from pathlib import Path
from dotenv import set_key

TARGET = Path(__file__).resolve().parent / '.env'


def main():
    print('FieldShift local Gemini configuration')
    print('Use a NEW key. A key already shared in a chat should be revoked.')
    key = getpass('Gemini API key (hidden input): ').strip()
    if not key or any(ch.isspace() for ch in key):
        raise SystemExit('No key saved: enter a single-line nonempty key.')
    TARGET.touch(exist_ok=True)
    try:
        TARGET.chmod(0o600)  # Owner access only on Unix-like systems
    except OSError:
        pass
    set_key(str(TARGET), 'GEMINI_API_KEY', key)
    print('Saved locally in .env. Restart run_demo.py to apply it.')


if __name__ == '__main__':
    main()
