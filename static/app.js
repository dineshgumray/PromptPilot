function setStatus(text, kind) {
  const statusPill = document.getElementById("status-pill");
  if (!statusPill) {
    return;
  }

  statusPill.hidden = false;
  statusPill.textContent = text;
  statusPill.className = `status-pill ${kind || "idle"}`.trim();
}

function copyText(text) {
  const value = String(text ?? "");

  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(value).catch(() => fallbackCopyText(value));
  }

  return Promise.resolve().then(() => fallbackCopyText(value));
}

function fallbackCopyText(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);

  try {
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    const copied = document.execCommand("copy");

    if (!copied) {
      throw new Error("Clipboard copy failed.");
    }
  } finally {
    document.body.removeChild(textarea);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-collapsible-section]").forEach((section) => {
    const toggleButton = section.querySelector("[data-section-toggle]");
    const body = section.querySelector("[data-section-body]");
    const toggleLabel = section.querySelector("[data-toggle-label]");

    if (!toggleButton || !body || !toggleLabel) {
      return;
    }

    const closedLabel = toggleButton.dataset.toggleClosedLabel || "Show";
    const openLabel = toggleButton.dataset.toggleOpenLabel || "Hide";

    function syncSectionState(isExpanded) {
      toggleButton.setAttribute("aria-expanded", String(isExpanded));
      body.classList.toggle("is-hidden", !isExpanded);
      toggleLabel.textContent = isExpanded ? openLabel : closedLabel;
    }

    syncSectionState(toggleButton.getAttribute("aria-expanded") === "true");

    toggleButton.addEventListener("click", () => {
      const isExpanded = toggleButton.getAttribute("aria-expanded") === "true";
      syncSectionState(!isExpanded);
    });
  });

  document.querySelectorAll("[data-copy-history-task]").forEach((button) => {
    button.addEventListener("click", async () => {
      const historyItem = button.closest(".history-item");
      const taskText = historyItem?.querySelector(".history-task-text")?.textContent?.trim();

      if (!taskText) {
        return;
      }

      try {
        await copyText(taskText);
        setStatus("History task copied", "success");
      } catch (error) {
        setStatus("Copy failed", "error");
      }
    });
  });

  document.querySelectorAll("[data-clear-history-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm("Clear all saved history entries?")) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll("[data-delete-profile-button]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (!window.confirm("Delete your profile and all saved history?")) {
        event.preventDefault();
      }
    });
  });

  const form = document.getElementById("generator-form");
  if (!form) {
    return;
  }

  const providerSelect = document.getElementById("provider-select");
  const modeSelect = document.getElementById("mode-select");
  const providerField = document.getElementById("provider-field");
  const modelField = document.getElementById("model-field");
  const modelLabel = document.getElementById("model-label");
  const modelInput = document.getElementById("model-input");
  const promptOutput = document.getElementById("prompt-output");
  const responseOutput = document.getElementById("response-output");
  const outputCard = document.querySelector(".output-card");
  const generateOnlyBlocks = document.querySelectorAll("[data-generate-only]");
  const submitButton = document.getElementById("generate-button");
  const copyPromptButton = document.getElementById("copy-prompt");
  const copyResponseButton = document.getElementById("copy-response");
  const providerModelMeta = {
    groq: {
      label: "Groq model",
      placeholder: "llama-3.3-70b-versatile",
      defaultModel: "llama-3.3-70b-versatile",
    },
    ollama: {
      label: "Ollama model",
      placeholder: "llama3.2:3b",
      defaultModel: "llama3.2:3b",
    },
    chatgpt: {
      label: "OpenAI model",
      placeholder: "gpt-4.1",
      defaultModel: "gpt-4.1",
    },
    gemini: {
      label: "Gemini model",
      placeholder: "gemini-2.5-flash",
      defaultModel: "gemini-2.5-flash",
    },
    claude: {
      label: "Claude model",
      placeholder: "claude-sonnet-4-20250514",
      defaultModel: "claude-sonnet-4-20250514",
    },
  };

  function syncModelForProvider(provider) {
    const providerMeta = providerModelMeta[provider];

    if (!providerMeta) {
      return;
    }

    modelLabel.textContent = providerMeta.label;
    modelInput.placeholder = providerMeta.placeholder;

    if (modelInput.dataset.provider !== provider || !modelInput.value) {
      modelInput.value = providerMeta.defaultModel;
    }

    modelInput.dataset.provider = provider;
  }

  function refreshModeState() {
    const provider = providerSelect.value;
    const mode = modeSelect.value;
    const showModel = mode === "generate";
    const isGenerateMode = mode === "generate";
    providerField.classList.remove("hidden");
    modelField.classList.toggle("hidden", !showModel);

    if (outputCard) {
      outputCard.classList.toggle("prompt-mode", !isGenerateMode);
      outputCard.classList.toggle("generate-mode", isGenerateMode);
    }

    generateOnlyBlocks.forEach((block) => {
      block.hidden = !isGenerateMode;
      block.classList.toggle("is-hidden", !isGenerateMode);
    });

    syncModelForProvider(provider);

    if (showModel) {
      return;
    }
  }

  providerSelect.addEventListener("change", refreshModeState);
  modeSelect.addEventListener("change", refreshModeState);
  refreshModeState();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const payload = Object.fromEntries(new FormData(form).entries());
    submitButton.disabled = true;
    submitButton.textContent = "Running...";
    setStatus("Running", "warning");

    try {
      const response = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Generation failed.");
      }

      promptOutput.textContent = data.optimized_prompt || "No prompt generated.";
      responseOutput.textContent = data.response_text || "No final output returned.";

      if (data.status === "generated") {
        setStatus("Generated", "success");
      } else if (data.status === "provider_error") {
        setStatus("Provider error", "error");
      } else if (data.status === "handoff_required" || data.status === "prompt_ready") {
        setStatus("Prompt ready", "warning");
      } else {
        setStatus("Needs attention", "error");
      }
    } catch (error) {
      responseOutput.textContent = error.message;
      setStatus("Error", "error");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Submit";
    }
  });

  copyPromptButton.addEventListener("click", async () => {
    try {
      await copyText(promptOutput.textContent);
      setStatus("Prompt copied", "success");
    } catch (error) {
      setStatus("Copy failed", "error");
    }
  });

  copyResponseButton.addEventListener("click", async () => {
    try {
      await copyText(responseOutput.textContent);
      setStatus("Output copied", "success");
    } catch (error) {
      setStatus("Copy failed", "error");
    }
  });
});
