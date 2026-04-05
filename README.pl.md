![updates2mqtt](../images/updates2mqtt-dark-256x256.png){ align=left }

# updates2mqtt

[![Rhizomatics Open Source](https://img.shields.io/badge/rhizomatics%20open%20source-lightseagreen)](https://github.com/rhizomatics)

[![PyPI - Version](https://img.shields.io/pypi/v/updates2mqtt)](https://pypi.org/project/updates2mqtt/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/rhizomatics/updates2mqtt)
[![Coverage](https://raw.githubusercontent.com/rhizomatics/updates2mqtt/refs/heads/badges/badges/coverage.svg)](https://updates2mqtt.rhizomatics.org.uk/developer/coverage/)
![Tests](https://raw.githubusercontent.com/rhizomatics/updates2mqtt/refs/heads/badges/badges/tests.svg)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/rhizomatics/updates2mqtt/main.svg)](https://results.pre-commit.ci/latest/github/rhizomatics/updates2mqtt/main)
[![Publish Python 🐍 distribution 📦 to PyPI and TestPyPI](https://github.com/rhizomatics/updates2mqtt/actions/workflows/pypi-publish.yml/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/pypi-publish.yml)
[![Github Deploy](https://github.com/rhizomatics/updates2mqtt/actions/workflows/python-package.yml/badge.svg?branch=main)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/python-package.yml)
[![CodeQL](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql)
[![Dependabot Updates](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates)


<br/>
<br/>


## Podsumowanie

Pozwól Home Assistant informować Cię o nowych aktualizacjach obrazów Docker dla Twoich kontenerów.

![Przykładowa strona aktualizacji Home Assistant](../images/ha_update_detail.png "Home Assistant Updates")![Przykładowe informacje o wydaniu Home Assistant](../images/ha_release_notes.png "Home Assistant Release Notes"){width=300}

Przeczytaj informacje o wydaniu i opcjonalnie kliknij *Aktualizuj*, aby uruchomić Docker *pull* (lub opcjonalnie *build*) i *aktualizację*.

![Przykładowe okno dialogowe aktualizacji Home Assistant](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## Opis

Updates2MQTT okresowo sprawdza dostępność nowych wersji komponentów i publikuje informacje o nowych wersjach do MQTT. Obsługiwane jest automatyczne wykrywanie przez HomeAssistant, dzięki czemu wszystkie aktualizacje można zobaczyć w tym samym miejscu co własne komponenty i dodatki Home Assistant.

Obecnie obsługiwane są tylko kontenery Docker, poprzez sprawdzenie rejestru obrazów (przy użyciu API Docker v1 lub API OCI v2) lub repozytorium git dla źródeł (patrz [Lokalne Kompilacje](local_builds.md)), ze specyficzną obsługą dla Docker, Github Container Registry, Gitlab, Codeberg, Microsoft Container Registry, Quay i LinuxServer Registry, z adaptacyjnym zachowaniem dla większości pozostałych. Projekt jest modularny, więc można dodawać inne źródła aktualizacji, przynajmniej do powiadamiania. Następnym planowanym jest **apt** dla systemów opartych na Debianie.

Komponenty mogą być również aktualizowane, automatycznie lub wyzwalane przez MQTT, na przykład przez naciśnięcie przycisku *Instaluj* w oknie dialogowym aktualizacji HomeAssistant. Ikony i informacje o wydaniu można określić dla lepszego doświadczenia HA. Szczegóły w [Integracja z Home Assistant](home_assistant.md).

Aby rozpocząć, przeczytaj strony [Instalacja](installation.md) i [Konfiguracja](configuration/index.md).

Dla szybkiego przetestowania spróbuj:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

lub bez Dockera, używając [uv](https://docs.astral.sh/uv/)

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

Zawiera też podstawowe narzędzie wiersza poleceń, które przeprowadzi analizę dla pojedynczego działającego kontenera lub pobierze manifesty, bloby JSON i listy tagów ze zdalnych rejestrów (działa z GitHub, GitLab, Codeberg, Quay, LSCR i Microsoft MCR).

## Wsparcie Wydań

Obecnie obsługiwane są tylko kontenery Docker, choć planowane są inne, prawdopodobnie z priorytetem dla `apt`.

| Ekosystem | Wsparcie      | Komentarze                                                                                                        |
|-----------|---------------|-------------------------------------------------------------------------------------------------------------------|
| Docker    | Scan, Fetch   | Fetch to tylko ``docker pull``. Wsparcie restartu tylko dla kontenerów ``docker-compose`` opartych na obrazie.   |

## Heartbeat

Ładunek JSON heartbeat jest opcjonalnie publikowany okresowo do konfigurowalnego tematu MQTT, domyślnie `healthcheck/{node_name}/updates2mqtt`. Zawiera bieżącą wersję Updates2MQTT, nazwę węzła, znacznik czasu i podstawowe statystyki.

## Sprawdzenie Zdrowia (Healthcheck)

Skrypt `healthcheck.sh` jest dołączony do obrazu Docker i może być użyty jako Docker healthcheck, jeśli zmienne środowiskowe kontenera `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` i `MQTT_PASS` są ustawione. Używa pakietu Linux `mosquitto-clients`, który zapewnia polecenie `mosquitto_sub` do subskrybowania tematów.

!!! tip

    Sprawdź, czy healthcheck działa, używając `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` (możesz pominąć `| jq`, jeśli nie masz zainstalowanego jsonquery, ale jest znacznie łatwiejszy do odczytania)

Innym podejściem jest bezpośrednie użycie usługi restarter w Docker Compose, aby wymusić restart, w tym przypadku raz dziennie:

```yaml title="Przykładowa Usługa Compose"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## Kontenery Docelowe

Chociaż `updates2mqtt` wykrywa i monitoruje wszystkie kontenery działające w ramach demona Docker, istnieją opcje dostosowania jego działania dla tych kontenerów.

Odbywa się to poprzez dodanie zmiennych środowiskowych lub etykiet Docker do kontenerów, zazwyczaj w pliku `.env` lub jako opcje `environment` w `docker-compose.yaml`.

### Automatyczne Aktualizacje

Jeśli kontenery Docker powinny być natychmiast aktualizowane bez żadnego potwierdzenia lub wyzwalacza, np. z okna dialogowego aktualizacji HomeAssistant, ustaw zmienną środowiskową `UPD2MQTT_UPDATE` w kontenerze docelowym na `Auto` (domyślnie `Passive`). Jeśli chcesz aktualizować bez publikowania do MQTT i widoczności dla Home Assistant, użyj `Silent`.

```yaml title="Przykładowy Fragment Compose"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

Automatyczne aktualizacje mogą dotyczyć również lokalnych kompilacji, gdzie zdefiniowano `git_repo_path` - jeśli dostępne są zdalne commity do pobrania, zostaną wykonane `git pull`, `docker compose build` i `docker compose up`.


## Powiązane Projekty

Inne przydatne aplikacje do self-hostingu z pomocą MQTT:

- [psmqtt](https://github.com/eschava/psmqtt) - Raportuj stan systemu i metryki przez MQTT

Znajdź więcej na [awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt)

Dla bardziej zaawansowanego menedżera aktualizacji skupionego na Dockerze, wypróbuj [What's Up Docker](https://getwud.github.io/wud/)

## Rozwój

Ten komponent opiera się na kilku pakietach open source:

- [docker-py](https://docker-py.readthedocs.io/en/stable/) SDK Python do dostępu do API Docker
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) klient MQTT
- [OmegaConf](https://omegaconf.readthedocs.io) do konfiguracji i walidacji
- [structlog](https://www.structlog.org/en/stable/) do strukturalnego logowania i [rich](https://rich.readthedocs.io/en/stable/) do lepszego raportowania wyjątków
- [hishel](https://hishel.com/) do buforowania metadanych
- [httpx](https://www.python-httpx.org) do pobierania metadanych
- Narzędzia Astral [uv](https://docs.astral.sh/uv/) i [ruff](https://docs.astral.sh/ruff/) do rozwoju i budowania
- [pytest](https://docs.pytest.org/en/stable/) i pomocnicze wtyczki do automatycznego testowania
- [usingversion](https://pypi.org/project/usingversion/) do logowania informacji o bieżącej wersji

## Rhizomatics Open Source dla Home Assistant

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - Automatyczne uzbrajanie i rozbrajanie paneli sterowania alarmem Home Assistant za pomocą fizycznych przycisków, obecności, kalendarzy, słońca i innych
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - Przechwytywanie zdarzeń OpenTelemetry (OTLP) i Syslog dla Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Ujednolicone powiadamianie dla łatwego przesyłania wiadomości wielokanałowych, w tym zaawansowanej integracji dzwonków i kamer bezpieczeństwa.


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - Integracja z kamerami ANPR/ALPR do tablic rejestracyjnych przez system plików (NAS/FTP) do MQTT z opcjonalną analizą obrazu i integracją z UK DVLA.
