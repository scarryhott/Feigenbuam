from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class AudioDiagnostics:
    audio_enabled: bool
    asr_available: bool
    tts_available: bool
    asr_backend: str
    tts_backend: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audio_enabled": bool(self.audio_enabled),
            "asr_available": bool(self.asr_available),
            "tts_available": bool(self.tts_available),
            "asr_backend": str(self.asr_backend),
            "tts_backend": str(self.tts_backend),
            "detail": str(self.detail),
        }


class VoiceAudioInterface:
    def __init__(
        self,
        enabled: bool,
        asr_engine: str = "auto",
        enable_tts: bool = True,
        tts_voice: Optional[str] = None,
        listen_timeout: float = 8.0,
        phrase_time_limit: float = 18.0,
    ) -> None:
        self.enabled = bool(enabled)
        self.asr_engine = str(asr_engine or "auto").strip().lower()
        self.enable_tts = bool(enable_tts)
        self.tts_voice = str(tts_voice).strip() if isinstance(tts_voice, str) else None
        self.listen_timeout = float(max(0.5, listen_timeout))
        self.phrase_time_limit = float(max(1.0, phrase_time_limit))

        self._sr: Any = None
        self._recognizer: Any = None
        self._microphone: Any = None
        self._pyttsx3: Any = None
        self._tts_engine: Any = None

        if self.enabled:
            self._init_asr()
            self._init_tts()

    def diagnostics(self) -> AudioDiagnostics:
        if not self.enabled:
            return AudioDiagnostics(
                audio_enabled=False,
                asr_available=False,
                tts_available=False,
                asr_backend="none",
                tts_backend="none",
                detail="audio mode disabled",
            )

        asr_available = self._recognizer is not None and self._microphone is not None
        tts_available = self._tts_engine is not None or shutil.which("say") is not None

        asr_backend = "speech_recognition"
        if not asr_available:
            asr_backend = "unavailable"

        if self._tts_engine is not None:
            tts_backend = "pyttsx3"
        elif shutil.which("say") is not None:
            tts_backend = "macos_say"
        else:
            tts_backend = "unavailable"

        detail = "ready" if (asr_available and (tts_available or not self.enable_tts)) else "partial_setup"
        return AudioDiagnostics(
            audio_enabled=True,
            asr_available=asr_available,
            tts_available=tts_available,
            asr_backend=asr_backend,
            tts_backend=tts_backend,
            detail=detail,
        )

    def _init_asr(self) -> None:
        try:
            import speech_recognition as sr  # type: ignore

            self._sr = sr
            self._recognizer = sr.Recognizer()
            self._microphone = sr.Microphone()
        except Exception:
            self._sr = None
            self._recognizer = None
            self._microphone = None

    def _init_tts(self) -> None:
        if not self.enable_tts:
            return
        try:
            import pyttsx3  # type: ignore

            self._pyttsx3 = pyttsx3
            self._tts_engine = pyttsx3.init()
            if self.tts_voice:
                for voice in self._tts_engine.getProperty("voices"):
                    vid = str(getattr(voice, "id", "")).lower()
                    vname = str(getattr(voice, "name", "")).lower()
                    if self.tts_voice.lower() in {vid, vname}:
                        self._tts_engine.setProperty("voice", getattr(voice, "id"))
                        break
        except Exception:
            self._pyttsx3 = None
            self._tts_engine = None

    def _recognize_with_engine(self, audio: Any, engine: str) -> str:
        if self._recognizer is None:
            return ""

        if engine == "whisper" and hasattr(self._recognizer, "recognize_whisper"):
            return str(self._recognizer.recognize_whisper(audio)).strip()
        if engine == "sphinx":
            return str(self._recognizer.recognize_sphinx(audio)).strip()
        if engine == "google":
            return str(self._recognizer.recognize_google(audio)).strip()
        return ""

    def _recognize(self, audio: Any) -> str:
        if self._recognizer is None:
            return ""

        if self.asr_engine in {"whisper", "sphinx", "google"}:
            return self._recognize_with_engine(audio, self.asr_engine)

        # Auto: prioritize offline-first options where possible.
        engines = []
        if hasattr(self._recognizer, "recognize_whisper"):
            engines.append("whisper")
        engines.extend(["sphinx", "google"])
        for name in engines:
            try:
                text = self._recognize_with_engine(audio, name)
            except Exception:
                continue
            if text:
                return text
        return ""

    def listen_once(self) -> str:
        if not self.enabled or self._recognizer is None or self._microphone is None or self._sr is None:
            return ""

        try:
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = self._recognizer.listen(
                    source,
                    timeout=self.listen_timeout,
                    phrase_time_limit=self.phrase_time_limit,
                )
            return self._recognize(audio)
        except Exception:
            return ""

    def speak(self, text: str) -> None:
        content = str(text).strip()
        if not content or not self.enabled or not self.enable_tts:
            return

        if self._tts_engine is not None:
            try:
                self._tts_engine.say(content)
                self._tts_engine.runAndWait()
                return
            except Exception:
                pass

        if shutil.which("say") is None:
            return

        cmd = ["say"]
        if self.tts_voice:
            cmd.extend(["-v", self.tts_voice])
        cmd.append(content)
        try:
            subprocess.run(cmd, check=False)
        except Exception:
            return
