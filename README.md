# PromptPilot

PromptPilot is a Flask generative AI middleware app that stores a reusable profile at signup, uses that profile to build richer prompts automatically, and defaults to Groq for fast hosted generation.

The stack is intentionally low-friction:

- Flask for the backend and templated frontend
- SQLite for persistence
- Groq for hosted inference
- Render for deployment
- Plain HTML, CSS, and JavaScript for the UI

## What the app does

1. Collects a reusable profile during signup:
   - name
   - occupation
   - location
   - date of birth
   - goals
2. Stores that profile in SQLite.
3. Merges profile data with the current task, use case, audience, and desired output shape.
4. Returns either:
   - an optimized prompt for the selected provider, or
   - a final generated answer when the target provider supports live inference.

The app fills in hidden defaults for the metadata it still uses internally, so the signup form stays short while prompt quality remains high.

## Why the provider behavior is split

Prompt mode always works and gives you a provider-aware handoff prompt.

Generate mode uses the selected provider directly when its API key is configured. Groq is the recommended hosted path because it keeps the app simple to run on Render while still letting you generate answers in-app.

Ollama remains available if you want a local model, and OpenAI, Gemini, and Claude are still supported when their keys are present.

## Project structure

```text
.
|-- app.py
|-- schema.sql
|-- services/
|   |-- llm_client.py
|   `-- prompt_engine.py
|-- static/
|   |-- app.js
|   `-- styles.css
|-- templates/
|   |-- base.html
|   |-- dashboard.html
|   |-- landing.html
|   |-- login.html
|   `-- signup.html
|-- tests/
|   |-- test_app.py
|   `-- test_prompt_engine.py
|-- Dockerfile
|-- compose.yaml
|-- render.yaml
`-- requirements.txt
```

## Run locally

### Option 1: Plain Python

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`.

PromptPilot automatically reads settings from a local `.env` file in the project root.

### Option 2: Local generation with Ollama

Install Ollama on your machine, start it, and pull a model such as:

```powershell
ollama pull llama3.2:3b
```

Then run the Flask app:

```powershell
python app.py
```

Prompt mode works immediately. Generate mode works when the local Ollama server is reachable at `http://127.0.0.1:11434`.

### Option 3: Direct Groq generation with an API key

Edit `.env` in the project root and set one or more provider keys:

```dotenv
GROQ_API_KEY=your-groq-key
GROQ_MODEL=llama-3.3-70b-versatile
OPENAI_API_KEY=your-openai-key
GEMINI_API_KEY=your-gemini-key
ANTHROPIC_API_KEY=your-anthropic-key
```

Then start the app normally:

```powershell
python app.py
```

Then choose `Generate final output` in the UI and select `Groq`.

If Groq rejects the request, the app now shows the raw API error in the output panel. A `403` with `error code: 1010` usually means the request was blocked by the network path or account access, so check the Groq key, deployment host, and region.

### Option 4: Docker Compose

```powershell
docker compose up --build
```

If the Ollama container starts without a model, pull one inside the container or point the app to an existing Ollama instance.

## Environment variables

You can set these either in the shell or in the local `.env` file. A starter template is included in [`.env.example`](./.env.example).

- `SECRET_KEY`: Flask session secret
- `PORT`: app port, default `8000` locally and `10000` in the Docker image
- `DATABASE`: SQLite database path, default `instance/promptpilot.db`
- `LOG_FILE`: prompt wizard log path, default `instance/promptpilot-wizard.log`
- `OLLAMA_URL`: default `http://127.0.0.1:11434`
- `OLLAMA_MODEL`: default `llama3.2:3b`
- `GROQ_API_KEY`: enables direct Groq generation
- `GROQ_BASE_URL`: default `https://api.groq.com/openai/v1`
- `GROQ_MODEL`: default `llama-3.3-70b-versatile`
- `OPENAI_API_KEY`: enables direct OpenAI generation
- `OPENAI_BASE_URL`: default `https://api.openai.com/v1`
- `OPENAI_MODEL`: default `gpt-4.1`
- `GEMINI_API_KEY`: enables direct Gemini generation
- `GEMINI_BASE_URL`: default `https://generativelanguage.googleapis.com`
- `GEMINI_MODEL`: default `gemini-2.5-flash`
- `ANTHROPIC_API_KEY`: enables direct Claude generation
- `ANTHROPIC_BASE_URL`: default `https://api.anthropic.com`
- `ANTHROPIC_MODEL`: default `claude-sonnet-4-20250514`
- `ANTHROPIC_VERSION`: default `2023-06-01`
- `ANTHROPIC_MAX_TOKENS`: default `2048`
- `LLM_TIMEOUT`: default `120`
- `DEV_AUTH_MODE`: set to `true` to let local logins skip password verification

## Render Deployment

Render is the recommended deployment target for this repo because it keeps the app simple to ship, works cleanly with Docker, and fits the Groq-first flow well.

To deploy it:

1. Create a new Render Web Service from this repository.
2. Use the included `Dockerfile` or let Render build from the repo directly.
3. Set at least `SECRET_KEY` and `GROQ_API_KEY` in the Render environment.
4. Leave `DATABASE` and `LOG_FILE` on the default relative paths for local-style storage, or move them to a persistent disk if you want durable history.
5. Start the service with `gunicorn wsgi:application`.

Render binds web services to `PORT`, and the Docker image already listens on that port.

SQLite works fine for demos and low-volume usage. If you need durable history on Render, add persistent storage or move to a managed database.

## Test

```powershell
python -m unittest discover -s tests -v
```
