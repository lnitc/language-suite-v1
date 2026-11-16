# Language Suite

An app for practising languages with an AI teacher. It runs on your own
computer with free local models, or with a cloud AI service if you prefer.

The features are grouped into four sections:

| Section | Features |
|---|---|
| Speaking | Conversation partner, job interview rehearsal, interpreter simulation, speech (public speaking), shadowing (all by voice) |
| Listening | Listening comprehension (a spoken text with multiple-choice questions) |
| Vocabulary | Vocabulary practice (text or voice), vocabulary list creator (CSV and other formats) |
| Writing | Dictation (typed or handwritten), essay writing and written translation (typed, uploaded or handwritten) |
| Reading | Reading comprehension (a text with multiple-choice questions) |
| Grammar | Grammar drills (fill in the blank, correct the mistake) |
| Progress | History of your results, and a list of your mistakes to review |

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

## Settings

The **Settings** button at the top opens a small panel where you set, once:

| Setting | Used for |
|---|---|
| Language I am learning | Fills in the language field of every feature |
| My language | The translation side of vocabulary, word lists, interpreting and translation |
| My level | Preselects the difficulty everywhere |
| Feedback and explanations in | The language of the teacher's feedback in every feature. If empty, your own language is used, and English if that is empty too |

The settings fill in the forms; you can still change any field for a single
session. They are stored in your browser only.

## Context window

A model can only hold a limited amount of text at once: its context window,
counted in tokens (a token is roughly three quarters of an English word, or
about one Japanese character). Everything has to fit: the instructions, your
text, and the answer.

**Ollama does not report an error when a request is too long. It silently
drops part of it**, and the symptom is feedback that ignores the end of your
essay, or questions about only half of a text. On most home computers (less
than 24 GB of graphics memory) Ollama's default window is 4,096 tokens, which
a long essay, a translation or a long reading text with many questions can
exceed, especially in Japanese or Chinese.

The app estimates the size of every request and shows a note when it
probably does not fit. To raise the limit with Ollama on Windows:

1. In PowerShell, run `setx OLLAMA_CONTEXT_LENGTH 8192`
2. Quit Ollama (right-click its icon near the clock, Quit) and start it again.
3. In your `.env` file, set `LLM_CONTEXT_TOKENS=8192` and restart the app.

Run `ollama ps` while a model is loaded to see the window it is using. A
larger window needs more memory; if the model becomes much slower, it no
longer fits in your graphics memory, so choose a smaller number or shorter
texts. With a cloud service, set `LLM_CONTEXT_TOKENS` to the limit of your
model, or to `0` to switch the check off.

## Interpreter simulation

Practise consecutive interpreting by voice. Choose the number of speakers:

| | 1 speaker (speech) | 2 speakers (dialogue) |
|---|---|---|
| What you hear | One person giving a talk in one language | Two people who do not share a language, talking through you |
| What you do | Interpret each part into the other language | Interpret each turn into the other person's language, so the direction changes every turn |
| Languages you need to speak | The target language | Both languages |
| Settings | Sentences before you interpret, number of parts | Sentences per turn, number of turns |

In a dialogue, the page shows the situation and who the speakers are, and
for every turn who is speaking and which language to interpret into. The
voice and the microphone switch language automatically with each turn, so
your browser needs a voice for both languages (see "Voices").

At the end you get an ideal version and a comment for every part or turn,
an overall comment, and a download.

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

## Essay writing

Practise writing and get it marked.

1. Choose the language and level. Start with **an assignment from the
   teacher**, or with **your own essay** if you already have one.
2. Type the essay, or upload it: a text, PDF or Word `.docx` file, or up to
   four photos of a handwritten essay. An upload is put into the text box,
   so you can check it (and fix misread handwriting) before sending.
3. You get a rating on four criteria (content, organisation, vocabulary,
   grammar), written feedback, the most important corrections, and an ideal
   version of your essay. You can edit your essay and have it checked again,
   and download the result.

Length: up to about 2,000 characters is recommended. Longer essays are
accepted with a warning, because a small local model takes longer and may
review the end less carefully. Above 5,000 characters the essay is not
accepted; check it in two parts.

The rating is the model's judgement, not an exam score: use it to compare
your own essays over time rather than as an official grade. Handwriting
needs a chat model that can read images.

## Written translation

Practise translating a text and get it marked.

1. Choose the language pair, difficulty and text length. Start with **a
   text from the teacher**, or with **your own text and translation** if
   you already have both.
2. Type the translation, or upload it: a text, PDF or Word `.docx` file, or
   up to four photos of handwriting. With your own text, type, paste or
   upload the source text as well. Uploads are put into the text boxes, so
   you can check them before sending.
