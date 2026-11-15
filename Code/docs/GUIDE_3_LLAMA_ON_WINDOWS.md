# Running Llama locally on Windows with ClaimClear

Llama runs on your own computer, so your medical records never leave it. ClaimClear uses a running local model by default.

## What you need

| | Minimum |
|---|---|
| Windows | 10 or 11, 64-bit |
| RAM | 8 GB for Llama 3.1 8B, or 4 GB for Llama 3.2 3B |
| Free disk space | about 10 GB |
| Python | any version 3.8 or newer |
| Internet | only for the first download |

To check your RAM, press **Win + Pause** (or go to Settings → System → About) and read "Installed RAM".

## Step 1: Install Python (skip if you have it)

1. Open Command Prompt: press **Win + R**, type `cmd`, press Enter.
2. Check for Python by running `py --version`. If it prints `Python 3.x.x`, go to Step 2.
3. Otherwise, download it from https://www.python.org/downloads/ and run the installer. **Tick "Add python.exe to PATH"**, then click Install Now.
4. Close Command Prompt and open a new one so it finds Python.

## Step 2: Unzip ClaimClear

1. Right-click `ClaimClear_Package.zip` → **Extract All…** → Extract.
2. The project is in `ClaimClear_Package\02_Code\ClaimClear`.

## Step 3: Open Command Prompt in the ClaimClear folder

1. In File Explorer, open `ClaimClear_Package\02_Code\ClaimClear`.
2. Click the address bar, type `cmd`, and press Enter. Command Prompt opens in that folder.

## Step 4: Start Llama

```
start_llm.bat --model llama3.1:8b
```

What happens:

1. **If Ollama isn't installed**, it asks `Install it now with: winget install --id Ollama.Ollama? [Y/n]`. Type **Y** and press Enter. Accept the Windows permission prompt if one appears. If it says winget isn't available, install Ollama from https://ollama.com/download (run `OllamaSetup.exe`), then run the same command again.
2. It starts Ollama in the background.
3. On the first run it downloads Llama 3.1 8B (about 4.9 GB), with a progress bar. This takes a few minutes.
4. It loads the model into memory, which can take a minute or two the first time.
5. It ends with: `[llm] ready: llama3.1:8b at http://127.0.0.1:11434/v1. Saved to .env, so ClaimClear uses it automatically.`

If the window says it can't find Ollama after installing it, close Command Prompt, open a new one in the same folder (Step 3), and run the command again.

**If you have 4 GB of RAM or an older PC**, use the smaller model instead: `start_llm.bat --model llama3.2:3b`

**To choose from a menu**, run `start_llm.bat` without a model, type a number and press Enter.

## Step 5: Start ClaimClear

In the same window:

```
start.bat
```

The first run installs ClaimClear (a few minutes); later runs take seconds. Look for this line:

```
[start] local LLM found: llama3.1:8b (Ollama); the chat uses it, records stay on this computer
```

ClaimClear then opens in your browser at http://127.0.0.1:8000.

To do Steps 4 and 5 in one go: `start_llm.bat --model llama3.1:8b --start`

## Step 6: Check that Llama is answering

1. At the top right of the ClaimClear page, the model name should read **llama3.1:8b**.
2. Click a sample case, or attach your documents.
3. Ask a question, such as *"What was my diagnosis?"* or *"Why was R3 deducted?"*. The answer streams in from Llama on your own computer.

## Next time

Ollama starts with Windows on its own (it sits in the system tray as the llama icon), so all you need is `start.bat`. If ClaimClear says *"the local LLM … is not running"*, open **Ollama** from the Start menu, or run `start_llm.bat`, then run `start.bat` again.

## Stopping

| To stop | Do this |
|---|---|
| ClaimClear | Close the browser tab, or press **Ctrl + C** in Command Prompt |
| The model (frees the memory) | Run `ollama stop llama3.1:8b` (Ollama also unloads it by itself after a few idle minutes) |
| Ollama completely | Right-click the llama icon in the system tray → **Quit Ollama** |

## Troubleshooting

| Problem | Fix |
|---|---|
| `Python is needed to start` | Do Step 1 and tick **Add python.exe to PATH**. Then open a new Command Prompt. |
| `'winget' is not recognized` | Install Ollama from https://ollama.com/download, then run Step 4 again. |
| Download stops or fails | Check your internet connection and run the same command again; it continues where it stopped. |
| `the model did not answer` | Not enough memory. Close other programs, or use `llama3.2:3b`. |
| Answers are very slow | Normal on a PC without a graphics card. Use `llama3.2:3b` for faster replies. |
| ClaimClear uses OpenRouter, not Llama | You chose OpenRouter in the page earlier. Run `start_llm.bat --model llama3.1:8b` again, or choose **Local model** in the page's settings. |
| ₹ shows as `?` | Use `start.bat` rather than `python start.py`; it switches the window to UTF-8. |
| See which models are installed | `ollama list` |
| Delete a model to free disk space | `ollama rm llama3.1:8b` |
