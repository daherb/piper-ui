# Piper UI

Simple web-ui for piper, based on flask and jinja

Only intended for local use, it will overwrite the same wave file every time it converts text to speech.

## Installation

On Linux:
```
python -m venv venv
. ./venv/bin/activate
pip install -r requirements.txt
python piper_ui.py
```

The default voice path is `/usr/share/piper-voices` but can be overwritten using the `PIPER_VOICE_PATH` environment variable.