3. You get a rating on four criteria (accuracy, completeness, naturalness,
   grammar and vocabulary), feedback with tips, the most important
   corrections, and an ideal version. You can edit your translation and
   have it checked again, and download the result.

Length: up to about 1,500 characters is recommended for the source text and
for the translation, each. Longer texts are accepted with a warning, up to
3,000 characters. The limits are lower than for an essay because the model
has to read two texts and write a third.

## Listening comprehension

The same exercise as reading comprehension, for the ear. The teacher writes
a short talk, announcement or story in spoken style, the app reads it aloud,
and you answer multiple-choice questions about it.

- The text is not shown while you listen. You see it in the result, next to
  the answers and explanations.
- You can play it as often as you like, stop it, and change the speed.
- "Long" is about two minutes of speech; texts are shorter than in reading.
- The voice comes from your browser or your speech server (see "Voices"),
  so its quality depends on the voice you have for that language.

## Speech (public speaking)

Practise giving a short speech and get it reviewed, like an essay that you
speak.

1. Choose the language, difficulty and length (about 1, 2 or 3 minutes).
   Start with **an assignment from the teacher** (topic, situation,
   audience, points to cover), or with **your own topic**.
2. Record your speech. A timer shows your time against the target, and the
   recording stops by itself one minute after the target. You can record
   again as often as you like.
3. The app writes down what you said. Listen to your recording, correct
   anything the app misheard, and send it.
4. You get a rating on four criteria (content, structure, language, impact
   on the audience), feedback, corrections, and a sample script of an ideal
   speech, which you can also have read aloud. The result can be downloaded.

The coach works from the written transcript and did not hear you, so it
cannot judge pronunciation, voice or intonation. What the app measures
itself is the length of your speech and your speaking pace; both are shown
in the result and given to the coach for its comments.

## Shadowing (listen and repeat)

You hear a sentence, say it yourself, and see which words the app's speech
recognition could make out. Words it could not recognise are highlighted,
and you can try again as often as you like; your best try counts. At the end
you get your average, the words that were missed most, and tips for them.

- Sentences come from the teacher, or from your own text (upload a text,
  PDF or `.docx`).
- Tick **Hide the sentence** to repeat from listening only; the sentence is
  shown after your first try.
- This is not a pronunciation score. Speech recognition guesses what you
  meant, so a recognised word is a good sign rather than proof, and it never
  hears *how* you said it. A word that is not recognised is worth practising.
- In languages with several ways of writing the same word (for example
  kanji and kana in Japanese), a correctly spoken word can be marked as not
  recognised when the recognition writes it differently.

## Reading comprehension

The teacher writes a text and up to ten multiple-choice questions about it,
each with four options, like the reading part of a language proficiency exam.

1. Choose the language, difficulty, text length, number of questions and
   question difficulty. **Straightforward** questions can be answered by
   finding the right sentence. **Tricky** questions rephrase the correct
   answer with other words, while the wrong options borrow the text's own
   wording, so matching words is not enough.
   "Long" is about one A4 page (around 500 words, or 1,000 characters for
   languages such as Japanese and Chinese).
2. The text appears first, so you can start reading while the questions
   are being prepared.
3. Choose your answers and submit. You get your score, the correct answers
   with the reason for each, and, for your wrong answers, why the option
   you chose is wrong. The result can be downloaded.

Tricky questions get a second opinion: the model answers each one from the
text without being told the intended answer, and a question is kept only if
it finds the same answer again. This removes most ambiguous questions, at
the cost of one extra model call per batch.

The answers are marked by the app itself, not by the model, and the options
are shuffled. A small local model can still occasionally write a question
whose "correct" answer is debatable; if a question looks wrong, trust the
text. Badly formed questions are discarded, so you may sometimes get fewer
questions than you asked for.

## Grammar drills

Short exercises on a grammar point.

1. Choose the language and difficulty, and name the grammar point (for
   example "past simple or present perfect"). Leave it empty and the teacher
   picks points that suit your level.
2. Choose the type of exercise: **fill in the blank** (complete a sentence),
   **correct the mistake** (rewrite a sentence that contains one error), or
   mixed. Up to ten items.
3. You get your score, and for every item your answer, the correct answer,
   the rule behind it, and a comment on what was wrong with your answer.

Marking works as in vocabulary practice: the app compares your answer with
the accepted answers itself, ignoring capital letters and punctuation. An
answer that does not match is then shown to the teacher, who accepts it if
it is correct after all. Badly formed items (no blank, no clear answer) are
discarded, so you may sometimes get fewer items than you asked for.

