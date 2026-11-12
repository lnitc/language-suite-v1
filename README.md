# Language Suite

An app for practising languages with an AI teacher. It runs on your own
computer with free local models, or with a cloud AI service if you prefer.

| Feature | Status |
|---|---|
| Vocabulary practice (text) | Ready |
| Dictation (typed) | Ready |
| Dictation (handwritten, photo upload) | Planned |
| Conversation partner (voice) | Planned |
| Job interview rehearsal (voice) | Planned |
| Interpreter simulation (voice) | Planned |

## How it works

The app has three "sockets". Anything with the right plug fits, so each one
can be local or cloud without changing the features.

| Socket | Job | Local (free) | Cloud |
|---|---|---|---|
| Brain | Chat, questions, feedback | Ollama | Any OpenAI-style API |
| Ear | Speech to text | Planned (separate install) | Planned |
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

Speech to text (for the conversation features) is not needed yet. Its
install steps will be added with the first feature that uses the microphone.

## Troubleshooting

| Message | What to do |
|---|---|
| "Could not reach the model server" | Start Ollama (search "Ollama" in the Start menu), or check `LLM_BASE_URL` |
| "Model ... was not found" | Run `ollama pull <model>`, or fix `LLM_MODEL` in `.env` |
| "The model took too long to answer" | The first request loads the model and is slow. Retry, or raise `LLM_TIMEOUT` |
| "rejected the API key" | Check `LLM_API_KEY` in `.env` |
| "did not return a usable word list" or "dictation text" | Retry. If it repeats, try a larger model |
| "This browser has no voice for ..." | Add the language in Windows (see Voices), or use a speech server |
| Dictation is silent | Check the PC volume, pick another voice in the Voice list, or try Edge |

## For developers

### Project layout

```
app/
  main.py            entry point, serves the API and the browser UI
  config.py          settings from environment variables / .env
  providers/
    base.py          the three interfaces: ChatProvider, SpeechToText, TextToSpeech
    openai_compatible.py   brain and mouth for Ollama and OpenAI-style APIs
    factory.py       picks the provider named in the settings
  features/
    vocabulary.py    Feature 4
    dictation.py     Feature 5
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
