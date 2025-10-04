#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for the modularized LoL Skin Changer
"""

import argparse
import time
from ocr.backend import OCR
from database.name_db import NameDB
from lcu.client import LCU
from state.shared_state import SharedState
from threads.phase_thread import PhaseThread
from threads.champ_thread import ChampThread
from threads.ocr_thread import OCRSkinThread
from threads.websocket_thread import WSEventThread
from utils.logging import setup_logging, get_logger
from injection.manager import InjectionManager

log = get_logger()


def main():
    """Main entry point"""
    
    ap = argparse.ArgumentParser(description="Tracer combiné LCU + OCR (ChampSelect) — ROI lock + burst OCR + locks/timer fixes")
    
    # OCR arguments
    ap.add_argument("--tessdata", type=str, default=None, help="Chemin du dossier tessdata (ex: C:\\Program Files\\Tesseract-OCR\\tessdata)")
    ap.add_argument("--psm", type=int, default=7)
    ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--lang", type=str, default="fra+eng", help="OCR lang (tesseract)")
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
    ap.add_argument("--diff-threshold", type=float, default=0.005)
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

    args = ap.parse_args()

    setup_logging(args.verbose)
    log.info("Starting...")
    
    # Initialize components
    ocr = OCR(lang=args.lang, psm=args.psm, tesseract_exe=args.tesseract_exe)
    ocr.tessdata_dir = args.tessdata
    log.info(f"OCR: {ocr.backend}")
    
    db = NameDB(lang=args.dd_lang)
    lcu = LCU(args.lockfile)
    state = SharedState()
    
    # Initialize injection manager
    injection_manager = InjectionManager()
    
    # Configure skin writing
    state.skin_write_ms = int(getattr(args, 'skin_threshold_ms', 1500) or 1500)
    state.skin_file = getattr(args, 'skin_file', state.skin_file) or state.skin_file
    state.inject_batch = getattr(args, 'inject_batch', state.inject_batch) or state.inject_batch

    # Initialize threads
    t_phase = PhaseThread(lcu, state, interval=1.0/max(0.5, args.phase_hz), log_transitions=not args.ws)
    t_champ = None if args.ws else ChampThread(lcu, db, state, interval=0.25)
    t_ocr = OCRSkinThread(state, db, ocr, args, lcu)
    t_ws = WSEventThread(lcu, db, state, ping_interval=args.ws_ping, timer_hz=args.timer_hz, fallback_ms=args.fallback_loadout_ms, injection_manager=injection_manager) if args.ws else None

    # Start threads
    t_phase.start()
    if t_champ: 
        t_champ.start()
    t_ocr.start()
    if t_ws: 
        t_ws.start()

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


if __name__ == "__main__":
    main()
