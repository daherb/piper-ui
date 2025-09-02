import wave
from piper import PiperVoice, SynthesisConfig
import flask
from flask import Flask, Response, request, send_file
from jinja2 import Environment, DictLoader, select_autoescape
from glob import glob
from pathlib import Path
import json
import io
import os
import stable_whisper

if 'PIPER_VOICE_PATH' in os.environ:
    VOICE_PATH=os.environ['PIPER_VOICE_PATH']
else:
    VOICE_PATH="/usr/share/piper-voices"

page_dict = {
    'html' :
    '''
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="ui.css">
    <script src="speak.js"></script>
</head>
<body onload="update_speed()">
<h1>Piper UI</h1>
<video preload=none id="player" width="100%" height="100px">
    <source src="piper.wav" type="audio/wave">
    <track default kind="captions" srclang="en"
    src="piper.vtt" />
    Your browser does not support the audio element.
</video>
<br>
<label for="voices">Voices:</label>
<select name="voices" id="voices">
{% for voice in voices %}
    <option value="{{ voice.filename }}" >{{ voice.name }}</option>
{% endfor %}
</select>
<label for="speed">Speed:</label>
<input type="range"  id="speed" name="speed" min="0.25" max="4" value="1.0" step="0.05" oninput="update_speed()"/></input>
<output for="speed" id="speed_output"></output>
<input type="button" value="Speak!" onclick="speak()"></input>
<br>
<br>
<textarea id="text">
</textarea>
</body>
</html>
    ''',
    'css':
    '''
* {
    font-family: courier;
    color: white;
    background-color: black;
}
body {
    height: 100%;
}
textarea {
    width:  calc(100vw - 80px);      /* calc and viewport to the rescue */
    height: calc(100vh - 280px);
    padding: 12px 20px;
    resize: none;
}
input[type=button] {
    margin-top: 20px;
    margin-left: 20px;
    font-size: 26px;
}
label, select {
    font-size: 26px;
}
::cue {
    font-size: 26px;
}
    ''',
    'js':
    '''
function speak() {
    player.removeAttribute("controls","");
    voiceVal = voices.value;
    textVal = text.value;
    speedVal = Number(speed.value);
    const request = new Request("/speak", {
      method: "POST",
      body: JSON.stringify({'filename': voiceVal, 'text': textVal, 'speed': speedVal}),
});
    fetch(request)
    .then((response) => {
      if (response.ok) {
        player.load();
        player.setAttribute("controls","")
      }
    });
}

function update_speed() {
    speed.title=speed.value + "x";
    speed_output.value=speed.title;
}
    '''
    }

# Jinja environment
env = Environment(
    loader = DictLoader(page_dict),
    autoescape=select_autoescape()
)

app = Flask(__name__)

@app.route("/ui.css")
def css():
    template = env.get_template("css")
    return Response(template.render(), mimetype='text/css')

@app.route("/speak.js")
def js():
    template = env.get_template("js")
    return Response(template.render(), mimetype='text/javascript')

@app.route("/piper.wav")
def wav():
    if Path("piper.wav").exists():
        with open("piper.wav", "rb") as wav_file:
            return send_file(
                io.BytesIO(wav_file.read()),
                mimetype='media/wave'
                #as_attachment=True,
                #download_name='%s.jpg' % pid
            )
    else:
        return Response(status=404)
@app.route("/piper.vtt")
def vttv():
    if Path("piper.wav").exists():
        with open("piper.vtt", "rb") as wav_file:
            return send_file(
                io.BytesIO(wav_file.read()),
                mimetype='text/vtt'
            )
    else:
        return Response(status=404)

@app.route("/")
def root():
    template = env.get_template("html")
    voices = [{'filename': f , 'name': Path(f).stem} for f in glob(VOICE_PATH + "/**/*.onnx", recursive=True)]
    return template.render(voices = voices)

@app.route("/speak",methods=['POST'])
def speak():
    data = json.loads(request.data)
    voice = PiperVoice.load(data['filename'])
    print(data)
    syn_config = SynthesisConfig(
        volume=1,  # half as loud
        length_scale=1.0/data['speed'],  # twice as slow
        noise_scale=1.0,  # more audio variation
        noise_w_scale=1.0,  # more speaking variation
        normalize_audio=False, # use raw audio from voice
    )
    paragraphs = data['text'].split('\n\n')
    first = True
    with wave.open("piper.wav", "wb") as wav_file:
        print("generate")
        for paragraph in paragraphs:
            for chunk in voice.synthesize(paragraph, syn_config=syn_config):
                if first:
                    first = False
                    wav_file.setframerate(chunk.sample_rate)
                    wav_file.setsampwidth(chunk.sample_width)
                    wav_file.setnchannels(chunk.sample_channels)
                wav_file.writeframes(chunk.audio_int16_bytes)
            wav_file.writeframes(bytearray(int((voice.config.sample_rate * chunk.sample_width * chunk.sample_channels)/data['speed'])))
    print("transcribe")
    model = stable_whisper.load_model('base')
#    result = model.transcribe('piper.wav')
    result = model.align('piper.wav',data['text'],language='en')
    result.to_srt_vtt('piper.vtt')
    print("done")
    return Response(status=200)

app.run(debug=True)
