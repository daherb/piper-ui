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
import logging

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
<body onload="load()">
<h1>Piper UI</h1>
<div id="cue"></div>
<audio preload=none id="player" width="100%" height="100px">
    <source id="playerSource" src="piper.wav" type="audio/wave">
    <track id="subtitle" default kind="captions" oncuechange="show_cue()" />
    Your browser does not support the audio element.
</audio>
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
<label for="showSubtitles">Subtitles:</label>
<input type="checkbox" id="showSubtitles" onclick="toggle_subtitles()"></input>
<label for="showKaraoke">Karaoke:</label>
<input type="checkbox" id="showKaraoke" disabled></input>
<input type="button" value="Speak!" onclick="speak()"></input>
<br>
<br>
<div id="text" contentEditable="true" oninput="cleanup_input(['p','br'])">Add text here...</div>
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
div#text {
    border-style: inset;
    width:  calc(100vw - 80px);      /* calc and viewport to the rescue */
    height: calc(100vh - 280px);
    padding: 12px 20px;
    resize: none;
    overflow-y:scroll;
}
div#cue {
    height: 40px;
    width:  calc(100vw - 80px);      /* calc and viewport to the rescue */
    padding: 10px;
    border: 2px;
    overflow: auto;
    resize: both;
}
span.highlight {
    color: green;
}
    ''',
    'js':
    '''
"use strict";
var cue_words = []

// Page load handler
function load() {
    // Sets speed label and tool tip
    update_speed();
    // Add event handler that seems to otherwise not work properly
    player.addEventListener("timeupdate", highlight_word)
    // Check for resize of cue
    const resizeObserver = new ResizeObserver((entries) => resize_cue(entries));
    resizeObserver.observe(cue);
}

// Handles resizing the cue area
function resize_cue(entries) {
    cue.style.fontSize=entries[0].contentBoxSize[0].blockSize + "px";
}
// Matches the state of karaoke with the State of subtitle
function toggle_subtitles() {
    if (showSubtitles.checked) {
        showKaraoke.removeAttribute("disabled");
    }
    else {
        showKaraoke.setAttribute("disabled","true");
        showKaraoke.checked = false;
    } 
}
// Sends the text to the server and loads the result into the player
function speak() {
    player.removeAttribute("controls","");
    // erase current subtitle
    subtitle.src=""
    cue.innerHTML = '&nbsp;';
    const voiceVal = voices.value;
    // If we have paragraphs, get their text content as an array,
    // otherwise get a simple array with just the text content of the text element
    var textVal = [];
    Array.from(text.childNodes).map((node) => {
        textVal.push(node.textContent);
    });
    textVal = textVal.filter((txt) => !/^\\s*$/.test(txt)).map((txt) => txt.replace(/^\\s+/,"").replace(/\\s+$/,""));
    const speedVal = Number(speed.value);
    const languageVal = voices.options[voices.selectedIndex].text.substr(0,2);
    const request = new Request("/speak", {
      method: "POST",
      body: JSON.stringify({'filename': voiceVal, 'text': textVal, 'speed': speedVal, 'language': languageVal}),
});
    fetch(request)
    .then((response) => {
      if (response.ok) {
        player.setAttribute("controls","");
        subtitle.srclang = languageVal;
        subtitle.src = "piper.vtt";
        playerSource.src = "piper.wav";
        player.load();
      }
    });
}

// Updates the speed label and tool tip
function update_speed() {
    speed.title=speed.value + "x";
    speed_output.value=speed.title;
}

// Parse cues and convert into a list of words with start and end time
function parse_cue(cue) {
    const cueFormat = RegExp("(?<startTime><?(?<startHour>\\\\d{2}):(?<startMinute>\\\\d{2}):(?<startSecond>\\\\d{2}.\\\\d{3})>)?(?<word>.+)(?<endTime><(?<endHour>\\\\d{2}):(?<endMinute>\\\\d{2}):(?<endSecond>\\\\d{2}.\\\\d{3})>?)");
    var parsed = []
    var text = cue.text;
    // Add missing start and end tags
    if (!text.startsWith("<")) {
        text = "<00:00:00.000>" + text
    }
    if (!text.endsWith(">")) {
       text = text + "<99:99:99.999>" // This should be enough for pretty much everything
    }
    const parts = text.split(/>\\s+<?/);
    for (var index in parts) {
        const part = parts[index]
        const match = cueFormat.exec(part);
        if (match != null) {
            var start = match.groups.startTime;
            if (typeof(start) == 'undefined') {
                // Copy the end of the previous cue of it exists
                if (parsed.length > 0) {
                    start = parsed[parsed.length -1].end;
                }
                else {
                   start = 0;
                }
            }
            else {
                start = Number.parseInt(match.groups.startHour) * 3600 + Number.parseInt(match.groups.startMinute) * 60 + Number.parseFloat(match.groups.startSecond);
            }
            const word = match.groups.word;
            // Fix the end to the duration of the current file
            var end;
            if (match.groups.endTime == "<99:99:99.999>") {
                end = player.duration;
            }
            else {
                end = Number.parseInt(match.groups.endHour) * 3600 + Number.parseInt(match.groups.endMinute) * 60 + Number.parseFloat(match.groups.endSecond);
            }
            const info = {'start': start, 'word': word, 'end': end}
            parsed.push(info);
        }
    }
    return parsed;
}

