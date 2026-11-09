"""Opt-in isolated live integration check for development and packaged Windows builds."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import traceback
import wave
import subprocess


def run(output_filename):
    result = {"passed": False, "checks": []}
    output = Path(output_filename).resolve()
    try:
        if not os.environ.get("GRAILD_SMOKE_REAL_AUDIO"):
            os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame
        import requests
        import webview
        from web_app import JuiceSpotApp, resource_path
        from app_version import APP_VERSION
        from audio_files import get_playback_path
        import mutagen, cryptography, imageio_ffmpeg, sqlite3, ssl
        assert Path(resource_path("GRAILDUpdater.exe")).is_file()
        for asset in ("index.html", "canary_ui.js", "update_ui.js", "assets/tailwind.css", "assets/fonts.css", "assets/inter-400.ttf", "assets/inter-600.ttf", "assets/inter-700.ttf", "assets/inter-900.ttf"):
            assert Path(resource_path(asset)).is_file(), asset
        result["checks"].append("bundled Python dependencies, UI assets, fonts and updater helper")
        result["frozen"] = bool(getattr(__import__("sys"), "frozen", False))
        result["audio_driver"] = pygame.mixer.get_init()
        with tempfile.TemporaryDirectory(prefix="GRAILD-Canary-check-") as temporary:
            root = Path(temporary)
            os.environ["APPDATA"] = str(root / "profile")
            os.environ["LOCALAPPDATA"] = str(root / "local")
            music = root / "music"
            music.mkdir()
            with wave.open(str(music / "Rental.wav"), "wb") as sound:
                sound.setnchannels(1)
                sound.setsampwidth(2)
                sound.setframerate(44100)
                sound.writeframes(b"\0\0" * 44100)
            original_loader = JuiceSpotApp.load_config_folder
            JuiceSpotApp.load_config_folder = lambda self: str(music)
            try:
                app = JuiceSpotApp()
            finally:
                JuiceSpotApp.load_config_folder = original_loader
            registration = app.register_account("canary_test", "isolated-smoke-password")
            assert registration["success"], registration
            result["checks"].append("isolated profile and existing account/achievement flow")
            assert not app.audio_error, app.audio_error
            leaderboard = app.get_global_leaderboard()
            result["live_leaderboard"] = {"success": leaderboard.get("success"), "message": leaderboard.get("message", "")}
            try:
                health = requests.get(app.get_discord_broker_url() + "/healthz", timeout=25)
                result["discord_broker_health_status"] = health.status_code
            except requests.RequestException as error:
                result["discord_broker_health_status"] = type(error).__name__
            result["checks"].append("packaged broker connectivity and public leaderboard request (no score upload)")
            updates = app.check_for_updates()
            assert updates["current_version"] == APP_VERSION
            if not updates["repository"]:
                assert updates["status"] == "unconfigured"
            result["checks"].append("configured app version and update settings")
            scan_deadline = time.monotonic() + 70
            while time.monotonic() < scan_deadline:
                scan = app.get_canary_era_scan()
                if scan["status"] == "complete":
                    break
                if scan["status"] == "failed":
                    raise AssertionError(scan)
                time.sleep(0.1)
            else:
                raise AssertionError("Automatic era scan timed out")
            checked = app._canary.library_era_checks(str(music), ["Rental.wav"])
            assert checked["Rental.wav"]["era"] == "DRFL", checked
            assert app._canary.local_match(music / "Rental.wav") is None
            result["checks"].append("automatic startup Canary era check without linking recordings")
            def wait(operation, options=None):
                started = app.start_canary_request(operation, options)
                assert started.get("job_id"), started
                deadline = time.monotonic() + 70
                while time.monotonic() < deadline:
                    job = app.get_canary_request(started["job_id"])
                    if job["status"] == "complete":
                        return job["result"]
                    if job["status"] == "failed":
                        raise AssertionError(job)
                    time.sleep(0.1)
                raise AssertionError("Background request timed out")
            search = wait("search", {"query": "Rental"})
            assert any(song["id"] == "rental" for song in search["songs"])
            result["checks"].append("live metadata search in background worker")
            candidates = wait("local", {"filename": "Rental.wav"})
            assert not candidates["confirmed"]
            assert app._canary.local_match(music / "Rental.wav") is None
            info = wait("confirm", {"filename": "Rental.wav", "song_id": "rental"})
            assert info["confirmed"] and info["song"]["id"] == "rental"
            assert info["artwork"].startswith("data:image/"), info.get("notice")
            result["checks"].append("explicit local-file confirmation, live details and artwork")
            era = app.set_recording_era(info["song"]["era"])
            assert era["success"] and era["state"]["eligible_track_count"] == 1
            assert app.get_catalog()[0]["canary"]["id"] == "rental"
            for mode in ("classic", "random"):
                app.set_game_mode(mode)
                assert app.play_snippet()["ok"]
                app.stop_audio()
            assert app.play_correct_answer() is None
            app.stop_audio()
            pygame.mixer.music.unload()
            result["checks"].append("era eligibility and both local-only audio modes with bundled decoder")
            choice = wait("random", {"era": info["song"]["era"]})
            assert choice["song"]["era"] == info["song"]["era"]
            assert choice["song"]["page_url"].startswith("https://canary.best/song/")
            assert app.set_library_source("canary")["success"]
            app.load_game_preferences()
            assert app.library_source == "canary" and app.recording_era == info["song"]["era"]
            assert app.set_library_source("local")["success"]
            result["checks"].append("per-account era/source preferences and era-filtered random Canary page selection")
            client = app._canary.client
            with client._db() as db:
                db.execute("UPDATE api_cache SET saved = 0")
            original_get = client.session.get
            def offline(*args, **kwargs):
                raise requests.ConnectionError("isolated offline check")
            client.session.get = offline
            try:
                assert client.search_songs("Rental")["_stale"]
            finally:
                client.session.get = original_get
            result["checks"].append("offline metadata cache fallback")
            # Exercise the actual bundled HTML, JavaScript, and native WebView2 bridge.
            window = webview.create_window("GRAILD Canary integration check", resource_path("index.html"), js_api=app, hidden=True)
            app._window = window
            ui_result = {"passed": False}
            def loaded():
                try:
                    ready = window.evaluate_js("typeof canaryRequest === 'function' && !!document.getElementById('recording-era-select') && !!document.getElementById('song-information')")
                    assert ready, "Canary UI assets did not load"
                    styling = window.evaluate_js("(() => { const node = document.createElement('div'); node.className = 'hidden bg-purple-600'; document.body.append(node); const style = getComputedStyle(node); const ok = style.display === 'none' && style.backgroundColor === 'rgb(147, 51, 234)'; node.remove(); return ok && !document.querySelector('script[src^=https],link[href^=https]'); })()")
                    assert styling, "Local stylesheet did not load or the UI still depends on a remote script/font"
                    deadline = time.monotonic() + 15
                    while not window.evaluate_js("document.fonts.check('400 16px Inter') && document.fonts.status === 'loaded'"):
                        assert time.monotonic() < deadline, "Bundled font did not load"
                        time.sleep(0.1)
                    result["checks"].append("native WebView2 renders local CSS and bundled Inter font without CDN assets")
                    updater_ui = window.evaluate_js("(() => { renderUpdateState(" + json.dumps(app.get_update_state()) + "); return typeof updateNow === 'function' && !!document.getElementById('manual-update-check') && document.getElementById('settings-current-version').textContent === " + json.dumps(APP_VERSION) + "; })()")
                    assert updater_ui, "Packaged update UI did not load"
                    payload = json.dumps(info)
                    ui_result["passed"] = bool(window.evaluate_js("(() => { beginCanaryInfo('Rental.wav'); renderCanarySongInfo(" + payload + ", 'Rental.wav', true); return document.getElementById('song-info-content').textContent.includes('Rental') && document.querySelectorAll('#song-info-content img').length === 1; })()"))
                except Exception:
                    ui_result["error"] = traceback.format_exc()
                finally:
                    window.destroy()
            window.events.loaded += loaded
            watchdog = threading.Timer(45, window.destroy)
            watchdog.daemon = True
            watchdog.start()
            try:
                webview.start()
            finally:
                watchdog.cancel()
            assert ui_result["passed"], ui_result
            result["checks"].append("native hidden WebView2 loads Canary script, Song Information and real artwork")
            app.stop_audio()
            pygame.mixer.music.unload()
            pygame.mixer.quit()
        result["passed"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1
