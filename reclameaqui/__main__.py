"""Linha de comando.

    python -m reclameaqui stats nubank
    python -m reclameaqui types quinto-andar
    python -m reclameaqui collect magazine-luiza --limit 200 --out saida.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from .client import Client, ReclameAquiError

CSV_FIELDS = ["id", "created", "title", "description", "status", "solved",
              "evaluated", "problemType", "productType", "userCity", "userState",
              "url"]


def _write(items, path: Path, fmt: str) -> int:
    n = 0
    if fmt == "jsonl":
        with open(path, "w", encoding="utf-8") as fh:
            for item in items:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                n += 1
    else:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for item in items:
                writer.writerow(item)
                n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reclameaqui",
        description="Cliente da API interna do Reclame Aqui.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("stats", help="indicadores agregados da empresa")
    p.add_argument("slug")

    p = sub.add_parser("types", help="tipos de problema")
    p.add_argument("slug")
    p.add_argument("--scan", action="store_true",
                   help="descobre o catálogo completo testando IDs (lento)")
    p.add_argument("--scan-end", type=int, default=1500)
    p.add_argument("--out", type=Path,
                   help="salva o catálogo em JSON, para usar com "
                        "`collect --types`")

    p = sub.add_parser("collect", help="coleta reclamações")
    p.add_argument("slug")
    p.add_argument("--limit", type=int, help="para após N reclamações")
    p.add_argument("--all", action="store_true",
                   help="percorre cada tipo de problema (passa do teto de ~500)")
    p.add_argument("--types", type=Path,
                   help="JSON de tipos gerado por `types --scan --out`; "
                        "sem ele, --all usa só os tipos do cadastro")
    p.add_argument("--full-text", action="store_true",
                   help="busca o texto integral de cada uma (1 requisição por item)")
    p.add_argument("--out", type=Path, default=Path("complaints.jsonl"))
    p.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
    p.add_argument("--delay", type=float, nargs=2, metavar=("MIN", "MAX"),
                   default=[1.5, 3.0])

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s  %(message)s")

    try:
        client = Client(args.slug, delay=tuple(getattr(args, "delay", (1.5, 3.0))))

        if args.command == "stats":
            info = client.company()
            print(f"{info.get('companyName')}  (id {info.get('id')})")
            for key, value in client.stats().items():
                print(f"  {key:<20} {value}")
            return 0

        if args.command == "types":
            types = (client.scan_problem_types(end=args.scan_end) if args.scan
                     else client.problem_types())
            for t in types:
                print(f"  {t['id']}  {t.get('name') or t.get('sample', '')}")
            print(f"\n{len(types)} tipos")
            if args.out:
                args.out.write_text(json.dumps(types, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
                print(f"salvo em {args.out}")
            return 0

        if args.all:
            types = None
            if args.types:
                types = json.loads(args.types.read_text(encoding="utf-8"))
                print(f"{len(types)} tipos de problema carregados de {args.types}")
            source = client.collect_all(problem_types=types)
        else:
            source = client.complaints(limit=args.limit)
        if args.limit and args.all:
            def capped(it):
                for i, x in enumerate(it):
                    if i >= args.limit:
                        return
                    yield x
            source = capped(source)

        if args.full_text:
            def enriched(it):
                for item in it:
                    extra = client.full_text(item)
                    if extra.get("text"):
                        item["description"] = extra["text"]
                    yield item
            source = enriched(source)

        total = _write(source, args.out, args.format)
        print(f"{total} reclamações → {args.out}")
        return 0

    except ReclameAquiError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrompido", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
