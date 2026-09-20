"""Exemplo: coleta e sumariza reclamações de uma empresa.

    python examples/analise_basica.py nubank
"""
import sys
from collections import Counter

from reclameaqui import Client


def main(slug: str, limit: int = 300) -> None:
    client = Client(slug)
    info = client.company()
    print(f"{info['companyName']} (id {info['id']})\n")

    for key, value in client.stats().items():
        print(f"  {key:<20} {value}")

    print(f"\ncoletando até {limit} reclamações…")
    items = list(client.complaints(limit=limit))

    solved = sum(1 for i in items if i.get("solved"))
    print(f"\n{len(items)} coletadas | {solved} resolvidas "
          f"({solved / max(len(items), 1) * 100:.1f}%)")

    print("\nestados:")
    for uf, n in Counter(i.get("userState") for i in items).most_common(10):
        print(f"  {uf}  {n}")

    print("\nmais recentes:")
    for i in items[:5]:
        print(f"  {i.get('created', '')[:10]}  {i.get('title', '')[:70]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "quinto-andar")
