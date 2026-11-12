# Language Suite

An app for practising languages with an AI teacher. It runs on your own
computer with free local models, or with a cloud AI service if you prefer.

| Feature | Status |
|---|---|
| Vocabulary practice (text) | Ready |
| Dictation | Planned |
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
| Mouth | Text to speech | Planned (separate install) | Planned |

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

### Speech engines (for the voice features)

Not needed yet. Install steps for the speech-to-text and text-to-speech
engines will be added here together with the first voice feature.

## Troubleshooting

| Message | What to do |
|---|---|
| "Could not reach the model server" | Start Ollama (search "Ollama" in the Start menu), or check `LLM_BASE_URL` |
| "Model ... was not found" | Run `ollama pull <model>`, or fix `LLM_MODEL` in `.env` |
| "The model took too long to answer" | The first request loads the model and is slow. Retry, or raise `LLM_TIMEOUT` |
| "rejected the API key" | Check `LLM_API_KEY` in `.env` |
| "did not return a usable word list" | Retry. If it repeats, try a larger model |

## For developers

### Project layout

```
app/
  main.py            entry point, serves the API and the browser UI
  config.py          settings from environment variables / .env
  providers/
    base.py          the three interfaces: ChatProvider, SpeechToText, TextToSpeech
    openai_compatible.py   brain for Ollama and OpenAI-style cloud APIs
    factory.py       picks the provider named in the settings
  features/
    vocabulary.py    Feature 4
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