// Shows cues when triggered by the player. Updates both the subtitle view and the highlights in the text itself
function show_cue() {
    const cues = event.target.track.activeCues;
    // reset cue words
    cue_words = []
    if (cues.length > 0) { // only clear if we have new items
        cue.innerHTML = '';
    } 
    for (var ct = 0;  ct < cues.length; ct++) {
        if (showSubtitles.checked) {
            cue.append(cues[ct].getCueAsHTML());
        }
        const parsed_cues = parse_cue(cues[ct]);
        cue_words = cue_words.concat(parsed_cues);
        // Remove all timestamps and newlines. Merge multiple spaces
        const highlight_text = cues[ct].text.replaceAll(/\\s*<.+?>\\s*/g," ").replaceAll(/\\n/g," ").replaceAll(/\\s+/g, " ");
        add_highlight(text,highlight_text);
    }
}

// Helper to remove all highlight spans from an element
function remove_highlight() {
    cue.innerHTML = cue.textContent;
}

// Helper add a highlight span to an element surrounding a given text
function add_highlight(element,text) {
    element.innerHTML = element.innerHTML.replace(text,'<span class="highlight">' + text + '</span>');
}

// Karaoke function: highlight a word in the shown subtitle
function highlight_word() {
    if (showKaraoke.checked) {
        const time = player.currentTime;
        remove_highlight();
        if (cue_words.length > 0) {
            if (cue_words[0].start <= time)  { // for some reason it works much better without checking the end time
                add_highlight(cue,cue_words[0].word);
                cue_words.shift()
            }
        }
    }
}

// Cleans up the text by removing all tags that are not listed as acceptable, all attributes and all styles. It also puts all top-level text nodes into paragraph tags
function cleanup_input(acceptable) {
    const acceptableLower = acceptable.map((tag) => tag.toLowerCase());
    // Continue until only paragraphs are left
    while (!Array.from(text.getElementsByTagName("*")).every((t) => acceptableLower.some((a) => t.tagName.toLowerCase() == a))) {
        // Get the first non-p element
        var element = Array.from(text.getElementsByTagName("*")).filter((t) => !(acceptableLower.some((a) => t.tagName.toLowerCase() == a)))[0];
        // replace tag by its content, except for style
        if (element.tagName.toLowerCase() != 'style') {
            element.outerHTML = element.innerHTML;
        }
        else {
            element.remove();
        }
    }
    // Add spaces to the text node
    Array.from(text.childNodes).map((node) => { if (node.nodeType == Node.TEXT_NODE) { node.textContent += ' ' }})
    // Strip attributes (incl styles) and elements without text (except br)
    Array.from(text.getElementsByTagName("*")).map((e) => { Array.from(e.attributes).map((a) => e.removeAttribute(a.name)) ; if (e.tagName.toLowerCase() != 'br' && e.textContent == "") { e.remove() } ; });
    // Normalize tree: merge neighboring text nodes and remove empty elements
    text.normalize();
    // More manual normalization the HTML 
    var tmpHTML = text.innerHTML
      .replaceAll(/&amp;/g,   "&")
      .replaceAll(/&lt;/g,    "<")
      .replaceAll(/&gt;/g,    ">")
      .replaceAll(/&quot;/g,  "\\"")
      .replaceAll(/&apos;/g,  "'")
      .replaceAll(/&nbsp;/g,  " ")
      .replaceAll(/&ndash;/g, "–")
      .replaceAll(/&mdash;/g, "—")
      .replaceAll(/&copy;/g,  "©")
      .replaceAll(/&reg;/g,   "®")
      .replaceAll(/&trade;/g, "™")
      .replaceAll(/&asymp;/g, "≈")
      .replaceAll(/&ne;/g,    "≠")
      .replaceAll(/&pound;/g, "£")
      .replaceAll(/&euro;/g,  "€")
      .replaceAll(/&deg;/g, "°")
      .replaceAll('<br>','\\n')                     // br's by new newlines
      .replaceAll(/\\n\\n/gu,'\\n</p>\\n<p>\\n')    // multiple newlines by paragraph breaks
      .replaceAll(/\\s*\\n+\\s*/gu," ")             // newlines with dangling spaces by a single space
      .replaceAll(/\\s+/gu," ")                     // several spaces by a single space
      .replace(/^\\s*/u,"")                         // initial spaces
    if (!tmpHTML.startsWith("<p>")) { tmpHTML = "<p>" + tmpHTML + "</p>" }    // if we don't have initial p tags add them around the whole content
    text.innerHTML = tmpHTML;
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
            )
    else:
        return Response(status=404)

@app.route("/piper.vtt")
def vtt():
    if Path("piper.vtt").exists():
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
    app.logger.info(json.dumps(data, indent=4))
    voice = PiperVoice.load(data['filename'])
    syn_config = SynthesisConfig(
        volume=1,  
        length_scale=1.0/data['speed'],  # adjust speed
        noise_scale=1.0,  # more audio variation
        noise_w_scale=1.0,  # more speaking variation
        normalize_audio=False, # use raw audio from voice
    )
    paragraphs = data['text']
    first = True
    with wave.open("piper.wav", "wb") as wav_file:
        print("generate")
        empty_samples = 0
        for paragraph in paragraphs:
            for chunk in voice.synthesize(paragraph, syn_config=syn_config):
                if first:
                    first = False
                    wav_file.setframerate(chunk.sample_rate)
                    wav_file.setsampwidth(chunk.sample_width)
                    wav_file.setnchannels(chunk.sample_channels)
                    empty_samples = int((voice.config.sample_rate * chunk.sample_width * chunk.sample_channels*0.5)/data['speed'])
                    while empty_samples % chunk.sample_width != 0:
                        empty_samples += 1
                wav_file.writeframes(chunk.audio_int16_bytes)
            wav_file.writeframes(bytearray(empty_samples))
    print("transcribe")
    model = stable_whisper.load_model('base')
    result = model.align('piper.wav',"\n\n".join(data['text']),language='en')
    result.to_srt_vtt('piper.vtt')
    print("done")
    return Response(status=200)

app.logger.setLevel(logging.INFO)
app.run()
