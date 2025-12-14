"""
main.py - MIO desktop AI girlfriend (text + voice + call mode)
Added: Upgrade button + PayPal subscription dialog + human onboarding flow.
Notes:
 - Replace OPENROUTER_API_KEY below with your key (no .env).
 - Requires: PyQt5, PyQtWebEngine (optional but recommended), requests, SpeechRecognition, pyttsx3
 - Microphone recording uses SpeechRecognition + PyAudio (Google recognizer used by default).
 - TTS uses pyttsx3 (offline).
 - This is a minimal, practical demo — tune the persona, model, and UI as you like.
"""

import sys
import threading
import time
import queue
import requests
from PyQt5 import QtWidgets, QtCore, QtGui
import speech_recognition as sr
import pyttsx3

# --- ADDED: PyQt WebEngine import (for embedded PayPal page) ---
# Requires: pip install PyQtWebEngine
try:
    from PyQt5 import QtWebEngineWidgets
    WEBENGINE_AVAILABLE = True
except Exception:
    WEBENGINE_AVAILABLE = False
    import webbrowser
# --- END ADDED ---

# -----------------------
# CONFIG (paste your key here)
# -----------------------
OPENROUTER_API_KEY = "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"
OPENROUTER_MODEL = "deepseek/deepseek-r1"

# Correct OpenRouter URL
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Colors
CRIMSON = "#FF0059"    # crimson red
VANTA = "#000000"      # near-vanta black

# -----------------------
# OpenRouter helper
# -----------------------
def openrouter_chat(messages):
    """
    messages: list of dicts like [{"role":"user","content":"..."} ...]
    Returns: assistant text (string) or raises exception
    """
    url = OPENROUTER_API_URL
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.9,
        "max_tokens": 512
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # tolerant parsing for different response shapes
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        try:
            return data["choices"][0]["text"]
        except Exception:
            return str(data)

