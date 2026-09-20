# reclameaqui-client

Cliente Python para a API interna do [Reclame Aqui](https://www.reclameaqui.com.br).
Coleta reclamações de qualquer empresa pelo slug, sem navegador e sem raspar HTML.

Os projetos que existem hoje fazem scraping do HTML com Selenium e seletores CSS
gerados por `styled-components` — que mudam a cada deploy do site. Este aqui
conversa com os mesmos endpoints JSON que o próprio site consome.

```bash
pip install -r requirements.txt

python -m reclameaqui stats nubank
python -m reclameaqui collect magazine-luiza --limit 200 --out saida.jsonl
```

**Coleta completa**, em dois passos — o primeiro descobre o catálogo de tipos de
problema, o segundo o usa para furar o teto de ~500 por listagem:

```bash
python -m reclameaqui types nubank --scan --out tipos.json
python -m reclameaqui collect nubank --all --types tipos.json \
    --full-text --out nubank.jsonl -v
```

O `--scan` leva cerca de 25 minutos e só precisa ser feito uma vez por empresa.
Numa empresa com 18.520 reclamações, esse fluxo recuperou mais de 10.000; sem o
catálogo, a listagem geral entrega 500.

```python
from reclameaqui import Client

c = Client("quinto-andar")
print(c.stats())

for r in c.complaints(limit=50):
    print(r["created"], r["title"])
```

---

## A API, documentada

Nada disso é oficial nem documentado pelo Reclame Aqui. Foi levantado
observando o tráfego do site. Pode mudar sem aviso.

### Resolver a empresa

```
GET https://iosite.reclameaqui.com.br/raichu-io-site-v1/company/shortname/{slug}
```

O `slug` é o trecho em `reclameaqui.com.br/empresa/<slug>/`. Devolve o cadastro
público: `id`, `companyName`, `complainCount`, `presences`, `categories` e o
`companyIndexes`, que traz os indicadores agregados (total de reclamações, não
respondidas, nota, tempo médio de resposta).

Outros caminhos sob `iosite` (`/company/{id}/public`, `/complain/{id}`) respondem
**200 com o HTML genérico do site**, não JSON. É uma rota catch-all: se receber
70 KB começando com `<!DOCTYPE html>`, o endpoint não existe.

### Buscar reclamações

```
GET https://iosearch.reclameaqui.com.br/raichu-io-site-search-v1
    /query/companyComplains/{tamanho}/{offset}?company={id}
```

As reclamações vêm em `complainResult.complains.data`. Cada item traz
`title`, `description`, `created`, `status`, `solved`, `evaluated`,
`problemType`, `productType`, `userCity`, `userState`, `url` — e também
`userName`, `userEmail`, `ip` e `phones`, que esta biblioteca descarta por
padrão (veja *Privacidade*).

Três limites que não estão documentados em lugar nenhum e que definem como usar:

**1. O lote máximo é 10.** Pedir `/query/companyComplains/50/0` devolve 200 com
corpo vazio, não erro. Qualquer valor acima de 10 falha silenciosamente.

**2. Cada listagem satura em ~500 itens.** O `offset` continua aceitando valores
maiores, mas para de trazer novidade. É o mesmo teto das 50 páginas da interface
web.

**3. O filtro é `problemType`.** Aceita o ID de 16 dígitos com zeros à esquerda
(`0000000000000381`). Testamos `problema`, `problem`, `problemTypes` e
`problemId` — todos devolvem 500.

O terceiro limite resolve o segundo: **como o teto é por listagem e não por
empresa, iterar tipo por tipo multiplica o alcance.** Numa empresa com 18.520
reclamações, a listagem geral dá 500; percorrendo 81 tipos de problema chega-se
a mais de 10.000.

```python
types = c.scan_problem_types(end=1500)
for r in c.collect_all(problem_types=types):
    ...
```

Pela linha de comando, `types --scan --out tipos.json` seguido de
`collect --all --types tipos.json`.

### O catálogo de tipos de problema

`company.presences[].problemTypes` traz nome e ID, mas só de um subconjunto — no
caso testado, 12 de 81. Não há endpoint que liste o resto.

A saída é força bruta: os IDs são inteiros pequenos preenchidos com zeros
(`75`, `381`, `1227`), então testar de 1 a 1500 encontra o catálogo completo.
Uma requisição por ID, cerca de 25 minutos.

```bash
python -m reclameaqui types quinto-andar --scan --out tipos.json
```

No caso testado, o cadastro trazia 12 tipos e o scan encontrou 81.

### Texto completo

A busca devolve um `description` truncado, com cerca de 130 caracteres. O texto
integral (~1.300 em média) só existe na página pública da reclamação.

O campo `url` traz apenas o slug da reclamação (`titulo-da-reclamacao_HASH`),
sem domínio nem caminho da empresa. `Client.complaint_url()` monta a URL real.

```bash
python -m reclameaqui collect quinto-andar --limit 100 --full-text
```

Custa uma requisição por reclamação, então use com parcimônia.

### Cloudflare

O site é protegido, mas de forma assimétrica: **`requests` passa e o Chrome
headless é barrado.** Selenium sem interface recebe o challenge e nunca chega
ao conteúdo. Não há motivo para usar navegador aqui.

---

## Privacidade

O payload traz dado pessoal de quem reclamou: nome, e-mail, IP e telefone.

Esta biblioteca **remove esses campos antes de qualquer gravação**. O parâmetro
`keep_pii=True` existe para quem tem base legal para tratá-los; o padrão é
descartar. O CLI nunca os grava.

Recomendações, não garantias jurídicas: não redistribua os textos coletados
(são de autoria de quem reclamou), guarde só o que a sua pergunta exige, e trate
qualquer publicação em agregado.

---

## Uso responsável

Os Termos de Uso do Reclame Aqui restringem coleta automatizada. Este projeto é
publicado para fins de pesquisa e interoperabilidade; avaliar a base legal do
seu uso é com você.

O intervalo padrão de 1,5 a 3 segundos entre requisições é deliberado. Reduzir
não te dá muito tempo de volta — a coleta é limitada pelo teto de 500, não pela
velocidade — e transforma pesquisa discreta em carga sobre um serviço de
terceiro. Se for ajustar, ajuste para cima.

---

## Instalação

```bash
git clone https://github.com/eduardosuranyi/reclameaqui-client
cd reclameaqui-client
pip install -r requirements.txt
```

Python 3.10+. Só `requests`; `beautifulsoup4` apenas para `--full-text`.

## Licença

MIT.
