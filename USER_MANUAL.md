# Language Suite: a simple guide

**English** | [日本語](USER_MANUAL.ja.md)

This guide is for people who want to use Language Suite and have never
installed a program this way before. You do not need to know anything about
programming. You need about an hour, an internet connection for the
installation, and a little patience: most of the hour is waiting for
downloads.

The guide follows Windows 11. Notes marked **On a Mac** give the difference
for Apple computers. (The Mac steps were written from the documentation of
the tools and have not been tried on a Mac yet.)

## What you are about to do

Language Suite is an AI language teacher that lives **on your own
computer**. It gives conversation practice, dictations, vocabulary and
grammar drills, essay marking and more.

Most AI tools you know work like ordering food by delivery: you send your
request over the internet, a kitchen somewhere else does the work, and the
result comes back. Language Suite works like **cooking at home**. The
kitchen is your computer.

| | Delivery (a website like ChatGPT) | Cooking at home (Language Suite) |
|---|---|---|
| Where the work happens | On a company's computers | On your computer |
| Cost | Often a subscription | Free |
| Privacy | Your texts are sent to the company | Nothing leaves your computer |
| Internet | Always needed | Needed only to install |
| What you need | An account | A reasonably strong computer, and this one-time setup |

"Running software on your local machine" means exactly this: the program,
and the AI behind it, run on the computer in front of you ("local") and not
somewhere on the internet.

## A few words you will meet

| Word | What it means |
|---|---|
| **App** | Language Suite itself: the pages you click on |
| **Model** | The "brain" of the AI teacher. It is one very large file (about 10 GB) that you download once |
| **Ollama** | A free program that runs models on your computer. Think of a film player: Ollama is the player, the model is the film. It works quietly in the background and has almost no window of its own |
| **PowerShell** (Windows), **Terminal** (Mac) | A window where you give the computer instructions by typing a line and pressing Enter, instead of clicking buttons. It looks old-fashioned, but you will only copy and paste a few lines from this guide |
| **Command** | One of those typed lines |
| **Python** | The language Language Suite is written in. Your computer needs Python installed to understand the app, the way it needs a PDF reader to open a PDF |
| **Repository** | The project's home on the GitHub website, where its files are kept. "Downloading the repository" means downloading the app's files |
| **Graphics memory** (also "VRAM" or "GPU memory") | Memory on your computer's graphics card. AI models run much faster when they fit into it |
| **localhost** | A web address that means "this computer". When your browser opens `http://localhost:8000`, it is talking to the app on your own machine, not to the internet |

## Step 1. Check your computer

You are looking for three numbers.

**On Windows**

1. **Memory (RAM):** open **Settings > System > About**. Look at
   "Installed RAM".
2. **Graphics memory:** press `Ctrl + Shift + Esc` to open Task Manager,
   click **Performance**, then **GPU** in the list. Near the bottom, read
   **Dedicated GPU memory**: the second number is the size (for example
   "0.4 / 8.0 GB" means 8 GB). If you see two entries, "GPU 0" and "GPU 1",
   use the larger of the two.
3. **Free disk space:** open File Explorer, click **This PC**, and read the
   free space under your C: drive.

**On a Mac:** open the Apple menu > **About This Mac**. Note the **Chip**
and the **Memory**. For disk space: **System Settings > General > Storage**.

**What your numbers mean**

| What you have | What to do |
|---|---|
| Graphics memory of about 8 GB | Ideal. Use the standard model, `gemma4:e4b` |
| Graphics memory of 12 GB or more | Use the standard model, or the larger `gemma4:12b` for better feedback |
| Less than 6 GB of graphics memory, or none | It still works with the small model `gemma4:e2b`, but answers are slow and simpler. See "If your computer is not strong enough" below |
| Mac with Apple chip (M1 or later) and 16 GB memory or more | Use `gemma4:e4b` |
| Mac with 8 GB memory | Use `gemma4:e2b` |
| Less than 16 GB of RAM (Windows) | Close other programs while you use the app |
| Less than 20 GB of free disk space | Free some space first: the model alone is about 10 GB |

