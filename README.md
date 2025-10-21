# Piper UI

Simple web-ui for piper, based on flask and jinja

Only intended for local use, it will overwrite the same wave file every time it converts text to speech.

## Installation

On Linux:
```
python -m venv venv
. ./venv/bin/activate
# For CPU install torch as cpu version first
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python piper_ui.py
```

The default voice path is `/usr/share/piper-voices` but can be overwritten using the `PIPER_VOICE_PATH` environment variable.

## Download voices
You can download all voices by cloning https://huggingface.co/rhasspy/piper-voices with LFS:
```
git lfs install
git clone https://huggingface.co/rhasspy/piper-voices
```

Alternatively you can download only idividual voices e.g. just the Swedish voices:

```
git lfs install
git clone https://huggingface.co/rhasspy/piper-voices --sparse
cd piper-voices
git sparse-checkout init
git sparse-checkout set "sv"
```
