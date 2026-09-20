"""Cliente da API interna do Reclame Aqui.

Uso como biblioteca:

    from reclameaqui import Client

    c = Client("quinto-andar")
    print(c.company())                 # dados públicos da empresa
    for r in c.complaints(limit=200):  # itera reclamações
        print(r["title"])

Uso pela linha de comando: veja `python -m reclameaqui --help`.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Iterable, Iterator

import requests

log = logging.getLogger("reclameaqui")

IOSITE = "https://iosite.reclameaqui.com.br/raichu-io-site-v1"
IOSEARCH = "https://iosearch.reclameaqui.com.br/raichu-io-site-search-v1"
SITE = "https://www.reclameaqui.com.br"

#: A API rejeita lotes acima disto (responde 200 com corpo vazio).
MAX_BATCH = 10

#: Cada listagem devolve no máximo ~500 itens, independente do offset.
LISTING_CAP = 500

#: Campos com dado pessoal. Removidos antes de qualquer gravação.
PII_FIELDS = frozenset({
    "userEmail", "userName", "ip", "deletedIp", "phones", "address", "user",
    "requesterName", "moderationUserName", "deletionReason",
    "moderationReasonDescription", "userRequestedDelete",
})

DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Origin": SITE,
    "Referer": f"{SITE}/",
}


class ReclameAquiError(RuntimeError):
    """Falha ao conversar com a API."""


def strip_pii(item: dict) -> dict:
    """Remove campos de dado pessoal de uma reclamação."""
    return {k: v for k, v in item.items() if k not in PII_FIELDS}


class Client:
    """Cliente para uma empresa, identificada pelo slug na URL do Reclame Aqui.

    O slug é o trecho em ``reclameaqui.com.br/empresa/<slug>/`` — por exemplo
    ``quinto-andar``, ``nubank``, ``magazine-luiza``.

    :param slug: slug da empresa.
    :param delay: intervalo (mín, máx) em segundos entre requisições. O padrão
        é deliberadamente conservador; diminuir sobrecarrega o servidor.
    :param retries: tentativas por requisição, com espera crescente.
    """

    def __init__(self, slug: str, delay: tuple[float, float] = (1.5, 3.0),
                 retries: int = 4, timeout: int = 30):
        self.slug = slug
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.session = requests.Session()
        self._company: dict | None = None

    # ------------------------------------------------------------ rede ---
    def _sleep(self) -> None:
        time.sleep(random.uniform(*self.delay))

    def _get(self, url: str) -> requests.Response | None:
        """GET com retry e espera crescente. Nunca levanta por erro de rede."""
        for attempt in range(self.retries):
            try:
                return self.session.get(url, headers=DEFAULT_HEADERS,
                                        timeout=self.timeout)
            except requests.RequestException as exc:
                wait = 5 * (attempt + 1)
                log.warning("rede (%s) — tentativa %d/%d, aguardando %ds",
                            type(exc).__name__, attempt + 1, self.retries, wait)
                time.sleep(wait)
        return None

    def _get_json(self, url: str) -> dict:
        """GET esperando JSON. A API às vezes responde 200 com corpo vazio."""
        resp = self._get(url)
        if resp is None:
            raise ReclameAquiError(f"sem resposta: {url}")
        if not resp.ok:
            raise ReclameAquiError(f"status {resp.status_code}: {url}")
        try:
            return resp.json()
        except ValueError as exc:
            body = (resp.text or "")[:120]
            raise ReclameAquiError(
                f"resposta não-JSON ({len(resp.text)} bytes): {body!r}") from exc

    # --------------------------------------------------------- empresa ---
    def company(self) -> dict:
        """Cadastro público da empresa (cacheado)."""
        if self._company is None:
            self._company = self._get_json(f"{IOSITE}/company/shortname/{self.slug}")
        return self._company

    @property
    def company_id(self) -> int:
        return self.company()["id"]

    def stats(self) -> dict:
        """Indicadores agregados: total, não respondidas, nota, tempo de resposta."""
        info = self.company()
        raw = info.get("companyIndexes") or []
        text = raw[0] if isinstance(raw, list) and raw else str(raw)
        out: dict[str, float] = {}
        for key in ("totalComplains", "totalNotAnswered", "finalScore",
                    "averageAnswerTime", "solvedPercentual"):
            m = re.search(rf"{key}=([0-9.]+)", str(text))
            if m:
                out[key] = float(m.group(1))
        out["complainCount"] = info.get("complainCount")
        return out

    def problem_types(self) -> list[dict]:
        """Tipos de problema declarados no cadastro da empresa.

        Atenção: costuma trazer só um subconjunto. Para o catálogo completo use
        :meth:`scan_problem_types`.
        """
        found, seen = [], set()
        for presence in self.company().get("presences") or []:
            for pt in presence.get("problemTypes") or []:
                pid = str(pt.get("id"))
                if pid not in seen:
                    seen.add(pid)
                    found.append({"id": pid, "name": pt.get("name")})
        return found

    def scan_problem_types(self, start: int = 1, end: int = 1500) -> list[dict]:
        """Descobre tipos de problema testando IDs um a um.

        Os IDs são inteiros pequenos preenchidos com zeros à esquerda. Lento
        (uma requisição por ID), mas é a única forma de obter o catálogo todo.
        """
        found = []
        for n in range(start, end + 1):
            pid = str(n).zfill(16)
            try:
                page = self._search(0, 1, f"&problemType={pid}")
            except ReclameAquiError:
                page = []
            if page:
                found.append({"id": pid, "name": None,
                              "sample": (page[0].get("title") or "")[:70]})
                log.info("achou %s — %s", pid, found[-1]["sample"])
            self._sleep()
        return found

    # ---------------------------------------------------- reclamações ---
    @staticmethod
    def _extract(payload: dict) -> list[dict]:
        node = payload.get("complainResult", {}).get("complains", {})
        if isinstance(node, dict):
            return node.get("data", [])
        return payload.get("complains") or payload.get("data") or []

    def _search(self, index: int, size: int, extra: str = "") -> list[dict]:
        url = (f"{IOSEARCH}/query/companyComplains/{size}/{index}"
               f"?company={self.company_id}{extra}")
        return self._extract(self._get_json(url))

    def complaints(self, limit: int | None = None, problem_type: str | None = None,
                   keep_pii: bool = False) -> Iterator[dict]:
        """Itera reclamações, da mais recente para a mais antiga.

        :param limit: para após este número de itens.
        :param problem_type: filtra por ID de tipo de problema.
        :param keep_pii: mantém os campos pessoais (desligado por padrão).

        A listagem satura em ~500 itens. Para ir além, itere por tipo de
        problema — veja :meth:`collect_all`.
        """
        extra = f"&problemType={problem_type}" if problem_type else ""
        seen: set[str] = set()
        index, empty = 0, 0
        while index < LISTING_CAP and empty < 2:
            try:
                batch = self._search(index, MAX_BATCH, extra)
            except ReclameAquiError as exc:
                log.warning("index %d: %s", index, exc)
                index += MAX_BATCH
                empty += 1
                continue
            self._sleep()
            fresh = [c for c in batch if c.get("id") not in seen]
            for item in fresh:
                seen.add(item["id"])
                yield item if keep_pii else strip_pii(item)
                if limit and len(seen) >= limit:
                    return
            empty = empty + 1 if not fresh else 0
            if not batch:
                break
            index += MAX_BATCH

    def collect_all(self, problem_types: Iterable[dict] | None = None,
                    keep_pii: bool = False) -> Iterator[dict]:
        """Coleta a listagem geral e depois cada tipo de problema.

        Como cada listagem satura em ~500, fatiar por tipo de problema é o que
        permite passar desse teto. Itens repetidos são descartados.
        """
        seen: set[str] = set()

        def fresh(it: Iterable[dict]) -> Iterator[dict]:
            for item in it:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    yield item

        yield from fresh(self.complaints(keep_pii=keep_pii))
        types = list(problem_types) if problem_types is not None else self.problem_types()
        for i, pt in enumerate(types, 1):
            before = len(seen)
            yield from fresh(self.complaints(problem_type=pt["id"], keep_pii=keep_pii))
            log.info("[%d/%d] %s: +%d (total %d)", i, len(types),
                     pt.get("name") or pt["id"], len(seen) - before, len(seen))

    # ------------------------------------------------------ texto full ---
    def complaint_url(self, item: dict) -> str:
        """URL pública. O campo ``url`` traz só o slug da reclamação."""
        path = str(item.get("url") or "").strip().lstrip("/")
        if path.startswith("http"):
            return path
        if not path.startswith(f"{self.slug}/"):
            path = f"{self.slug}/{path}"
        return f"{SITE}/{path}/"

    def full_text(self, item: dict) -> dict:
        """Busca o texto integral na página da reclamação.

        A API de busca devolve um resumo curto (~130 caracteres). O texto
        completo (~1.300) só existe na página individual.
        """
        from bs4 import BeautifulSoup

        resp = self._get(self.complaint_url(item))
        if resp is None or not resp.ok:
            return {"id": item["id"], "error": "fetch"}
        soup = BeautifulSoup(resp.text, "html.parser")

        def testid(name: str) -> str | None:
            el = soup.find(attrs={"data-testid": name})
            return el.get_text(" ", strip=True) if el else None

        text = testid("complaint-description")
        if not text:  # fallback: maior bloco de texto da página
            blocks = [b.get_text(" ", strip=True) for b in soup.find_all(["p", "div"])]
            blocks = [b for b in blocks if 120 < len(b) < 8000]
            text = max(blocks, key=len) if blocks else None
        return {"id": item["id"], "text": text, "title": testid("complaint-title"),
                "status": testid("complaint-status")}