Write down which model name applies to you. This guide uses `gemma4:e4b` in
its examples; type your own model name instead wherever you see it.

**If your computer is not strong enough,** you can use a paid cloud AI
service instead of a model on your computer. That path is described in
`README.md`, section "Cloud setup".

## Step 2. Install Python

1. Go to <https://www.python.org/downloads/> and click the yellow
   **Download Python** button.
2. Open the downloaded file.
3. **Important:** on the first screen, tick the box
   **"Add python.exe to PATH"** at the bottom. Then click **Install Now**.

**On a Mac:** download from the same page and install it like any other
program.

## Step 3. Install Ollama and download the model

1. Go to <https://ollama.com/download>, download Ollama and install it.
   When it is running, you see a small llama icon near the clock (on a Mac:
   in the menu bar at the top).
2. Open PowerShell: click the **Start** button, type `PowerShell`, and
   press Enter. A dark window opens.

   **On a Mac:** press `Cmd + Space`, type `Terminal`, press Enter.
3. Copy the line below, paste it into the window (right-click pastes in
   PowerShell; on a Mac use `Cmd + V`), and press Enter:

   ```
   ollama pull gemma4:e4b
   ```

   This downloads the model. It is about 10 GB, so it can take from ten
   minutes to an hour. You see a progress bar; wait until it says
   "success".
4. Try it:

   ```
   ollama run gemma4:e4b "Say hello in Spanish"
   ```

   After a few seconds the model answers. Your AI teacher's brain is ready.
   You can close this window.

## Step 4. Download the app

1. Open the project's page on GitHub (the page where you found this guide).
2. Click the green **Code** button, then **Download ZIP**.
3. Open your Downloads folder, right-click the ZIP file and choose
   **Extract All**. (On a Mac: double-click the ZIP file.)
4. Move the extracted folder somewhere you will find it again, for example
   into **Documents**.
5. Open the folder until you can see files named `README.md` and
   `requirements.txt`. **This is the project folder.** (Windows sometimes
   puts a folder inside a folder of the same name: go one level deeper
   until you see those files.)

## Step 5. Set the app up (once)

You now open PowerShell *inside the project folder*, so that your commands
apply to the app.