## History and mistake review

The **Progress** section keeps what you have done, so that you can see how
you are getting on and come back to what went wrong.

**History** lists every finished session with its date, language and score.
A small table shows, per activity, how many sessions you did, your average
score, and the average of your last five (compare the two to see whether you
are improving). *Open* shows the full result again, exactly as in the
"Download result" file, and you can download or delete it.

**My mistakes** collects single things to review:

| From | What is collected |
| --- | --- |
| Vocabulary practice | words you got wrong or skipped |
| Grammar drills | items you got wrong or skipped |
| Reading and listening comprehension | questions you got wrong |
| Dictation | sentences with missed words |
| Essay, Translation, Speech | the teacher's corrections |

The same mistake made again is counted ("wrong 3 times") instead of being
listed twice. **Practise the words in Vocabulary** starts a vocabulary
session with your wrong words (up to 50, one language pair at a time); this
needs no model, because the correct translations are already stored. A word
you then translate correctly is marked as learned by itself. Other entries
you mark as learned, or remove, by hand.

Where it is stored: in one database file on your computer,
`data/history.db` (SQLite, which comes with Python: nothing to install).

- It is **not** in the browser, so it survives clearing the browser data
  and is the same in every browser on this computer.
- Only text is stored (scores, your answers, corrections, feedback), never
  recordings. A result is a few kilobytes.
- It never leaves your computer, and `data/` is ignored by git.
- To back it up, copy the file. To start again, delete it while the app is
  stopped, or use the delete buttons on the pages.
- To keep it elsewhere, set `HISTORY_DB` in `.env`.
- To stop saving, untick "Save my results in the history" on the History
  page (remembered per browser).

The app assumes **one learner per installation**: there are no user
accounts, so everyone who uses this copy of the app shares one history.

## Vocabulary list creator

Makes a word list and saves it as a CSV file, which opens in Excel and can
be imported into flashcard tools such as Anki.

| Column | Content |
|---|---|
| 1 | Word or collocation in the language you are learning |
| 2 | Pronunciation (hiragana for Japanese, pinyin for Chinese, IPA for Latin-alphabet languages, and so on) |
| 3 | Translation in the language you chose for explanations |
| 4 | Optional: an example sentence with its translation, then remarks if any (register, nuance, common mistakes) |

Two ways to use it:

- **Create a list:** choose the languages, the difficulty, the number of
  words (up to 100) and describe what you want in the prompt.
- **Tidy up your own list:** upload a text file, a PDF with selectable text
  or a `.docx`, with one word or phrase per line. The layout can be messy:
  readings, meanings and notes may be missing or mixed up. Every line comes
  back as a complete entry, and "Number of words" is ignored. At most 100
  lines are used; the app warns you when a file is longer.

Column 4 can be left out. Untick it on the form and it is never made, which
is quicker. Or untick it above the finished list and download again without
it. A three-column list is the better choice when you upload it as a word
list in the Vocabulary tab: less text for a small model to read.

Choose the file format next to the download button. The choice is
remembered, and the same list can be downloaded again in another format.

| Format | Good for | Notes |
|---|---|---|
| CSV (default) | Excel, Anki and other flashcard tools | The four columns above |
| Plain text | Reading, printing, pasting into notes | One numbered block per word |
| Word (.docx) | Editing and printing | A table on a landscape page |
| PDF | Sharing and printing | Opens the browser's print window: choose "Save as PDF" (or "Microsoft Print to PDF") as the printer. This way every script is drawn correctly with the fonts on your computer |
| JSON | Other programs | The example, its translation and the remarks are separate fields |

The list is made ten entries at a time, so you can watch it grow, stop and
continue, and download what is ready. With a local model, 100 entries can
take several minutes.

Check the result before you study from it: a small local model can get a
reading or a nuance wrong. Entries the model could not complete are shown
in colour and keep your original line.

## Handwritten dictation

In Dictation, choose **How you write: By hand**. You listen to each sentence
and write on paper. At the end you upload a photo or scan of the page (PNG,
JPEG or WebP, up to four pages).

1. The chat model reads your handwriting. It is not shown the original
   text, so it cannot quietly repair your mistakes.
2. You see what it read and can correct misreadings before marking.
3. The text is marked like a typed dictation.

This needs a chat model that can read images (for example `gemma4:e4b` with
Ollama). Photos are shrunk in the browser before they are sent and are not
saved. For the best reading, use dark ink, clear spacing between lines, and
a straight, well-lit photo.

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
- In Conversation and Job interview you can tick **Hands-free** instead: the
  app starts listening when the other person has finished speaking, and
  stops by itself when you pause for two seconds. Leave it unticked if you
  like to pause and think; then nothing is sent until you press the button.
