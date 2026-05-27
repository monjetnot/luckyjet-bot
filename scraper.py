"""
scraper.py — Écoute les cotes LuckyJet de 1win en temps réel via WebSocket
et les pousse dans la file partagée avec le bot Telegram.
"""
import asyncio
import json
import re
import logging
from datetime import datetime
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# URL du jeu sur 1win (ajuste si nécessaire selon ta région)
GAME_URL = "https://1win.xyz/casino/games/lucky-jet"

class LuckyJetScraper:
    def __init__(self, on_new_cote_callback):
        """
        on_new_cote_callback : fonction async appelée avec (cote: float)
        à chaque nouveau résultat capturé.
        """
        self.callback = on_new_cote_callback
        self.running = False
        self._last_seen = set()  # évite les doublons

    async def start(self):
        self.running = True
        logger.info("🔍 Démarrage du scraper 1win LuckyJet...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )

            # Intercepte les WebSocket
            page = await context.new_page()
            page.on("websocket", self._on_websocket)

            # Intercepte aussi les réponses XHR/Fetch (historique initial)
            page.on("response", self._on_response)

            logger.info(f"🌐 Navigation vers {GAME_URL}")
            try:
                await page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logger.warning(f"Timeout navigation (normal) : {e}")

            # Maintient le scraper actif
            while self.running:
                await asyncio.sleep(1)
                # Vérification périodique : relit le DOM pour les cotes affichées
                try:
                    cotes_dom = await self._read_cotes_from_dom(page)
                    for c in cotes_dom:
                        await self._handle_cote(c)
                except Exception as e:
                    logger.debug(f"DOM read error: {e}")

            await browser.close()

    def stop(self):
        self.running = False

    def _on_websocket(self, ws):
        """Intercepte les messages WebSocket du jeu."""
        ws.on("framereceived", lambda data: asyncio.create_task(
            self._parse_ws_message(data)
        ))

    async def _parse_ws_message(self, data: str):
        """Parse les messages WS pour extraire les cotes de fin de round."""
        try:
            msg = json.loads(data)
        except Exception:
            return

        # 1win Lucky Jet envoie typiquement des messages avec crash_result ou multiplier
        # Schéma observé : {"type":"ROUND_END","multiplier":2.35}
        # ou {"data":{"result":{"multiplier":1.45}}}

        cote = None

        # Pattern 1 : champ direct
        for key in ("multiplier", "crash", "result", "coefficient", "coeff"):
            if key in msg:
                val = msg[key]
                if isinstance(val, (int, float)):
                    cote = float(val)
                    break

        # Pattern 2 : imbriqué
        if cote is None:
            for path in [
                ["data", "result", "multiplier"],
                ["data", "multiplier"],
                ["result", "multiplier"],
                ["payload", "multiplier"],
                ["payload", "coefficient"],
            ]:
                try:
                    val = msg
                    for k in path:
                        val = val[k]
                    if isinstance(val, (int, float)):
                        cote = float(val)
                        break
                except (KeyError, TypeError):
                    continue

        # Pattern 3 : cherche dans le texte brut
        if cote is None:
            raw = str(data)
            matches = re.findall(r'"(?:multiplier|coefficient|crash|result)"\s*:\s*(\d+\.?\d*)', raw)
            if matches:
                cote = float(matches[0])

        if cote and 1.0 <= cote <= 200:
            await self._handle_cote(cote)

    async def _on_response(self, response):
        """Capture les historiques de cotes depuis les requêtes HTTP."""
        url = response.url
        if any(kw in url for kw in ["history", "rounds", "results", "lucky"]):
            try:
                body = await response.json()
                cotes = self._extract_from_json(body)
                for c in cotes[-5:]:  # Seulement les 5 dernières pour éviter le flood
                    await self._handle_cote(c)
            except Exception:
                pass

    def _extract_from_json(self, data, depth=0) -> list:
        """Extraction récursive des cotes dans une réponse JSON."""
        if depth > 5:
            return []
        cotes = []
        if isinstance(data, list):
            for item in data:
                cotes.extend(self._extract_from_json(item, depth + 1))
        elif isinstance(data, dict):
            for key in ("multiplier", "coefficient", "crash", "result", "value"):
                if key in data and isinstance(data[key], (int, float)):
                    v = float(data[key])
                    if 1.0 <= v <= 200:
                        cotes.append(v)
            for v in data.values():
                if isinstance(v, (dict, list)):
                    cotes.extend(self._extract_from_json(v, depth + 1))
        return cotes

    async def _read_cotes_from_dom(self, page) -> list:
        """Lit les cotes affichées dans l'historique visuel du jeu."""
        cotes = []
        try:
            # Sélecteurs courants pour les historiques de crash games
            selectors = [
                ".history-item", ".round-result", ".multiplier-value",
                "[class*='history']", "[class*='result']", "[class*='coefficient']",
                "[class*='multiplier']", ".crash-value"
            ]
            for sel in selectors:
                elements = await page.query_selector_all(sel)
                for el in elements[:10]:
                    text = await el.inner_text()
                    # Nettoie et extrait le nombre
                    cleaned = re.sub(r'[^\d.]', '', text.strip())
                    try:
                        val = float(cleaned)
                        if 1.0 <= val <= 200:
                            cotes.append(round(val, 2))
                    except ValueError:
                        pass
        except Exception:
            pass
        return cotes

    async def _handle_cote(self, cote: float):
        """Déduplique et appelle le callback avec la nouvelle cote."""
        key = f"{cote}_{datetime.now().strftime('%H%M%S')}"
        if key not in self._last_seen:
            self._last_seen.add(key)
            # Nettoyage mémoire
            if len(self._last_seen) > 200:
                oldest = list(self._last_seen)[:100]
                for k in oldest:
                    self._last_seen.discard(k)
            logger.info(f"🎯 Nouvelle cote capturée : {cote}x")
            await self.callback(cote)
