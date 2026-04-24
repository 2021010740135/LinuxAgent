from __future__ import annotations

import html

import streamlit as st

from app.agent import ControlledLinuxServerAgent
from app.config import AppSettings
from app.tools import LinuxServerToolService


def build_agent() -> ControlledLinuxServerAgent:
    settings = AppSettings.load()
    tool_service = LinuxServerToolService(settings)
    return ControlledLinuxServerAgent(settings, tool_service)


def ensure_session_state() -> None:
    if "agent" not in st.session_state:
        st.session_state.agent = build_agent()
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Controlled Linux Server Agent is ready. "
                    "Describe what you need on the Linux server, and I will execute safely."
                ),
            }
        ]


def render_styles() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Noto+Sans+SC:wght@400;500;700&display=swap');

:root {
  --bg-gradient-a: #f4f7ff;
  --bg-gradient-b: #e5f7f2;
  --card-bg: rgba(255, 255, 255, 0.82);
  --agent-bg: #0f172a;
  --user-bg: #2563eb;
  --text-light: #f8fafc;
  --text-dark: #0f172a;
  --muted: #475569;
  --accent: #0f766e;
}

html, body, [class*="css"] {
  font-family: "Space Grotesk", "Noto Sans SC", sans-serif;
}

.stApp {
  background:
    radial-gradient(circle at 10% 10%, #dbeafe 0, transparent 35%),
    radial-gradient(circle at 90% 15%, #dcfce7 0, transparent 30%),
    linear-gradient(120deg, var(--bg-gradient-a), var(--bg-gradient-b));
}

.main-wrap {
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: var(--card-bg);
  border-radius: 18px;
  backdrop-filter: blur(8px);
  padding: 16px 18px;
  margin-bottom: 14px;
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.06);
}

.title-row h1 {
  margin: 0;
  color: var(--text-dark);
  font-size: 1.6rem;
  font-weight: 700;
}

.title-row p {
  margin: 6px 0 0 0;
  color: var(--muted);
}

.pending-panel {
  border-left: 4px solid var(--accent);
  background: rgba(236, 253, 245, 0.8);
  border-radius: 12px;
  padding: 12px 14px;
  margin: 8px 0 12px 0;
  color: #134e4a;
}

.chat-row {
  display: flex;
  margin: 10px 0;
  animation: reveal 180ms ease-out;
}

.chat-row.assistant {
  justify-content: flex-start;
}

.chat-row.user {
  justify-content: flex-end;
}

.chat-bubble {
  max-width: min(78ch, 86%);
  border-radius: 16px;
  padding: 11px 13px;
  line-height: 1.45;
  white-space: normal;
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}

.chat-bubble.assistant {
  color: var(--text-light);
  background: linear-gradient(135deg, #0f172a, #1e293b);
}

.chat-bubble.user {
  color: var(--text-light);
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
}

.bubble-role {
  opacity: 0.75;
  font-size: 0.74rem;
  margin-bottom: 5px;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

@keyframes reveal {
  0% { opacity: 0; transform: translateY(4px); }
  100% { opacity: 1; transform: translateY(0); }
}

div[data-testid="stForm"] {
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.88);
  padding: 12px 14px 8px 14px;
}

div[data-testid="stTextArea"] textarea {
  min-height: 140px;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_message(role: str, content: str) -> None:
    safe_content = html.escape(content).replace("\n", "<br>")
    role_class = "assistant" if role == "assistant" else "user"
    role_name = "Agent" if role == "assistant" else "User"
    st.markdown(
        (
            f'<div class="chat-row {role_class}">'
            f'<div class="chat-bubble {role_class}">'
            f'<div class="bubble-role">{role_name}</div>'
            f"<div>{safe_content}</div>"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_pending_tasks(agent: ControlledLinuxServerAgent) -> None:
    actions = agent.list_pending_actions()
    if not actions:
        return

    lines = ["<div class='pending-panel'><strong>Pending high-risk tasks</strong><br>"]
    for action in actions:
        line = (
            f"{html.escape(action.task_id)} | "
            f"{html.escape(action.action_name)} | "
            f"{html.escape(action.reason)} | "
            f"TTL {action.ttl_seconds}s"
        )
        lines.append(f"{line}<br>")
    lines.append("</div>")
    st.markdown("".join(lines), unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(
        page_title="Controlled Linux Server Agent",
        layout="wide",
    )
    ensure_session_state()
    render_styles()

    agent: ControlledLinuxServerAgent = st.session_state.agent

    st.markdown(
        """
<div class="main-wrap title-row">
  <h1>Controlled Linux Server Agent</h1>
  <p>Web chat for Linux ops over SSH with Task-ID confirmation and sudo verification.</p>
</div>
        """,
        unsafe_allow_html=True,
    )

    top_col1, top_col2 = st.columns([1, 1])
    with top_col1:
        if st.button("New Session", use_container_width=True):
            clear_message = agent.reset_conversation(clear_pending_tasks=True)
            st.session_state.messages = [
                {
                    "role": "assistant",
                    "content": "New session started. Pending tasks from the previous session were cleared.",
                }
            ]
            if clear_message:
                st.session_state.messages.append({"role": "assistant", "content": clear_message})
            st.rerun()
    with top_col2:
        if st.button("Clear Pending Tasks", use_container_width=True):
            clear_message = agent.tool_service.clear_all_pending_tasks()
            st.session_state.messages.append({"role": "assistant", "content": clear_message})
            st.rerun()

    render_pending_tasks(agent)

    st.markdown('<div class="main-wrap">', unsafe_allow_html=True)
    for msg in st.session_state.messages:
        render_message(msg["role"], msg["content"])
    st.markdown("</div>", unsafe_allow_html=True)

    with st.form("chat_form", clear_on_submit=True):
        user_input = st.text_area(
            "Your request",
            placeholder=(
                "Example: check system version and disk usage.\n"
                "For high-risk task confirmation: confirm Task-AB12"
            ),
            key="chat_input",
        )
        sudo_password = st.text_input(
            "sudo password (required only for Task-ID confirmation)",
            type="password",
            key="sudo_password_input",
        )
        submitted = st.form_submit_button("Send", use_container_width=True)

    if submitted:
        cleaned = user_input.strip()
        if not cleaned:
            st.warning("Please input a request.")
            return

        st.session_state.messages.append({"role": "user", "content": cleaned})
        with st.spinner("Agent is processing your request..."):
            reply = agent.run_once(
                cleaned,
                sudo_password=sudo_password or None,
                interactive_password_prompt=False,
            )
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()


if __name__ == "__main__":
    main()