# -----------------------
# UI
# -----------------------
class MIOApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MIO — your AI girlfriend")
        self.resize(740, 640)
        self.setStyleSheet(f"background: {VANTA}; color: white;")
        self._build_ui()

        self.tts = pyttsx3.init()

        self.conversation = [
            {"role": "system", "content": "You are MIO, a playful and flirty and seductive AI girlfriend. Keep replies short, affectionate, and lightly teasing. Use emojis lightly."}
        ]

        self.call_thread = None
        self.call_running = False
        self.call_queue = queue.Queue()

        # premium flag (set to True on successful subscription)
        self.premium = False

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("MIO")
        title.setStyleSheet(f"font-size:22px; font-weight:700; color: {CRIMSON};")
        subtitle = QtWidgets.QLabel("— Your AI Girlfriend")
        subtitle.setStyleSheet("color: #ddd;")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()

        self.call_btn = QtWidgets.QPushButton("Start Call")
        self.call_btn.setCheckable(True)
        self.call_btn.clicked.connect(self.toggle_call_mode)
        header.addWidget(self.call_btn)

        # --- ADDED: Upgrade button (matches UI style) stored on self for later updates ---
        self.upgrade_btn = QtWidgets.QPushButton("Upgrade")
        self.upgrade_btn.setToolTip("Upgrade to premium subscription")
        self.upgrade_btn.setFixedWidth(100)
        self.upgrade_btn.setStyleSheet(f"background: {CRIMSON}; color: white; padding:8px; border-radius:6px; font-weight:600;")
        self.upgrade_btn.clicked.connect(self.open_upgrade_dialog)
        header.addWidget(self.upgrade_btn)
        # --- END ADDED ---

        layout.addLayout(header)

        self.chat_list = QtWidgets.QListWidget()
        self.chat_list.setStyleSheet(f"""
            QListWidget {{
                background: {VANTA};
                border: 1px solid {CRIMSON};
                padding: 8px;
                font-size: 14px;
            }}
            QListWidget::item {{
                color: #EEE;
            }}
        """)
        layout.addWidget(self.chat_list, 1)

        row = QtWidgets.QHBoxLayout()
        self.input_field = QtWidgets.QLineEdit()
        self.input_field.setPlaceholderText("Type a message to MIO...")
        self.input_field.returnPressed.connect(self.on_send_text)
        self.input_field.setStyleSheet(f"background: #111; color: #EEE; border: 1px solid {CRIMSON}; padding:8px;")
        row.addWidget(self.input_field, 1)

        send_btn = QtWidgets.QPushButton("Send")
        send_btn.clicked.connect(self.on_send_text)
        send_btn.setFixedWidth(90)
        send_btn.setStyleSheet(f"background: {CRIMSON}; color: white; padding:8px; border-radius:6px;")
        row.addWidget(send_btn)

        voice_btn = QtWidgets.QPushButton("🎤 Voice")
        voice_btn.clicked.connect(self.on_voice_message)
        voice_btn.setFixedWidth(90)
        voice_btn.setStyleSheet("background: #222; color: #fff;")
        row.addWidget(voice_btn)

        layout.addLayout(row)

    # -----------------------
    # --- ADDED: Upgrade / PayPal dialog handler (improved) ---
    # -----------------------
    def open_upgrade_dialog(self):
        """
        Opens a dialog with embedded PayPal button HTML (local temp file).
        Uses setHtml with base URL so PayPal SDK can load. Detects subscription success
        by watching document.title changes (onApprove sets title="sub:<id>").
        Falls back to default browser if WebEngine not available.
        """
        plan_id = "P-0GG05336E3956973MNEYCBII"
        # The HTML content with your PayPal snippet. onApprove sets document.title to "sub:<id>"
        paypal_html = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Upgrade — MIO Subscription</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body {{ background: #000; color:#fff; font-family: Arial, sans-serif; display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
      .card {{ background: #111; padding: 24px; border-radius: 12px; border: 1px solid #ff0059; width:320px; text-align:center; }}
      h2 {{ color: #ff0059; margin: 0 0 12px 0; }}
      p {{ color: #ddd; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h2>Upgrade to Premium</h2>
      <p>Subscribe for premium MIO features.</p>
      <div id="paypal-button-container-{plan_id}"></div>
    </div>

    <script src="https://www.paypal.com/sdk/js?client-id=AcGI8BMuAXDnLo6PVp0HMssAg_n3KNANuJ5hLmsF4gYkvx68AvnfMMv3JHU2v7U75P1W2eadPN5-2b38&vault=true&intent=subscription" data-sdk-integration-source="button-factory"></script>
    <script>
      paypal.Buttons({{
          style: {{
              shape: 'pill',
              color: 'black',
              layout: 'vertical',
              label: 'subscribe'
          }},
          createSubscription: function(data, actions) {{
            return actions.subscription.create({{
              plan_id: '{plan_id}'
            }});
          }},
          onApprove: function(data, actions) {{
            // set title so the host app can detect success
            try {{
              document.title = 'sub:' + data.subscriptionID;
              console.log('Subscription successful: ' + data.subscriptionID);
              // also show a native alert as fallback
              alert('Subscription successful: ' + data.subscriptionID);
            }} catch (e) {{
              console.log('onApprove error', e);
            }}
          }},
          onError: function(err) {{
            console.log('PayPal error', err);
            alert('PayPal error: ' + err);
          }}
      }}).render('#paypal-button-container-{plan_id}');
    </script>
  </body>
</html>
"""

        # Embedded web view path
        if WEBENGINE_AVAILABLE:
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("Upgrade — MIO Subscription")
            dlg.setModal(True)
            dlg.resize(420, 520)
            vlayout = QtWidgets.QVBoxLayout(dlg)

            view = QtWebEngineWidgets.QWebEngineView()
            vlayout.addWidget(view)

            # Connect titleChanged to detect "sub:<id>" from onApprove
            def on_title_changed(title):
                if title and title.startswith("sub:"):
                    subid = title.split("sub:", 1)[1]
                    # Hand off to onboarding handler (use singleShot to be safe with event loop)
                    QtCore.QTimer.singleShot(0, lambda: self._on_subscription_detected(subid))
                    try:
                        dlg.accept()
                    except Exception:
                        pass

            view.titleChanged.connect(on_title_changed)

            # Load the HTML with base URL pointing to paypal.com so their script can load resources
            from PyQt5.QtCore import QUrl
            view.setHtml(paypal_html, QUrl("https://www.paypal.com"))

            dlg.exec_()

        else:
            # fallback: create a temp file and open in system browser
            import tempfile, os
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8")
            tf.write(paypal_html)
            tf.flush()
            tf.close()
            webbrowser.open('file://' + os.path.abspath(tf.name))
    # -----------------------
    # --- END ADDED ---
    # -----------------------

    def add_message_bubble(self, sender, text):
        item = QtWidgets.QListWidgetItem()
        wrap = QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout()
        box.setContentsMargins(8, 6, 8, 6)

        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        if sender == "user":
            label.setStyleSheet(f"background: {CRIMSON}; color: white; padding:10px; border-radius:12px;")
            box.addStretch()
            box.addWidget(label)
        else:
            label.setStyleSheet(f"background: #1a1a1a; color: #EEE; padding:10px; border-radius:12px; border:1px solid {CRIMSON};")
            box.addWidget(label)
            box.addStretch()

        wrap.setLayout(box)
        item.setSizeHint(wrap.sizeHint())
        self.chat_list.addItem(item)
        self.chat_list.setItemWidget(item, wrap)
        self.chat_list.scrollToBottom()

    def on_send_text(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.input_field.clear()
        self.add_message_bubble("user", text)
        self.append_and_query("user", text)

    def append_and_query(self, role, content):
        self.conversation.append({"role": role, "content": content})
        threading.Thread(target=self._get_and_render_response, daemon=True).start()

    def _get_and_render_response(self):
        try:
            resp = openrouter_chat(self.conversation)
            self.conversation.append({"role": "assistant", "content": resp})
            QtCore.QMetaObject.invokeMethod(self, "_display_mio_response", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, resp))
            self._speak(resp)
        except Exception as e:
            QtCore.QMetaObject.invokeMethod(self, "_display_mio_response", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, f"[error] {e}"))

    @QtCore.pyqtSlot(str)
    def _display_mio_response(self, text):
        self.add_message_bubble("mio", text)

    def on_voice_message(self):
        threading.Thread(target=self._record_and_send_once, daemon=True).start()

    def _record_and_send_once(self):
        self.add_message_bubble("mio", "🎧 Listening...")
        recognizer = sr.Recognizer()
        with sr.Microphone() as mic:
            try:
                recognizer.adjust_for_ambient_noise(mic, duration=0.5)
                audio = recognizer.listen(mic, timeout=5, phrase_time_limit=12)
                transcript = recognizer.recognize_google(audio)
                QtCore.QMetaObject.invokeMethod(self, "_display_user_voice", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, transcript))
                self.append_and_query("user", transcript)
            except sr.WaitTimeoutError:
                QtCore.QMetaObject.invokeMethod(self, "_display_mio_response", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, "Didn't hear anything. Try again."))
            except sr.UnknownValueError:
                QtCore.QMetaObject.invokeMethod(self, "_display_mio_response", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, "Couldn't understand you."))
            except Exception as e:
                QtCore.QMetaObject.invokeMethod(self, "_display_mio_response", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, f"Voice error: {e}"))

    @QtCore.pyqtSlot(str)
    def _display_user_voice(self, text):
        self.add_message_bubble("user", text)

    def _speak(self, text):
        try:
            def _do():
                self.tts.say(text)
                self.tts.runAndWait()
            threading.Thread(target=_do, daemon=True).start()
        except Exception:
            pass

    def toggle_call_mode(self):
        if self.call_btn.isChecked():
            self.call_btn.setText("Stop Call")
            self.call_running = True
            self.call_thread = threading.Thread(target=self._call_loop, daemon=True)
            self.call_thread.start()
            self.add_message_bubble("mio", "📞 Call started. Speak whenever—MIO will reply aloud.")
        else:
            self.call_btn.setText("Start Call")
            self.call_running = False
            self.add_message_bubble("mio", "📞 Call ended.")

    def _call_loop(self):
        recognizer = sr.Recognizer()
        with sr.Microphone() as mic:
            while self.call_running:
                try:
                    recognizer.adjust_for_ambient_noise(mic, duration=0.3)
                    audio = recognizer.listen(mic, timeout=4, phrase_time_limit=8)
                    try:
                        transcript = recognizer.recognize_google(audio)
                    except sr.UnknownValueError:
                        continue

                    QtCore.QMetaObject.invokeMethod(self, "_display_user_voice", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, transcript))
                    self.conversation.append({"role":"user","content": transcript})

                    try:
                        resp = openrouter_chat(self.conversation)
                    except Exception as e:
                        resp = f"[error] {e}"

                    self.conversation.append({"role":"assistant","content": resp})
                    QtCore.QMetaObject.invokeMethod(self, "_display_mio_response", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, resp))
                    self._speak(resp)
                    time.sleep(0.4)

                except sr.WaitTimeoutError:
                    continue
                except Exception as e:
                    QtCore.QMetaObject.invokeMethod(self, "_display_mio_response", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, f"Call error: {e}"))
                    time.sleep(1)

    # -----------------------
    # --- ADDED: Premium onboarding handler ---
    # -----------------------
    def _on_subscription_detected(self, subscription_id: str):
        """
        Called when PayPal onApprove sets document.title="sub:<id>".
        Runs the human onboarding flow: saves the sub, makes MIO say a warm greeting,
        updates UI to show premium status, and inserts a welcome into the chat.
        """
        # Save locally (non-blocking)
        try:
            import json, os, datetime
            payload = {
                "subscription_id": subscription_id,
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
            }
            homedir = os.path.expanduser("~")
            save_path = os.path.join(homedir, ".mio_subscription.json")
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            # non-fatal; continue
            print("Warning: could not save subscription:", e)

        # Mark premium and update upgrade button
        self.premium = True
        try:
            self.upgrade_btn.setText("Premium ✓")
            self.upgrade_btn.setEnabled(False)
            # give a subtle premium look
            self.upgrade_btn.setStyleSheet("background: #222; color: #ffccdd; padding:8px; border-radius:6px; font-weight:700; border:1px solid #ff0059;")
        except Exception:
            pass

        # Friendly, human-like messages from MIO
        welcome_lines = [
            "💖 Oh — thank you! You're officially a premium human now. I'm so excited.",
            "I'll keep your secret safe. ✨",
            "If you'd like, I can enable extra features now — say 'show me premium' or just keep chatting. 💬"
        ]

        # Add them into the chat with delays to feel human (non-blocking)
        def human_sequence():
            for i, line in enumerate(welcome_lines):
                # small delay between lines to mimic typing/thinking
                time.sleep(0.7 + i * 0.3)
                QtCore.QMetaObject.invokeMethod(self, "_display_mio_response", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, line))
                # speak the first line only so it's not overpowering
                if i == 0:
                    self._speak(line)

            # append a system note to the conversation so the assistant can adapt tone
            self.conversation.append({"role": "system", "content": "The user is a premium subscriber. Use a warmer, slightly more intimate tone."})

            # show a short modal summarizing subscription ID
            try:
                QtWidgets.QMessageBox.information(self, "Subscription complete",
                    f"Thanks for subscribing — subscription id:\n{subscription_id}\n\nMIO's premium features are active.")
            except Exception:
                pass

        threading.Thread(target=human_sequence, daemon=True).start()
    # -----------------------
    # --- END ADDED ---
    # -----------------------

# -----------------------
# Run
# -----------------------
def main():
    if OPENROUTER_API_KEY.startswith("REPLACE") or not OPENROUTER_API_KEY.strip():
        print("ERROR: Please set OPENROUTER_API_KEY in main.py before running.")
        sys.exit(1)

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MIOApp()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
