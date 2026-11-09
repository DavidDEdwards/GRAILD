"""Opt-in packaged offline resource and local playback verification."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
import wave


def run(output_filename):
    output = Path(output_filename).resolve()
    report = {"passed": False, "frozen": bool(getattr(sys, "frozen", False)), "checks": []}
    try:
        # The external runner supplies the project path solely as a deny rule.
        forbidden = os.environ.get("GRAILD_STANDALONE_DENY_PROJECT")
        if forbidden:
            forbidden = Path(forbidden).resolve()
            def audit(event, args):
                if event in ("open", "os.listdir", "os.scandir") and args and isinstance(args[0], (str, bytes, os.PathLike)):
                    path = Path(os.fsdecode(args[0])).resolve()
                    if path.is_relative_to(forbidden):
                        raise PermissionError("Standalone test blocked a project-folder read")
            sys.addaudithook(audit)
        import pygame
        import webview
        import imageio_ffmpeg
        import requests
        import mutagen
        import cryptography
        import sqlite3
        import ssl
        from web_app import JuiceSpotApp, resource_path
        from app_version import APP_VERSION
        from audio_files import get_playback_path
        from tls_support import ca_bundle_path, verified_ssl_context
        import ssl
        assert Path(ca_bundle_path()).is_file()
        tls = verified_ssl_context()
        assert tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED and tls.get_ca_certs()
        report['checks'].append('bundled CA certificates and strict TLS verification')
        report["version"] = APP_VERSION
        # Fail network calls in this process: UI and local gameplay must still work.
        def offline(*args, **kwargs):
            raise requests.ConnectionError("Offline packaging check")
        requests.sessions.Session.request = offline
        with tempfile.TemporaryDirectory(prefix="GRAILD-standalone-profile-") as temp:
            root = Path(temp)
            os.environ["APPDATA"] = str(root / "roaming")
            os.environ["LOCALAPPDATA"] = str(root / "local")
            profile = root / "roaming" / "JuiceSpot"
            profile.mkdir(parents=True)
            music = root / "External music with spaces"
            music.mkdir()
            with wave.open(str(music / "Standalone test.wav"), "wb") as sound:
                sound.setnchannels(1); sound.setsampwidth(2); sound.setframerate(44100)
                sound.writeframes(b"\0\0" * 88200)
            (profile / "juicespot_config.json").write_text(json.dumps({"music_folder": str(music)}))
            app = JuiceSpotApp()
            assert not app.audio_error, app.audio_error
            report["audio_driver"] = pygame.mixer.get_init()
            for name in ("index.html", "canary_ui.js", "update_ui.js", "assets/tailwind.css", "assets/fonts.css", "assets/inter-400.ttf", "assets/inter-600.ttf", "assets/inter-700.ttf", "assets/inter-900.ttf", "GRAILDUpdater.exe"):
                assert Path(resource_path(name)).is_file(), name
            assert Path(imageio_ffmpeg.get_ffmpeg_exe()).is_file()
            for name in ('assets/graild-logo.png', 'assets/graild.ico', 'assets/graild.icns'):
                assert Path(resource_path(name)).is_file(), name
            assert app.register_account("standalone_test", "isolated-smoke-password")["success"]
            assert len(app.tracks) == 1 and app.music_folder == str(music)
            assert Path(get_playback_path(music / "Standalone test.wav")).is_file()
            for mode in ("classic", "random"):
                app.set_game_mode(mode)
                assert app.play_snippet()["ok"]
                app.stop_audio()
            report["checks"].extend(["bundled dependencies, FFmpeg, UI resources and updater helper", "external music folder and both local gameplay modes", "real pygame mixer initialization and decoded playback"])
            html = Path(resource_path("index.html")).read_text(encoding="utf-8")
            assert 'cdn.tailwindcss.com' not in html and 'fonts.googleapis.com' not in html
            window = webview.create_window("GRAILD standalone check", resource_path("index.html"), js_api=app, hidden=True)
            app._window = window
            ui = {"passed": False}
            def loaded():
                try:
                    assert window.evaluate_js("typeof renderState === 'function' && typeof canaryRequest === 'function' && typeof updateNow === 'function'")
                    assert window.evaluate_js("(() => { const n = document.createElement('div'); n.className='hidden bg-purple-600'; document.body.append(n); const s=getComputedStyle(n); const ok=s.display==='none' && s.backgroundColor==='rgb(147, 51, 234)'; n.remove(); return ok && !document.querySelector('script[src^=https],link[href^=https]'); })()")
                    deadline = time.monotonic() + 20
                    while not window.evaluate_js("document.fonts.check('400 16px Inter') && document.fonts.status === 'loaded'"):
                        assert time.monotonic() < deadline, "Bundled font did not load"
                        time.sleep(0.1)
                    bridge = threading.Event()
                    def checked(value):
                        ui["bridge"] = bool(value); bridge.set()
                    window.evaluate_js("pywebview.api.get_account_state().then(s => s.authenticated)", callback=checked)
                    assert bridge.wait(15) and ui.get("bridge"), "Native Python bridge failed"
                    ui["passed"] = True
                except Exception:
                    ui["error"] = traceback.format_exc()
                finally:
                    window.destroy()
            window.events.loaded += loaded
            timer=threading.Timer(60, window.destroy);timer.daemon=True;timer.start()
            try: webview.start(gui="edgechromium", icon=resource_path('assets/graild.ico'))
            finally: timer.cancel()
            assert ui["passed"], ui
            report["checks"].append("native WebView2, Python bridge, local CSS and Inter font without CDN")
            report["project_reads_denied"] = bool(forbidden)
            app.stop_audio(); pygame.mixer.music.unload(); pygame.mixer.quit()
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1
