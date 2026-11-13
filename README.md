# Language Suite

An app for practising languages with an AI teacher. It runs on your own
computer with free local models, or with a cloud AI service if you prefer.

| Feature | Status |
|---|---|
| Conversation partner (voice) | Ready |
| Job interview rehearsal (voice) | Ready |
| Interpreter simulation (voice) | Ready |
| Vocabulary practice (text or voice) | Ready |
| Dictation (typed) | Ready |
| Dictation (handwritten, photo upload) | Planned |

## How it works

The app has three "sockets". Anything with the right plug fits, so each one
can be local or cloud without changing the features.

| Socket | Job | Local (free) | Cloud |
|---|---|---|---|
| Brain | Chat, questions, feedback | Ollama | Any OpenAI-style API |
| Ear | Speech to text | Whisper on your PC (separate install) | Any OpenAI-style transcription API |
| Mouth | Text to speech | Your browser's built-in voices (default) | Any OpenAI-style speech API |

The app itself contains no models. Models and speech engines are installed
separately, under their own licences.

## Which setup should I choose?

| | Local (Ollama) | Cloud service |
|---|---|---|
| Cost | Free | Pay per use (usually) |
| Privacy | Everything stays on your PC | Text is sent to the provider |
| Needs | A GPU with about 8 GB VRAM, or patience on CPU | An account and an API key |
| Setup effort | Install Ollama and download a model (several GB) | Paste three settings |

## Installation (Windows 11)

### 1. Install the basics

1. **Python 3.11 or newer** from <https://www.python.org/downloads/>.
   In the installer, tick **"Add python.exe to PATH"**.
2. **Git** from <https://git-scm.com/download/win> (default options are fine).

Check both in a new PowerShell window:

```powershell
python --version
git --version
```

### 2. Get the code

```powershell
git clone <repository URL>
cd language-suite
```

### 3. Create a private Python environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

You need to run `.venv\Scripts\Activate.ps1` again each time you open a new
PowerShell window.

For the features that use the microphone, also install the local speech
recognition (see "Microphone" below for details):

```powershell
pip install -r requirements-voice.txt
```

### 4. Create your settings file

```powershell
copy .env.example .env
```

`.env` is your private settings file. Git ignores it, so it is never shared.

### 5a. Local setup: Ollama

1. Install Ollama from <https://ollama.com/download>. It starts automatically
   and runs in the background.
2. Download a model (about 10 GB, one time):

   ```powershell
   ollama pull gemma4:e4b
   ```

3. Test it: `ollama run gemma4:e4b "Say hello in Spanish"`

The default `.env` already points at Ollama, so there is nothing to edit.

Choosing a model by graphics memory (VRAM). These are starting points; check
<https://ollama.com/library> for current models and sizes.

| Your GPU memory | Suggested starting model |
|---|---|
| No GPU / under 6 GB | `gemma4:e2b` (slower, simpler feedback), or use a cloud service |
| 8 GB | `gemma4:e4b` |
| 12 GB or more | `gemma4:12b` |

To use a different model, pull it with `ollama pull <name>` and set
`LLM_MODEL=<name>` in `.env`.

### 5b. Cloud setup: any OpenAI-style service

Skip Ollama. Open `.env` in a text editor and set three values from your
provider's documentation:

```ini
LLM_BASE_URL=<the provider's API address, usually ending in /v1>
LLM_MODEL=<a model name from the provider>
LLM_API_KEY=<your own key>
```

Keep the key private. Anyone who has it can spend your credit.

### 6. Start the app

```powershell
python -m uvicorn app.main:app --port 8000
```

Open <http://localhost:8000> in your browser. Press `Ctrl+C` in PowerShell to
stop the app. It only listens on your own computer, not on the network.

## Uploading material

The conversation, job interview, vocabulary and dictation features accept a
file, for example a CV, a job description, an article or a word list.

| File type | Supported | Notes |
|---|---|---|
| Text (`.txt`, `.md`, `.csv`) | Yes | |
| PDF | Yes | Must contain selectable text. A scanned PDF has none: upload a photo of the page as an image instead |
| Word `.docx` | Yes | Text and tables are read; pictures, headers and footers are not |
| Word `.doc` (old format) | No | Open it in Word and use Save As to make a `.docx` or PDF |
| Image (`.png`, `.jpg`, `.webp`) | Conversation and interview only | Needs a chat model that can read images |

Files are read in memory on your computer and are not saved. Only the first
8,000 characters of a document are given to the model; the app tells you
when a file was cut.

## Voices (text to speech)

Dictation reads each sentence aloud. There are two ways to get a voice, set
with `TTS_PROVIDER` in `.env`.

| | `browser` (default) | `openai_compatible` |
|---|---|---|
| What speaks | Voices built into your browser and Windows | A speech server, local or cloud |
| Install | Nothing, or add a Windows language pack | A speech server or a cloud account |
| Quality | Depends on the voice; basic to good | Depends on the model; often more natural |
| Privacy | Local for Windows voices (see note) | Local server: stays on your PC. Cloud: text is sent to the provider |

### Browser voices

Use Chrome or Edge. The app lists the voices that match the dictation
language and lets you pick one.

If the app says there is no voice for your language, add it in Windows:
**Settings > Time & language > Language & region > Add a language**, choose
the language, and keep **Text-to-speech** ticked. Then restart the browser.

Privacy note: voices whose names contain "Online", "Natural" or "Google" are
produced on that company's servers, so the sentence is sent there. Voices
without those words run on your PC.