- In those two features the reply is spoken sentence by sentence while the
  model is still writing it, so you do not wait for the whole answer.

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
| "Reading handwriting needs a chat model that can read images" | Use a chat model with image support, or type the dictation instead |
| The handwriting is read badly | Retake the photo: straight, sharp, good light. Then correct the remaining misreadings in the review box |
| Dictation is silent | Check the PC volume, pick another voice in the Voice list, or try Edge |

## For developers

### Project layout

```
app/
  main.py            entry point, serves the API and the browser UI
  config.py          settings from environment variables / .env
  context.py         per-request preferences (feedback language) and notes for the learner
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
    wordlist.py      Feature 6 (vocabulary list creator)
    essay.py         Feature 7 (essay writing)
    reading.py       Features 8 and 10 (reading and listening comprehension)
    shadowing.py     Feature 11 (shadowing: listen and repeat)
    public_speaking.py   Feature 12 (speech: public speaking)
    grammar.py       Feature 13 (grammar drills)
    history.py       History and mistake review (SQLite file in data/)
    translation.py   Feature 9 (written translation)
    handwriting.py   reads handwriting from photos (dictation and essay)
  textutils.py       shared text helpers (answer matching, dictation marking)
  static/            browser UI (plain HTML, CSS, JavaScript)
tests/               run without any model, using a fake provider
  browser/           tests that click through the pages in a real browser
data/                local user data, ignored by git
```

Features must use the interfaces in `providers/base.py`, never a vendor
directly. To add a provider, implement the interface in a new file and
register it in `providers/factory.py`.

### Tests

There are two kinds, and neither needs Ollama, a GPU or a microphone.

| | Quick tests (`tests/`) | Browser tests (`tests/browser/`) |
|---|---|---|
| What they check | The Python code behind each feature | The pages themselves: a real browser clicks through every feature |
| The model is replaced by | A fake provider inside the test | A pretend model, voice and speech-recognition server (`tests/browser/fake_services.py`) |
| Extra install | none | `playwright`, and a browser (installed Chrome or Edge is enough) |
| Time | a few seconds | about half a minute |

```powershell
pip install -r requirements-dev.txt
python -m pytest -m "not browser"      # the quick tests only
```

For the browser tests, install once:

```powershell
pip install -r requirements-browser.txt
```

Then:

```powershell
python -m pytest                       # everything
python -m pytest tests/browser         # the browser tests only
```

- No browser window appears. To watch the tests click through the pages,
  run `$env:BROWSER_TESTS_HEADED = "1"` first (same PowerShell window).
- The tests look for Playwright's own Chromium, then installed Chrome, then
  Edge. To download Playwright's Chromium: `python -m playwright install chromium`.
  To use another Chromium-based browser, put its full path in
  `BROWSER_TESTS_CHROME`.
- Without the `playwright` package the browser tests are reported as
  *skipped*, not failed.
- They start their own copy of the app on a spare port, with a temporary
  history file. Your `.env`, your Ollama and your `data/history.db` are not
  used, and a running app does not get in the way.
- The pretend server recognises each prompt by a phrase in it. If you reword
  a prompt in `app/features/`, update the matching phrase in
  `fake_services.py` (the test for that feature fails until you do).

### Automated checks on GitHub

`.github/workflows/checks.yml` makes GitHub run three checks on its own
machines, for every push to the main branch and for every pull request:

| Check | What it does | Fails when |
|---|---|---|
| Secret scan | gitleaks reads **every commit**, not only the newest | something that looks like a key or password was ever committed |
| Tests | the quick tests on Linux and Windows, Python 3.11 and 3.13 | a test fails |
| Browser tests | the browser tests on Linux | a page no longer works |

The result appears as a green tick or a red cross next to the commit, and in
the repository's **Actions** tab, where each step's output can be read. The
checks need no secret, no model and no GPU, and they are free for public
repositories.

Two things to know:

- The secret scan runs **after** a push, so by then the key is already on
  GitHub. It is a net under the first line of defence, which is the
  `pre-commit` scanner on each contributor's own computer (rule 4 below). If
  the scan ever turns red, treat the key as leaked: revoke it and make a new
  one.
- By itself a red cross does not stop anything. To make the checks
  compulsory, the repository owner switches on a rule once, on GitHub:
  **Settings > Rules > Rulesets > New branch ruleset**, target the default
  branch, tick **Require a pull request before merging** and **Require
  status checks to pass**, and add the checks by name (they can be picked
  after the workflow has run once). From then on a pull request can only be
  merged when everything is green.

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
