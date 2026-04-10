import os
import time
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup, Tag
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

BASE_URL = "https://www.instagram.com"
LOGIN_URL = f"{BASE_URL}/accounts/login/"


@dataclass
class PostData:
    url: str
    caption: str = ""
    timestamp: str = ""
    is_pinned: bool = False


class InstagramScraper:
    def __init__(self, headless: bool = False):
        self.driver = self._init_driver(headless)
        self.wait = WebDriverWait(self.driver, 15)

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------

    def _init_driver(self, headless: bool) -> webdriver.Chrome:
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(
            "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return driver

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self) -> bool:
        username = os.getenv("INSTAGRAM_USERNAME")
        password = os.getenv("INSTAGRAM_PASSWORD")

        if not username or not password:
            raise ValueError(
                "Credentials manquants. Définis INSTAGRAM_USERNAME et "
                "INSTAGRAM_PASSWORD dans .env"
            )

        self.driver.get(LOGIN_URL)
        time.sleep(2)
        self._dismiss_popup()

        try:
            self.wait.until(
                EC.presence_of_element_located((By.NAME, "username"))
            ).send_keys(username)
            self.driver.find_element(By.NAME, "password").send_keys(password)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

            time.sleep(4)

            if "accounts/login" in self.driver.current_url:
                raise RuntimeError("Connexion échouée : identifiants incorrects.")

            self._dismiss_popup()
            print(f"[+] Connecté en tant que @{username}")
            return True

        except TimeoutException as e:
            raise RuntimeError(f"Timeout lors de la connexion : {e}") from e

    def _dismiss_popup(self):
        """Ferme les popups cookies / 'Enregistrer les infos'."""
        for xpath in [
            "//button[contains(text(),'Allow') or contains(text(),'Autoriser') or contains(text(),'Accept')]",
            "//button[contains(text(),'Not Now') or contains(text(),'Plus tard')]",
        ]:
            try:
                btn = WebDriverWait(self.driver, 4).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                btn.click()
                time.sleep(1)
            except TimeoutException:
                pass

    # ------------------------------------------------------------------
    # Scraping principal
    # ------------------------------------------------------------------

    def scrape(self, url: str, n: int) -> list[PostData]:
        """
        Navigue vers `url` (profil, hashtag, explore…) et retourne
        exactement `n` posts en excluant les posts épinglés.
        """
        self.driver.get(url)
        time.sleep(3)
        self._dismiss_popup()

        posts: list[PostData] = []
        seen_hrefs: set[str] = set()

        while len(posts) < n:
            new_links = self._collect_post_links()

            for href, pinned in new_links:
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)

                if pinned:
                    print(f"  [épinglé, ignoré] {href}")
                    continue

                post = self._scrape_post(f"{BASE_URL}{href}")
                if post:
                    posts.append(post)
                    print(f"  [{len(posts)}/{n}] {post.url}")

                if len(posts) >= n:
                    break

            if len(posts) >= n:
                break

            if not self._scroll_down():
                print("  [fin de page]")
                break

        return posts[:n]

    # ------------------------------------------------------------------
    # Collecte des liens dans la grille
    # ------------------------------------------------------------------

    def _collect_post_links(self) -> list[tuple[str, bool]]:
        """
        Retourne une liste de (href, is_pinned) pour chaque post visible.
        Détecte les posts épinglés via le SVG 'pin' dans leur container.
        """
        soup = self._get_soup()
        results: list[tuple[str, bool]] = []

        for link in soup.select("a[href*='/p/']"):
            href = link.get("href", "")
            if not href:
                continue
            pinned = self._is_pinned(link)
            results.append((href, pinned))

        return results

    def _is_pinned(self, link_tag: Tag) -> bool:
        """
        Un post épinglé a un SVG avec aria-label contenant 'pin' ou
        un élément avec un attribut qui signale l'épinglage.
        On remonte dans les ancêtres de <a> pour trouver ce SVG.
        """
        # Cherche dans le container parent (jusqu'à 5 niveaux)
        container = link_tag
        for _ in range(5):
            parent = container.parent
            if parent is None:
                break
            container = parent

        # SVG avec aria-label contenant 'pin' (EN) ou 'épinglé' (FR)
        for svg in container.find_all("svg"):
            aria = svg.get("aria-label", "").lower()
            if "pin" in aria or "épingl" in aria:
                return True

        # Attribut data- ou class contenant 'pinned'
        for el in container.find_all(True):
            for attr_val in (el.get("class") or []):
                if "pin" in attr_val.lower():
                    return True

        return False

    # ------------------------------------------------------------------
    # Scraping d'un post individuel
    # ------------------------------------------------------------------

    def _scrape_post(self, post_url: str) -> Optional[PostData]:
        try:
            self.driver.get(post_url)
            time.sleep(2)
            soup = self._get_soup()

            caption = ""
            # 1. Balise <h1> dans l'article (caption principale)
            h1 = soup.select_one("article h1")
            if h1:
                caption = h1.get_text(strip=True)
            # 2. Fallback : meta og:description
            if not caption:
                meta = soup.find("meta", {"property": "og:description"})
                if meta:
                    caption = meta.get("content", "")

            timestamp = ""
            time_tag = soup.find("time")
            if time_tag:
                timestamp = time_tag.get("datetime", "")

            return PostData(url=post_url, caption=caption, timestamp=timestamp)

        except Exception as e:
            print(f"  [erreur] {post_url} — {e}")
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_soup(self) -> BeautifulSoup:
        return BeautifulSoup(self.driver.page_source, "lxml")

    def _scroll_down(self) -> bool:
        """Scrolle vers le bas. Retourne False si la page n'a pas grandi."""
        prev = self.driver.execute_script("return document.body.scrollHeight")
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        new = self.driver.execute_script("return document.body.scrollHeight")
        return new > prev

    def close(self):
        self.driver.quit()
