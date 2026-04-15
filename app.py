import os
import sqlite3
from functools import wraps
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from services.llm_client import AnthropicClient, GeminiClient, GroqClient, LLMClientError, OllamaClient, OpenAIClient
from services.prompt_engine import PromptRequest, build_handoff_note, run_prompt_wizard

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "instance" / "promptpilot.db"
DEFAULT_LOG_PATH = BASE_DIR / "instance" / "promptpilot-wizard.log"


def load_dotenv_file(path):
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def env_int(name, default):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


def env_bool(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def env_path(name, default):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return str(default)

    path = Path(raw_value.strip()).expanduser()
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return str(path)


load_dotenv_file(BASE_DIR / ".env")


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "change-me-in-production"),
        DATABASE=env_path("DATABASE", DEFAULT_DB_PATH),
        LOG_FILE=env_path("LOG_FILE", DEFAULT_LOG_PATH),
        OLLAMA_URL=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
        OLLAMA_MODEL=os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
        GROQ_API_KEY=os.getenv("GROQ_API_KEY", ""),
        GROQ_BASE_URL=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        GROQ_MODEL=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", ""),
        OPENAI_BASE_URL=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        OPENAI_MODEL=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        GEMINI_API_KEY=os.getenv("GEMINI_API_KEY", ""),
        GEMINI_BASE_URL=os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com"),
        GEMINI_MODEL=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        ANTHROPIC_API_KEY=os.getenv("ANTHROPIC_API_KEY", ""),
        ANTHROPIC_BASE_URL=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        ANTHROPIC_MODEL=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        ANTHROPIC_VERSION=os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
        ANTHROPIC_MAX_TOKENS=env_int("ANTHROPIC_MAX_TOKENS", 2048),
        LLM_TIMEOUT=env_int("LLM_TIMEOUT", 120),
        DEV_AUTH_MODE=env_bool("DEV_AUTH_MODE", False),
    )

    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["LOG_FILE"]).parent.mkdir(parents=True, exist_ok=True)

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = get_db()
        with open(BASE_DIR / "schema.sql", "r", encoding="utf-8") as schema_file:
            db.executescript(schema_file.read())
        db.commit()

    def current_user():
        user_id = session.get("user_id")
        if not user_id:
            return None
        return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def save_generation(user_id, prompt_request, optimized_prompt, response_text, status):
        db = get_db()
        db.execute(
            """
            INSERT INTO generations (
                user_id,
                provider,
                mode,
                use_case,
                task,
                optimized_prompt,
                response_text,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                prompt_request.target_provider,
                prompt_request.mode,
                prompt_request.use_case,
                prompt_request.task,
                optimized_prompt,
                response_text,
                status,
            ),
        )
        db.commit()

    def log_prompt_wizard(user_id, user_name, prompt_request, wizard_result, status):
        log_path = Path(app.config["LOG_FILE"])
        timestamp = datetime.now().isoformat(timespec="seconds")
        entry = "\n".join(
            [
                f"[{timestamp}] Prompt wizard run",
                (
                    f"user_id={user_id} user_name={user_name!r} "
                    f"provider={prompt_request.target_provider} mode={prompt_request.mode} "
                    f"use_case={prompt_request.use_case} status={status}"
                ),
                (
                    f"selected_variant={wizard_result['selected_variant']} "
                    f"selected_score={wizard_result['selected_score']}"
                ),
                wizard_result["trace"],
                "",
            ]
        )
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(entry)
            log_file.write("\n")

    def login_required(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            return view(**kwargs)

        return wrapped_view

    def get_default_model(provider):
        provider_defaults = {
            "ollama": app.config["OLLAMA_MODEL"],
            "groq": app.config["GROQ_MODEL"],
            "chatgpt": app.config["OPENAI_MODEL"],
            "gemini": app.config["GEMINI_MODEL"],
            "claude": app.config["ANTHROPIC_MODEL"],
        }
        return provider_defaults[provider]

    def get_generation_client(provider):
        if provider == "ollama":
            return OllamaClient(
                base_url=app.config["OLLAMA_URL"],
                default_model=app.config["OLLAMA_MODEL"],
                timeout=app.config["LLM_TIMEOUT"],
            )
        if provider == "groq":
            return GroqClient(
                api_key=app.config["GROQ_API_KEY"],
                base_url=app.config["GROQ_BASE_URL"],
                default_model=app.config["GROQ_MODEL"],
                timeout=app.config["LLM_TIMEOUT"],
            )
        if provider == "chatgpt":
            return OpenAIClient(
                api_key=app.config["OPENAI_API_KEY"],
                base_url=app.config["OPENAI_BASE_URL"],
                default_model=app.config["OPENAI_MODEL"],
                timeout=app.config["LLM_TIMEOUT"],
            )
        if provider == "gemini":
            return GeminiClient(
                api_key=app.config["GEMINI_API_KEY"],
                base_url=app.config["GEMINI_BASE_URL"],
                default_model=app.config["GEMINI_MODEL"],
                timeout=app.config["LLM_TIMEOUT"],
            )
        if provider == "claude":
            return AnthropicClient(
                api_key=app.config["ANTHROPIC_API_KEY"],
                base_url=app.config["ANTHROPIC_BASE_URL"],
                default_model=app.config["ANTHROPIC_MODEL"],
                api_version=app.config["ANTHROPIC_VERSION"],
                max_tokens=app.config["ANTHROPIC_MAX_TOKENS"],
                timeout=app.config["LLM_TIMEOUT"],
            )
        raise ValueError(f"Unsupported provider: {provider}")

    app.teardown_appcontext(close_db)

    @app.before_request
    def load_user():
        g.user = current_user()

    @app.context_processor
    def inject_now():
        return {
            "provider_labels": {
                "ollama": "Ollama",
                "groq": "Groq",
                "chatgpt": "ChatGPT",
                "gemini": "Gemini",
                "claude": "Claude",
            }
        }

    @app.route("/")
    def index():
        if g.user:
            return redirect(url_for("dashboard"))
        return render_template("landing.html")

    @app.route("/signup", methods=("GET", "POST"))
    def signup():
        if request.method == "POST":
            primary_use_case = request.form.get("primary_use_case", "").strip() or "general"
            preferred_tone = request.form.get("preferred_tone", "").strip() or "Direct and polished"
            form = {
                "name": request.form.get("name", "").strip(),
                "email": request.form.get("email", "").strip().lower(),
                "password": request.form.get("password", ""),
                "occupation": request.form.get("occupation", "").strip(),
                "location": request.form.get("location", "").strip(),
                "date_of_birth": request.form.get("date_of_birth", "").strip(),
                "industry": request.form.get("industry", "").strip(),
                "primary_use_case": primary_use_case,
                "preferred_tone": preferred_tone,
                "goals": request.form.get("goals", "").strip(),
            }
            required_fields = [
                "name",
                "email",
                "password",
                "occupation",
                "location",
                "date_of_birth",
            ]
            missing_fields = [field for field in required_fields if not form[field]]
            if missing_fields:
                flash("Please complete all required signup fields.", "error")
                return render_template("signup.html", profile=form)

            db = get_db()
            try:
                cursor = db.execute(
                    """
                    INSERT INTO users (
                        email,
                        password_hash,
                        name,
                        occupation,
                        location,
                        date_of_birth,
                        industry,
                        primary_use_case,
                        preferred_tone,
                        goals
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        form["email"],
                        generate_password_hash(form["password"]),
                        form["name"],
                        form["occupation"],
                        form["location"],
                        form["date_of_birth"],
                        form["industry"],
                        form["primary_use_case"],
                        form["preferred_tone"],
                        form["goals"],
                    ),
                )
                db.commit()
            except sqlite3.IntegrityError:
                flash("That email is already registered.", "error")
                return render_template("signup.html", profile=form)

            session.clear()
            session["user_id"] = cursor.lastrowid
            flash("Profile created. Your AI workspace is ready.", "success")
            return redirect(url_for("dashboard"))

        return render_template("signup.html", profile={})

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

            password_ok = bool(user) and (
                app.config["DEV_AUTH_MODE"] or check_password_hash(user["password_hash"], password)
            )

            if not password_ok:
                flash("Invalid email or password.", "error")
                return render_template("login.html", email=email)

            session.clear()
            session["user_id"] = user["id"]
            flash("Signed in.", "success")
            return redirect(url_for("dashboard"))

        return render_template("login.html", email="")

    @app.post("/logout")
    def logout():
        session.clear()
        flash("Signed out.", "success")
        return redirect(url_for("index"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        history = get_db().execute(
            """
            SELECT id, provider, mode, use_case, task, optimized_prompt, status, created_at
            FROM generations
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 8
            """,
            (g.user["id"],),
        ).fetchall()
        return render_template("dashboard.html", history=history)

    @app.post("/history/clear")
    @login_required
    def clear_history():
        db = get_db()
        db.execute("DELETE FROM generations WHERE user_id = ?", (g.user["id"],))
        db.commit()
        flash("History cleared.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/profile")
    @login_required
    def update_profile():
        def preserved_form_value(field_name):
            if field_name in request.form:
                return request.form.get(field_name, "").strip()
            current_value = g.user[field_name]
            return current_value.strip() if isinstance(current_value, str) else (current_value or "")

        form = {
            "name": request.form.get("name", "").strip(),
            "occupation": request.form.get("occupation", "").strip(),
            "location": request.form.get("location", "").strip(),
            "date_of_birth": request.form.get("date_of_birth", "").strip(),
            "industry": preserved_form_value("industry"),
            "primary_use_case": preserved_form_value("primary_use_case"),
            "preferred_tone": preserved_form_value("preferred_tone"),
            "goals": request.form.get("goals", "").strip(),
        }
        db = get_db()
        db.execute(
            """
            UPDATE users
            SET name = ?,
                occupation = ?,
                location = ?,
                date_of_birth = ?,
                industry = ?,
                primary_use_case = ?,
                preferred_tone = ?,
                goals = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                form["name"],
                form["occupation"],
                form["location"],
                form["date_of_birth"],
                form["industry"],
                form["primary_use_case"],
                form["preferred_tone"],
                form["goals"],
                g.user["id"],
            ),
        )
        db.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/profile/delete")
    @login_required
    def delete_profile():
        db = get_db()
        db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))
        db.commit()
        session.clear()
        flash("Profile deleted.", "success")
        return redirect(url_for("index"))

    @app.post("/api/generate")
    @login_required
    def generate():
        payload = request.get_json(silent=True) or {}
        try:
            prompt_request = PromptRequest.from_payload(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        wizard_result = run_prompt_wizard(g.user, prompt_request)
        optimized_prompt = wizard_result["final_prompt"]
        handoff_note = build_handoff_note(prompt_request.target_provider, prompt_request.mode)
        response_text = None
        status = "prompt_ready"
        selected_model = prompt_request.model or get_default_model(prompt_request.target_provider)

        if prompt_request.mode == "generate":
            client = get_generation_client(prompt_request.target_provider)
            try:
                response_text = client.generate(optimized_prompt, model=selected_model)
                status = "generated"
            except LLMClientError as exc:
                status = "provider_error"
                response_text = str(exc)
                handoff_note = str(exc)

        log_prompt_wizard(g.user["id"], g.user["name"], prompt_request, wizard_result, status)
        save_generation(g.user["id"], prompt_request, optimized_prompt, response_text, status)

        return jsonify(
            {
                "status": status,
                "provider": prompt_request.target_provider,
                "mode": prompt_request.mode,
                "model": selected_model,
                "optimized_prompt": optimized_prompt,
                "response_text": response_text,
                "handoff_note": handoff_note,
            }
        )

    with app.app_context():
        init_db()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=True)
