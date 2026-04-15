import sqlite3
import os
import tempfile
import unittest
from unittest.mock import patch

from app import create_app


class PromptPilotAppTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.log_fd, self.log_path = tempfile.mkstemp()
        os.close(self.log_fd)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": self.db_path,
                "LOG_FILE": self.log_path,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)
        os.unlink(self.log_path)

    def read_log(self):
        with open(self.log_path, "r", encoding="utf-8") as log_file:
            return log_file.read()

    def signup(self):
        return self.client.post(
            "/signup",
            data={
                "name": "Aarav Sharma",
                "email": "aarav@example.com",
                "password": "super-secret",
                "occupation": "Product Manager",
                "location": "Bengaluru, India",
                "date_of_birth": "1996-08-11",
                "goals": "Move into global product leadership roles.",
            },
            follow_redirects=True,
        )

    def test_signup_page_hides_profile_metadata_fields(self):
        response = self.client.get("/signup")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Goals (optional)", response.data)
        self.assertNotIn(b"Industry", response.data)
        self.assertNotIn(b"Primary use case", response.data)
        self.assertNotIn(b"Preferred tone", response.data)
        self.assertNotIn(b"Create your AI profile once.", response.data)

    def test_login_page_has_no_heading_section(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Login to PromptPilot", response.data)
        self.assertNotIn(b"Return to your workspace", response.data)

    def test_signup_redirects_to_dashboard(self):
        response = self.signup()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"My profile", response.data)
        self.assertIn(b"History", response.data)
        self.assertIn(b"More", response.data)
        self.assertIn(b"Copy prompt", response.data)
        self.assertIn(b"Copy output", response.data)
        self.assertIn(b"Submit", response.data)
        self.assertIn(b"Delete profile", response.data)
        self.assertIn(b"brand/logo.png", response.data)
        self.assertIn(b"Goals (optional)", response.data)
        self.assertIn(b'id="provider-field">', response.data)
        self.assertIn(b"generate-only is-hidden", response.data)
        self.assertIn(b"prompt-mode", response.data)
        self.assertNotIn(b"Generate the right prompt once", response.data)
        self.assertNotIn(b"Primary use case", response.data)
        self.assertNotIn(b"Industry", response.data)
        self.assertNotIn(b"Preferred tone", response.data)
        self.assertNotIn(b"Thinking styles", response.data)
        self.assertNotIn(b'id="result-title"', response.data)
        self.assertNotIn(b'id="handoff-note"', response.data)
        self.assertNotIn(b"Optimized prompt will appear here", response.data)
        self.assertNotIn(b"PromptPilot will merge your saved profile", response.data)
        self.assertNotIn(b"Idle", response.data)

    def test_signup_allows_missing_goals(self):
        response = self.client.post(
            "/signup",
            data={
                "name": "Aarav Sharma",
                "email": "aarav.no-goals@example.com",
                "password": "super-secret",
                "occupation": "Product Manager",
                "location": "Bengaluru, India",
                "date_of_birth": "1996-08-11",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            user = conn.execute(
                "SELECT goals FROM users WHERE email = ?",
                ("aarav.no-goals@example.com",),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(user["goals"], "")

    def test_signup_defaults_hidden_metadata(self):
        response = self.client.post(
            "/signup",
            data={
                "name": "Aarav Sharma",
                "email": "aarav.defaults@example.com",
                "password": "super-secret",
                "occupation": "Product Manager",
                "location": "Bengaluru, India",
                "date_of_birth": "1996-08-11",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            user = conn.execute(
                "SELECT industry, primary_use_case, preferred_tone FROM users WHERE email = ?",
                ("aarav.defaults@example.com",),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(user["industry"], "")
        self.assertEqual(user["primary_use_case"], "general")
        self.assertEqual(user["preferred_tone"], "Direct and polished")

    def test_generate_prompt_returns_json(self):
        self.signup()
        response = self.client.post(
            "/api/generate",
            json={
                "task": "Create a 5-point interview prep plan for PM roles.",
                "use_case": "career",
                "target_provider": "chatgpt",
                "mode": "prompt",
                "audience": "Self",
                "thinking_styles": "Analytical, strategic",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "prompt_ready")
        self.assertIn("Create a 5-point interview prep plan", payload["optimized_prompt"])
        self.assertNotIn("wizard_trace", payload)
        self.assertNotIn("wizard_selected_variant", payload)
        self.assertNotIn("wizard_selected_score", payload)
        log_text = self.read_log()
        self.assertIn("Prompt wizard run", log_text)
        self.assertIn("Mutate:", log_text)
        self.assertIn("Scoring:", log_text)
        self.assertIn("Critique", log_text)
        self.assertIn("Synthesize:", log_text)

    def test_clear_history_empties_saved_generations(self):
        self.signup()
        self.client.post(
            "/api/generate",
            json={
                "task": "Create a 5-point interview prep plan for PM roles.",
                "use_case": "career",
                "target_provider": "chatgpt",
                "mode": "prompt",
                "audience": "Self",
            },
        )

        before_clear = self.client.get("/dashboard")
        self.assertIn(b"Clear history", before_clear.data)
        self.assertIn(b"Copy task", before_clear.data)

        response = self.client.post("/history/clear", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No history found.", response.data)

    def test_update_profile_preserves_hidden_fields(self):
        self.signup()

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE users
                SET industry = ?, primary_use_case = ?, preferred_tone = ?
                WHERE email = ?
                """,
                ("SaaS", "career", "Direct and polished", "aarav@example.com"),
            )
            conn.commit()
        finally:
            conn.close()

        response = self.client.post(
            "/profile",
            data={
                "name": "Aarav Sharma",
                "occupation": "Senior Product Manager",
                "location": "Berlin, Germany",
                "date_of_birth": "1996-08-11",
                "goals": "Move into global product leadership roles.",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            user = conn.execute(
                "SELECT industry, primary_use_case, preferred_tone FROM users WHERE email = ?",
                ("aarav@example.com",),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(user["industry"], "SaaS")
        self.assertEqual(user["primary_use_case"], "career")
        self.assertEqual(user["preferred_tone"], "Direct and polished")

    def test_delete_profile_removes_user_and_history(self):
        self.signup()
        self.client.post(
            "/api/generate",
            json={
                "task": "Create a 5-point interview prep plan for PM roles.",
                "use_case": "career",
                "target_provider": "chatgpt",
                "mode": "prompt",
                "audience": "Self",
            },
        )

        response = self.client.post("/profile/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Start with your profile", response.data)

        conn = sqlite3.connect(self.db_path)
        try:
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            generation_count = conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(user_count, 0)
        self.assertEqual(generation_count, 0)

    def test_dev_auth_mode_skips_password_verification(self):
        self.signup()
        self.app.config["DEV_AUTH_MODE"] = True
        self.client.post("/logout", follow_redirects=True)

        response = self.client.post(
            "/login",
            data={
                "email": "aarav@example.com",
                "password": "wrong-password",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"My profile", response.data)

    @patch("services.llm_client.OpenAIClient.generate", return_value="A generated response from OpenAI.")
    def test_generate_with_openai_returns_generated_status(self, _mock_generate):
        self.signup()
        self.app.config["OPENAI_API_KEY"] = "test-openai-key"

        response = self.client.post(
            "/api/generate",
            json={
                "task": "Draft a short SaaS networking email.",
                "use_case": "career",
                "target_provider": "chatgpt",
                "mode": "generate",
                "audience": "Recruiter",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "generated")
        self.assertEqual(payload["response_text"], "A generated response from OpenAI.")
        self.assertEqual(payload["model"], self.app.config["OPENAI_MODEL"])

    @patch("services.llm_client.GroqClient.generate", return_value="A generated response from Groq.")
    def test_generate_with_groq_returns_generated_status(self, _mock_generate):
        self.signup()
        self.app.config["GROQ_API_KEY"] = "test-groq-key"

        response = self.client.post(
            "/api/generate",
            json={
                "task": "Draft a short SaaS networking email.",
                "use_case": "career",
                "target_provider": "groq",
                "mode": "generate",
                "audience": "Recruiter",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "generated")
        self.assertEqual(payload["response_text"], "A generated response from Groq.")
        self.assertEqual(payload["model"], self.app.config["GROQ_MODEL"])

    def test_generate_with_missing_openai_key_returns_provider_error(self):
        self.signup()
        self.app.config["OPENAI_API_KEY"] = ""

        response = self.client.post(
            "/api/generate",
            json={
                "task": "Draft a short SaaS networking email.",
                "use_case": "career",
                "target_provider": "chatgpt",
                "mode": "generate",
                "audience": "Recruiter",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "provider_error")
        self.assertIn("OPENAI_API_KEY", payload["handoff_note"])

    @patch("services.llm_client.GeminiClient.generate", return_value="A generated response from Gemini.")
    def test_generate_with_gemini_returns_generated_status(self, _mock_generate):
        self.signup()
        self.app.config["GEMINI_API_KEY"] = "test-gemini-key"

        response = self.client.post(
            "/api/generate",
            json={
                "task": "Summarize a market update.",
                "use_case": "business",
                "target_provider": "gemini",
                "mode": "generate",
                "audience": "Founder",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "generated")
        self.assertEqual(payload["response_text"], "A generated response from Gemini.")
        self.assertEqual(payload["model"], self.app.config["GEMINI_MODEL"])

    @patch("services.llm_client.AnthropicClient.generate", return_value="A generated response from Claude.")
    def test_generate_with_claude_returns_generated_status(self, _mock_generate):
        self.signup()
        self.app.config["ANTHROPIC_API_KEY"] = "test-anthropic-key"

        response = self.client.post(
            "/api/generate",
            json={
                "task": "Draft a concise policy memo.",
                "use_case": "research",
                "target_provider": "claude",
                "mode": "generate",
                "audience": "Analyst",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "generated")
        self.assertEqual(payload["response_text"], "A generated response from Claude.")
        self.assertEqual(payload["model"], self.app.config["ANTHROPIC_MODEL"])


if __name__ == "__main__":
    unittest.main()
