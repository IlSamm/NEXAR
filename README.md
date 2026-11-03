<p align="center"><img src="docs/banner.jpg" alt="NEXAR"></p>

<p align="center"><b>Il tuo PC Windows, sotto controllo da scrivania, telefono e Telegram.</b></p>

NEXAR abbassa i consumi mentre Codex e Claude lavorano, misura quanto assorbe il PC dalla presa e comanda luci, ventole e accensione: dall'app sul PC, dalla Mini App di Telegram o dal bot.

## Cosa fa

- **Modalità AI ECO · Normale · Gaming**: piano energetico di Windows, LED e ventole in un tocco. AI ECO parte da sola quando Codex o Claude lavorano.
- **Consumo reale alla presa**: processore e scheda video misurati dai sensori, il resto (scheda madre, RAM, dischi, ventole, pompa, LED, periferiche) stimato componente per componente, con la curva di efficienza dell'alimentatore. Watt, ampere a 230 V, kWh e costo del giorno e del mese, previsione di fine mese.
- **LED (OpenRGB)**: un colore per tutti o per dispositivo, luminosità, palette di colori salvati.
- **Ventole (Fan Control)**: spente, silenziose, normali o al massimo, solo le ventole del case. Radiatore e pompa AIO restano sempre al BIOS; con CPU o GPU calde tornano normali da sole.
- **Accensione**: sospendi, riavvia, spegni, blocca, timer e "spegni quando l'AI ha finito". Accensione da spento con Wake-on-LAN tramite un piccolo relay su Umbrel.
- **Telegram**: bot privato abbinato con codice temporaneo, Mini App con la dashboard completa (tramite Cloudflare Tunnel), avvisi di temperatura.
- **Si collega da solo**: trova e configura OpenRGB, Fan Control, LibreHardwareMonitor, GPU NVIDIA e cloudflared; quelli mancanti si installano con un clic (winget).
- **Si aggiorna da solo**: controlla le release di questo repository, scarica lo zip, verifica l'hash SHA-256 e si riavvia con la nuova versione.

## Installazione

1. Scarica `NEXAR-x.y.z-win64.zip` dall'ultima [release](https://github.com/IlSamm/NEXAR/releases/latest).
2. Estrai la cartella `NEXAR` dove preferisci (per esempio `C:\NEXAR`) e avvia `NEXAR.exe`.
3. Apri **Collegamenti**: NEXAR cerca i programmi e propone di installare quelli che mancano.
4. In **Impostazioni → Telegram** incolla il token del tuo bot (da [@BotFather](https://t.me/BotFather)) e invia al bot il codice `/pair` mostrato.

I dati personali (chiave di accesso, token del bot, consumi) stanno in `%LOCALAPPDATA%\NEXAR` e non vengono mai toccati dagli aggiornamenti né caricati qui.

## Requisiti

Windows 10/11 · WebView2 (già presente su Windows 11) · per luci e ventole: OpenRGB, Fan Control, LibreHardwareMonitor (installabili dall'app).

## Sviluppo

```powershell
py -m pip install -r requirements-dev.txt
py -m pytest -q
.\CREA_EXE.ps1                                  # compila dist\NEXAR\NEXAR.exe
.\release.ps1 1.0.1 "Cosa cambia"               # test, exe, zip + hash, tag e release GitHub
```

`release.ps1` pubblica lo zip e il file `.sha256`: le app installate lo trovano entro 6 ore (oppure subito con *Controlla ora* o `/aggiorna` su Telegram).