1. With the project folder open in File Explorer, click the empty part of
   the **address bar** at the top (where the folder's path is shown), type
   `powershell`, and press Enter. A PowerShell window opens, and the line in
   it ends with the name of your project folder.

   **On a Mac:** open Terminal, type `cd ` (with a space after it), drag
   the project folder from Finder into the Terminal window, and press Enter.

2. Paste these lines **one at a time**, pressing Enter after each and
   waiting until it has finished (a new line ending in `>` appears).

   **Windows:**

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   pip install -r requirements-voice.txt
   copy .env.example .env
   ```

   **Mac:**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-voice.txt
   cp .env.example .env
   ```

What these lines do, in plain words:

| Line | What it does |
|---|---|
| 1 | Makes a private box inside the project folder for the app's parts, so that nothing else on your computer is changed |
| 2 | Steps into that box. You can tell it worked because the line now starts with `(.venv)` |
| 3 | Downloads the parts the app is built from (a minute or two; a lot of text scrolls by, which is normal) |
| 4 | Downloads the parts for the microphone features (a few minutes) |
| 5 | Creates your personal settings file, called `.env`, from a ready-made example |

If line 2 gives a red message about "running scripts is disabled", see
Troubleshooting below; it is a one-line fix.

**If you chose a different model in Step 1:** open the file `.env` in the
project folder with Notepad (right-click > Open with > Notepad), find the
line `LLM_MODEL=gemma4:e4b`, replace the name with yours, and save.

## Step 6. Start the app

In the same PowerShell window, paste:

```
python -m uvicorn app.main:app --port 8000
```

After a moment you see a line like
`Uvicorn running on http://127.0.0.1:8000`. The app is running.

Now open **Chrome** or **Edge** and go to:

**<http://localhost:8000>**

You should see Language Suite, opened on the Conversation page.

Two things to remember:

- **Keep the PowerShell window open** while you use the app. That window
  *is* the app; the browser is only its screen. You can minimise it.
- Lines of text appear in that window while you work. That is normal.

### First things to do in the app

1. Click **Settings** at the top and enter the language you are learning,
   your own language and your level. The app then fills these in for you
   everywhere.
2. Try something without a microphone first, for example
   **Grammar > Grammar drills** or **Vocabulary > Vocabulary practice**.
   The very first answer takes longer (the model is being loaded); later
   ones are quicker.
3. The first time you use a microphone feature, the browser asks for
   permission: click **Allow**. That first recording is slow, because the
   speech recognition (about 0.5 GB) is downloaded once.

## Stopping the app

Click the PowerShell window and press `Ctrl + C` (on a Mac also
`Ctrl + C`), or simply close the window. The browser page stops working
until you start the app again.

Ollama keeps running in the background and uses almost nothing while idle.
To close it too, right-click the llama icon near the clock and choose
**Quit**.

## Starting it again another day

1. Open PowerShell in the project folder (Step 5, point 1).
2. Paste these two lines, one at a time:

   **Windows:**

   ```powershell
   .venv\Scripts\Activate.ps1
   python -m uvicorn app.main:app --port 8000
   ```

   **Mac:**

   ```bash
   source .venv/bin/activate
   python -m uvicorn app.main:app --port 8000
   ```

3. Open <http://localhost:8000> in Chrome or Edge.

You do not need to repeat the installation. No internet is needed.

## When something goes wrong

Most problems are one of the cases below. Red text in PowerShell looks
alarming, but it nearly always says what is missing.

### During installation

| What you see | Why | What to do |
|---|---|---|
| `python` "is not recognized" (or the Microsoft Store opens) | Python is not installed, or the "Add python.exe to PATH" box was not ticked | Close PowerShell. Run the Python installer again, choose **Modify** or reinstall, and tick the box. Open a new PowerShell window |
| `ollama` "is not recognized" | PowerShell was opened before Ollama was installed | Close PowerShell and open it again. If it still fails, restart the computer |
| "Activate.ps1 cannot be loaded because running scripts is disabled" | Windows blocks this kind of file by default | Paste `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, press Enter, answer `Y` if asked, then repeat the line that failed |
| `pip` "is not recognized", or "No module named uvicorn" | You are not inside the private box | Run the activation line again (`.venv\Scripts\Activate.ps1`). The line must start with `(.venv)` |
| "Could not open requirements file" or "No such file or directory" | PowerShell is not in the project folder | Close it and open it from the project folder, as in Step 5, point 1. Check that you can see `requirements.txt` in that folder |
| `pip install` ends with a lot of red text mentioning "No matching distribution" or "Failed building wheel" | Your Python version may be newer than one of the app's parts supports yet | Uninstall Python, install version 3.13 from the Python website (under "Looking for a specific release?"), delete the `.venv` folder in the project folder, and repeat Step 5 |
| The model download stops or fails | The internet connection dropped, or the disk is full | Run the same `ollama pull` line again: it continues where it stopped. Check your free disk space |
| "pull model manifest: file does not exist" | The model name was mistyped, or the model is no longer offered under that name | Check the spelling. If it is right, see `README.md`, "Changing or replacing the local model" |

### Starting the app

| What you see | Why | What to do |
|---|---|---|
| The browser says "This site can't be reached" or "refused to connect" | The app is not running | Look at the PowerShell window. If it is closed, or shows no "Uvicorn running" line, start the app again (see "Starting it again another day") |
| "error while attempting to bind on address" or "address already in use" | The app is already running in another window | Use that one: just open <http://localhost:8000>. Or close all PowerShell windows and start again |
| The page looks broken or old after an update | The browser kept old files | Press `Ctrl + F5` (on a Mac `Cmd + Shift + R`) |
| The microphone button does nothing and the address is not `localhost` | Browsers allow the microphone only on `localhost` | Open the app at exactly `http://localhost:8000` |

### While using the app

Messages shown at the top of the page:

| Message | What to do |
|---|---|
| "Could not reach the model server" | Ollama is not running. Search "Ollama" in the Start menu and open it, wait a few seconds, try again |
| "Model ... was not found" | The model is not downloaded. In PowerShell run the line the message shows, for example `ollama pull gemma4:e4b` |
| "The model server took too long to answer" | The first request after starting is slow. Try again. If it happens often, see "Everything is very slow" below |
| "did not return a usable ..." | The model wrote something the app could not use. Try again; it usually works the second time |
| "This browser has no voice for this language" | Your computer has no voice for that language. In Windows: **Settings > Time & language > Language & region > Add a language**, choose it and keep **Text-to-speech** ticked, then restart the browser. On a Mac: **System Settings > Accessibility > Spoken Content > System voice > Manage Voices** |
| "The microphone is blocked or missing" | Click the padlock or microphone icon at the left of the address bar and allow the microphone. Also check **Windows Settings > Privacy & security > Microphone** (Mac: **System Settings > Privacy & Security > Microphone**) |
| "No words were recognised" | Speak a little closer to the microphone. Check that the right microphone is selected in your computer's sound settings |
| "Local speech recognition is not installed" | Line 4 of Step 5 was skipped. Stop the app, run `pip install -r requirements-voice.txt` in the activated project folder, start the app again |
| "Could not load the Whisper model" | The first microphone use needs internet for a one-time download. Connect and try again |
| "Reading handwriting needs a chat model that can read images" | Your model cannot read photos. Type your text instead, or use the standard model |

Other situations:

| What happens | Why | What to do |
|---|---|---|
| Everything is very slow (a minute or more for a short answer) | The model does not fit into your graphics memory, so the slower main processor does the work | Close games, video editors and other heavy programs. Plug in a laptop: many are much slower on battery. If it stays slow, switch to the smaller model: run `ollama pull gemma4:e2b`, change `LLM_MODEL` in the `.env` file to `gemma4:e2b`, and restart the app |
| You hear nothing | Volume, or a voice that does not work in this browser | Check the computer's volume, choose another voice in the **Voice** list on the page, or try Edge instead of Chrome |
| The teacher misunderstands what you said | Speech recognition guesses, and sometimes guesses wrong | Speak in full sentences, a little slower, in a quiet room. Where the app shows what it heard, correct it before you send it |
| Feedback ignores the end of a long text | The model can only read a limited amount at once | Use shorter texts, or see `README.md`, "Context window" |
| A note saying that the request is probably too long for the model | The same limit, announced in advance | Shorten the text, or continue and check the result carefully |
| The answer seems wrong | The teacher is an AI and can make mistakes, especially a small model on a home computer | Check doubtful points in a dictionary or grammar book. Treat scores as a guide, not as an exam result |
| You closed PowerShell by accident | The app stopped | Start it again. A session you were in the middle of is lost; finished results are saved under **Progress > History** |

### Still stuck?

Copy the last lines of red text from the PowerShell window (select them
with the mouse, then right-click to copy) and include them when you ask for
help on the project's GitHub page, under **Issues**. Do not post the
contents of your `.env` file if you have ever typed a password or key into
it.

## Getting a newer version of the app

1. Download the ZIP again and extract it (Step 4).
2. From your **old** project folder, copy the file `.env` and the folder
   `data` into the **new** folder. They hold your settings and your
   history.
3. In the new folder, repeat Step 5 (without the last line, since you
   already have a `.env`).
4. Start the app, and press `Ctrl + F5` in the browser.

The model does not need to be downloaded again.

## Removing everything

| To remove | Do this |
|---|---|
| The app, its parts and your history | Delete the project folder |
| The model (the 10 GB file) | In PowerShell: `ollama rm gemma4:e4b` |
| Ollama | **Settings > Apps > Installed apps**, find Ollama, Uninstall (Mac: move Ollama to the Bin) |
| Python | The same way, if you do not need it for anything else |

## Your privacy, in short

With the setup in this guide, your texts, recordings and results stay on
your computer. One exception: voices whose names contain "Online",
"Natural" or "Google" are produced on that company's servers, so the
sentences they read aloud are sent there. Choose another voice in the
**Voice** list if you want to avoid that.

## Where to read more

This guide covers the essentials. For the full version, including every
feature in detail, the cloud setup, voices and microphone options, the
limits of each feature and information for developers, see
[README.md](README.md).
