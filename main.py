#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for the modularized LoL Skin Changer
"""

import argparse
import time
from ocr.backend import OCR
from database.name_db import NameDB
from database.multilang_db import MultiLanguageDB
from lcu.client import LCU
from state.shared_state import SharedState
from threads.phase_thread import PhaseThread
from threads.champ_thread import ChampThread
from threads.ocr_thread import OCRSkinThread
from threads.websocket_thread import WSEventThread
from threads.lcu_monitor_thread import LCUMonitorThread
from utils.logging import setup_logging, get_logger
from injection.manager import InjectionManager
from utils.skin_downloader import download_skins_on_startup

log = get_logger()


def get_ocr_language(lcu_lang: str, manual_lang: str = None) -> str:
    """Get OCR language based on LCU language or manual setting"""
    if manual_lang and manual_lang != "auto":
        return manual_lang
    
    # Map LCU languages to Tesseract languages
    # Use only the specific language (no +eng fallback) for better accuracy
    ocr_lang_map = {
        "en_US": "eng",
        "es_ES": "spa", 
        "es_MX": "spa",
        "fr_FR": "fra",
        "de_DE": "deu",
        "it_IT": "ita",
        "pt_BR": "por",
        "ru_RU": "rus",
        "pl_PL": "pol",
        "tr_TR": "tur",
        "el_GR": "ell",
        "hu_HU": "hun",
        "ro_RO": "ron",
        "zh_CN": "chi_sim",
        "zh_TW": "chi_tra",
        "ja_JP": "jpn",
        "ko_KR": "kor",
    }
    
    return ocr_lang_map.get(lcu_lang, "eng")  # Default to English


def validate_ocr_language(lang: str) -> bool:
    """Validate that OCR language is available (basic check)"""
    if not lang or lang == "auto":
        return True
    
    # Common Tesseract language codes
    supported_langs = [
        "eng", "fra", "spa", "deu", "ita", "por", "rus", "pol", "tur", 
        "ell", "hun", "ron", "chi_sim", "chi_tra", "jpn", "kor"
    ]
    
    # Check if all parts of combined languages are supported
    parts = lang.split('+')
    for part in parts:
        if part not in supported_langs:
            return False
    return True


def main():
    """Main entry point"""
    
    ap = argparse.ArgumentParser(description="Tracer combiné LCU + OCR (ChampSelect) — ROI lock + burst OCR + locks/timer fixes")
    
    # OCR arguments
    ap.add_argument("--tessdata", type=str, default=None, help="Chemin du dossier tessdata (ex: C:\\Program Files\\Tesseract-OCR\\tessdata)")
    ap.add_argument("--psm", type=int, default=7)
    ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--lang", type=str, default="auto", help="OCR lang (tesseract): 'auto', 'fra+eng', 'kor', 'chi_sim', 'ell', etc.")
    ap.add_argument("--tesseract-exe", type=str, default=None)
    
    # Capture arguments
    ap.add_argument("--capture", choices=["window", "screen"], default="window")
    ap.add_argument("--monitor", choices=["all", "primary"], default="all")
    ap.add_argument("--window-hint", type=str, default="League")
    
    # Database arguments
    ap.add_argument("--dd-lang", type=str, default="en_US", help="Langue(s) DDragon: 'fr_FR' | 'fr_FR,en_US,es_ES' | 'all'")
    
    # General arguments
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--lockfile", type=str, default=None)
    
    # OCR performance arguments
    ap.add_argument("--burst-hz", type=float, default=50.0)
    ap.add_argument("--idle-hz", type=float, default=0.0, help="ré-émission périodique (0=off)")
    ap.add_argument("--diff-threshold", type=float, default=0.001)
    ap.add_argument("--burst-ms", type=int, default=280)
    ap.add_argument("--min-ocr-interval", type=float, default=0.11)
    ap.add_argument("--second-shot-ms", type=int, default=120)
    ap.add_argument("--roi-lock-s", type=float, default=1.5)
    
    # Threading arguments
    ap.add_argument("--phase-hz", type=float, default=2.0)
    ap.add_argument("--ws", action="store_true", default=True)
    ap.add_argument("--no-ws", action="store_false", dest="ws", help="Disable WebSocket mode")
    ap.add_argument("--ws-ping", type=int, default=20)
    
    # Timer arguments
    ap.add_argument("--timer-hz", type=int, default=1000, help="Fréquence d'affichage du décompte loadout (Hz)")
    ap.add_argument("--fallback-loadout-ms", type=int, default=0, help="(déprécié) Ancien fallback ms si LCU ne donne pas le timer — ignoré")
    ap.add_argument("--skin-threshold-ms", type=int, default=2000, help="Écrire le dernier skin à T<=seuil (ms)")
    ap.add_argument("--skin-file", type=str, default="state/last_hovered_skin.txt", help="Chemin du fichier last_hovered_skin.txt")
    ap.add_argument("--inject-batch", type=str, default="", help="Batch à exécuter juste après l'écriture du skin (laisser vide pour désactiver)")
    
    # Multi-language arguments
    ap.add_argument("--multilang", action="store_true", default=True, help="Enable multi-language support")
    ap.add_argument("--no-multilang", action="store_false", dest="multilang", help="Disable multi-language support")
    ap.add_argument("--language", type=str, default="auto", help="Manual language selection (e.g., 'fr_FR', 'en_US', 'zh_CN', 'auto' for detection)")
    
    # Skin download arguments
    ap.add_argument("--download-skins", action="store_true", default=True, help="Automatically download skins at startup")
    ap.add_argument("--no-download-skins", action="store_false", dest="download_skins", help="Disable automatic skin downloading")
    ap.add_argument("--force-update-skins", action="store_true", help="Force update all skins (re-download existing ones)")
    ap.add_argument("--max-champions", type=int, default=None, help="Limit number of champions to download skins for (for testing)")

    args = ap.parse_args()

    setup_logging(args.verbose)
    log.info("Starting...")
    
    # Download skins if enabled
    if args.download_skins:
        log.info("Starting automatic skin download...")
        try:
            success = download_skins_on_startup(
                force_update=args.force_update_skins,
                max_champions=args.max_champions
            )
            if success:
                log.info("Skin download completed successfully")
            else:
                log.warning("Skin download completed with some issues")
        except Exception as e:
            log.error(f"Failed to download skins: {e}")
            log.info("Continuing without updated skins...")
    else:
        log.info("Automatic skin download disabled")
    
    # Initialize components
    # Initialize LCU first
    lcu = LCU(args.lockfile)
    
    # Wait for LCU connection before determining language
    ocr_lang = args.lang
    if args.lang == "auto":
        # Wait indefinitely for LCU to be available before getting language
        lcu_lang = None
        
        if not lcu.ok:
            log.info("Waiting for LCU connection...")
        
        while not lcu_lang:
            if lcu.ok:
                try:
                    lcu_lang = lcu.get_client_language()
                    if lcu_lang:
                        log.info(f"LCU connected - detected language: {lcu_lang}")
                        break
                except Exception as e:
                    log.debug(f"Failed to get LCU language: {e}")
            
            time.sleep(1)
            lcu.refresh_if_needed()
        
        ocr_lang = get_ocr_language(lcu_lang, args.lang)
        log.info(f"Auto-detected OCR language: {ocr_lang} (LCU: {lcu_lang})")
        
        # Note: WebSocket connection will be handled by LCUMonitorThread
        # for reconnections and language changes
    
    # Validate OCR language
    if not validate_ocr_language(ocr_lang):
        log.warning(f"OCR language '{ocr_lang}' may not be available. Falling back to English.")
        ocr_lang = "eng"
    
    # Initialize OCR with determined language
    try:
        ocr = OCR(lang=ocr_lang, psm=args.psm, tesseract_exe=args.tesseract_exe)
        ocr.tessdata_dir = args.tessdata
        log.info(f"OCR: {ocr.backend} (lang: {ocr_lang})")
    except Exception as e:
        log.warning(f"Failed to initialize OCR with language '{ocr_lang}': {e}")
        log.info("Falling back to English OCR")
        ocr = OCR(lang="eng", psm=args.psm, tesseract_exe=args.tesseract_exe)
        ocr.tessdata_dir = args.tessdata
        log.info(f"OCR: {ocr.backend} (lang: eng)")
    
    db = NameDB(lang=args.dd_lang)
    state = SharedState()
    
    # Initialize multi-language database (after LCU connection is established)
    if args.multilang:
        auto_detect = args.language.lower() == "auto"
        manual_lang = args.language if not auto_detect else args.dd_lang
        multilang_db = MultiLanguageDB(auto_detect=auto_detect, fallback_lang=manual_lang, lcu_client=lcu)
        if auto_detect:
            log.info("Multi-language auto-detection enabled")
        else:
            log.info(f"Multi-language mode: manual language '{manual_lang}'")
    else:
        multilang_db = None
        log.info("Multi-language support disabled")
    
    # Initialize injection manager
    injection_manager = InjectionManager()
    
    # Configure skin writing
    state.skin_write_ms = int(getattr(args, 'skin_threshold_ms', 2000) or 2000)
    state.skin_file = getattr(args, 'skin_file', state.skin_file) or state.skin_file
    state.inject_batch = getattr(args, 'inject_batch', state.inject_batch) or state.inject_batch

    # Function to update OCR language dynamically
    def update_ocr_language(new_lcu_lang: str):
        """Update OCR language when LCU language changes"""
        if args.lang == "auto":
            new_ocr_lang = get_ocr_language(new_lcu_lang, args.lang)
            if new_ocr_lang != ocr.lang:
                try:
                    # Update OCR language
                    ocr.lang = new_ocr_lang
                    log.info(f"OCR language updated to: {new_ocr_lang} (LCU: {new_lcu_lang})")
                    
                    # Update multilang database if needed
                    if multilang_db and multilang_db.auto_detect:
                        multilang_db.current_language = new_lcu_lang
                        if new_lcu_lang not in multilang_db.databases:
                            try:
                                multilang_db.databases[new_lcu_lang] = NameDB(lang=new_lcu_lang)
                                log.info(f"Loaded multilang database for {new_lcu_lang}")
                            except Exception as e:
                                log.debug(f"Failed to load multilang database for {new_lcu_lang}: {e}")
                except Exception as e:
                    log.warning(f"Failed to update OCR language: {e}")

    # Initialize threads
    t_phase = PhaseThread(lcu, state, interval=1.0/max(0.5, args.phase_hz), log_transitions=not args.ws)
    t_champ = None if args.ws else ChampThread(lcu, db, state, interval=0.25)
    t_ocr = OCRSkinThread(state, db, ocr, args, lcu, multilang_db)
    t_ws = WSEventThread(lcu, db, state, ping_interval=args.ws_ping, timer_hz=args.timer_hz, fallback_ms=args.fallback_loadout_ms, injection_manager=injection_manager) if args.ws else None
    t_lcu_monitor = LCUMonitorThread(lcu, state, update_ocr_language, t_ws)

    # Start threads
    t_phase.start()
    if t_champ: 
        t_champ.start()
    t_ocr.start()
    if t_ws: 
        t_ws.start()
    t_lcu_monitor.start()

    print("[ok] ready — combined tracer. OCR active ONLY in Champ Select.", flush=True)

    last_phase = None
    try:
        while True:
            ph = state.phase
            if ph != last_phase:
                if ph == "InProgress":
                    if state.last_hovered_skin_key:
                        log.info(f"[launch:last-skin] {state.last_hovered_skin_key} (skinId={state.last_hovered_skin_id}, champ={state.last_hovered_skin_slug})")
                    else:
                        log.info("[launch:last-skin] (no hovered skin detected)")
                last_phase = ph
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        state.stop = True
        t_phase.join(timeout=1.0)
        if t_champ: 
            t_champ.join(timeout=1.0)
        t_ocr.join(timeout=1.0)
        if t_ws: 
            t_ws.join(timeout=1.0)
        t_lcu_monitor.join(timeout=1.0)


if __name__ == "__main__":
    main()