### Speech server

Any server with an OpenAI-style `/audio/speech` endpoint works: a cloud
speech API, or a local speech server that you install separately under its
own licence. Set these in `.env`:

```ini
TTS_PROVIDER=openai_compatible
TTS_BASE_URL=<the server's API address, usually ending in /v1>
TTS_MODEL=<speech model name>
TTS_VOICE=<voice name, if the server needs one>
TTS_API_KEY=<your own key, or empty for a local server>
```

## Microphone (speech to text)

Conversation, job interview, interpreter and the voice mode of vocabulary
record you with the microphone and turn the recording into text. Set the
method with `STT_PROVIDER` in `.env`.

| | `faster_whisper` (default) | `openai_compatible` |
|---|---|---|
| What listens | The Whisper model, running on your PC | A transcription server, local or cloud |
| Install | `pip install -r requirements-voice.txt` | A server or a cloud account |
| Privacy | Recordings stay on your PC | Cloud: recordings are sent to the provider |
| Speed | A few seconds per turn on a modern CPU | Depends on the service |

### Local Whisper

1. Install it once, inside the activated environment:

   ```powershell
   pip install -r requirements-voice.txt
   ```

2. The first time you use the microphone, the model (about 0.5 GB for
   `small`) is downloaded automatically. That first turn is slow; later ones
   are not.

Optional settings in `.env`:

| Setting | Default | Meaning |
|---|---|---|
| `STT_MODEL` | `small` | `base` is faster and less accurate; `medium` is slower and more accurate |
| `STT_DEVICE` | `cpu` | `cuda` uses the NVIDIA GPU, but needs extra NVIDIA libraries and shares graphics memory with the chat model. `cpu` is the safe choice |

### Transcription server

```ini
STT_PROVIDER=openai_compatible
STT_BASE_URL=<the server's API address, usually ending in /v1>
STT_MODEL=<transcription model name>
STT_API_KEY=<your own key, or empty for a local server>
```

### Using the microphone

- Open the app at `http://localhost:8000` (not through another address):
  browsers only allow the microphone on `localhost` or secure sites.
- The first time, the browser asks for permission to use the microphone.
- Press the microphone button, speak, and press it again when you finish.

Good to know: speech recognition writes down what it believes you meant. It
cannot judge pronunciation, and it sometimes tidies up small slips, so the
feedback is about words, grammar and content.

## Troubleshooting

| Message | What to do |
|---|---|
| "Could not reach the model server" | Start Ollama (search "Ollama" in the Start menu), or check `LLM_BASE_URL` |
| "Model ... was not found" | Run `ollama pull <model>`, or fix `LLM_MODEL` in `.env` |
| "The model took too long to answer" | The first request loads the model and is slow. Retry, or raise `LLM_TIMEOUT` |
| "rejected the API key" | Check `LLM_API_KEY` in `.env` |
| "did not return a usable word list" or "dictation text" | Retry. If it repeats, try a larger model |
| "This browser has no voice for ..." | Add the language in Windows (see Voices), or use a speech server |
| "Local speech recognition is not installed" | Run `pip install -r requirements-voice.txt` in the activated environment |
| "Could not load the Whisper model" | The first use needs internet for the download. Check `STT_MODEL` |
| "The microphone is blocked or missing" | Click the padlock or microphone icon in the address bar and allow the microphone. Check Windows Settings > Privacy & security > Microphone |
| "No words were recognised" | Speak closer to the microphone, or check that Windows uses the right input device |
| The partner's voice is silent | Check the PC volume, pick another voice in the Voice list, or try Edge |
| Dictation is silent | Check the PC volume, pick another voice in the Voice list, or try Edge |

## For developers

### Project layout

```
app/
  main.py            entry point, serves the API and the browser UI
  config.py          settings from environment variables / .env
  providers/
    base.py          the three interfaces: ChatProvider, SpeechToText, TextToSpeech
    openai_compatible.py   brain, ear and mouth for Ollama and OpenAI-style APIs
    faster_whisper.py      ear: local Whisper (optional install)
    factory.py       picks the provider named in the settings
  features/
    talk.py          Features 1 and 2 (conversation, job interview)
    interpreter.py   Feature 3
    vocabulary.py    Feature 4
    dictation.py     Feature 5
    speech.py        shared speech endpoints (transcribe, synthesize)
    materials.py     reads text from uploaded PDF and Word files
  textutils.py       shared text helpers (answer matching, dictation marking)
  static/            browser UI (plain HTML, CSS, JavaScript)
tests/               run without any model, using a fake provider
data/                local user data, ignored by git
```

Features must use the interfaces in `providers/base.py`, never a vendor
directly. To add a provider, implement the interface in a new file and
register it in `providers/factory.py`.

### Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

### Security rules for contributors

1. **Never commit secrets.** Keys live only in `.env`, which is ignored by git.
   `.env.example` contains placeholders only.
2. **Never commit user data.** Recordings, uploads and session logs belong in
   `data/`, which is ignored by git.
3. **Keys stay on the server side.** Nothing in `app/static/` may contain or
   receive a key.
4. **Turn on the secret scanner** once after cloning. It blocks commits that
   contain something that looks like a key:

   ```powershell
   pre-commit install
   ```

5. If a key is ever committed by mistake, deleting it in a later commit is not
   enough, because git keeps history. Revoke the key at the provider and
   create a new one.
