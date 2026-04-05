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


## Resumo

Deixe o Home Assistant informá-lo sobre novas atualizações de imagens Docker para os seus containers.

![Exemplo de página de atualização do Home Assistant](../images/ha_update_detail.png "Home Assistant Updates")![Exemplo de notas de versão do Home Assistant](../images/ha_release_notes.png "Home Assistant Release Notes"){width=300}

Leia as notas de versão e, opcionalmente, clique em *Atualizar* para acionar um Docker *pull* (ou opcionalmente *build*) e *atualização*.

![Exemplo de diálogo de atualização do Home Assistant](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## Descrição

O Updates2MQTT verifica periodicamente a disponibilidade de novas versões dos componentes e publica as informações sobre novas versões via MQTT. O descobrimento automático do HomeAssistant é suportado, de modo que todas as atualizações podem ser vistas no mesmo lugar que os próprios componentes e add-ins do Home Assistant.

Atualmente, apenas containers Docker são suportados, seja por meio de uma verificação de registro de imagens (usando as APIs Docker v1 ou a API OCI v2) ou um repositório git para o código-fonte (consulte [Builds Locais](local_builds.md)), com tratamento específico para Docker, Github Container Registry, Gitlab, Codeberg, Microsoft Container Registry, Quay e LinuxServer Registry, com comportamento adaptativo para a maioria dos outros. O design é modular, portanto outras fontes de atualização podem ser adicionadas, pelo menos para notificação. A próxima prevista é o **apt** para sistemas baseados em Debian.

Os componentes também podem ser atualizados, automaticamente ou acionados via MQTT, por exemplo, clicando no botão *Instalar* no diálogo de atualização do HomeAssistant. Ícones e notas de versão podem ser especificados para uma melhor experiência no HA. Consulte [Integração com o Home Assistant](home_assistant.md) para detalhes.

Para começar, leia as páginas [Instalação](installation.md) e [Configuração](configuration/index.md).

Para um teste rápido, experimente:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

ou sem Docker, usando [uv](https://docs.astral.sh/uv/)

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

Também inclui uma ferramenta básica de linha de comando que realizará a análise de um único container em execução, ou buscará manifestos, blobs JSON e listas de tags de registros remotos (comprovadamente funciona com GitHub, GitLab, Codeberg, Quay, LSCR e Microsoft MCR).

## Suporte a Versões

Atualmente, apenas containers Docker são suportados, embora outros estejam planejados, provavelmente com prioridade para `apt`.

| Ecossistema | Suporte       | Comentários                                                                                                          |
|-------------|---------------|----------------------------------------------------------------------------------------------------------------------|
| Docker      | Scan, Fetch   | Fetch é apenas ``docker pull``. Suporte a reinicialização apenas para containers baseados em imagem ``docker-compose``. |

## Heartbeat

Um payload JSON de heartbeat é opcionalmente publicado periodicamente em um tópico MQTT configurável, com padrão `healthcheck/{node_name}/updates2mqtt`. Contém a versão atual do Updates2MQTT, o nome do nó, um timestamp e algumas estatísticas básicas.

## Verificação de Saúde (Healthcheck)

Um script `healthcheck.sh` está incluído na imagem Docker e pode ser usado como healthcheck do Docker se as variáveis de ambiente do container `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` e `MQTT_PASS` estiverem definidas. Utiliza o pacote Linux `mosquitto-clients` que fornece o comando `mosquitto_sub` para subscrever tópicos.

!!! tip

    Verifique se o healthcheck está funcionando usando `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` (pode omitir `| jq` se não tiver o jsonquery instalado, mas é muito mais fácil de ler com ele)

Outra abordagem é usar um serviço restarter diretamente no Docker Compose para forçar uma reinicialização, neste caso uma vez por dia:

```yaml title="Exemplo de Serviço Compose"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## Containers Alvo

Embora o `updates2mqtt` descubra e monitore todos os containers em execução no daemon Docker, existem algumas opções para ajustar seu funcionamento nesses containers.

Isso é feito adicionando variáveis de ambiente ou labels Docker aos containers, normalmente dentro de um arquivo `.env` ou como opções `environment` dentro do `docker-compose.yaml`.

### Atualizações Automatizadas

Se os containers Docker devem ser atualizados imediatamente, sem qualquer confirmação ou acionamento, por exemplo, a partir do diálogo de atualização do HomeAssistant, defina a variável de ambiente `UPD2MQTT_UPDATE` no container alvo como `Auto` (o padrão é `Passive`). Se quiser que ele atualize sem publicar no MQTT e sem ser visível para o Home Assistant, use `Silent`.

```yaml title="Exemplo de Trecho Compose"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

As atualizações automatizadas também podem se aplicar a builds locais, onde um `git_repo_path` foi definido - se houver commits remotos disponíveis para pull, então `git pull`, `docker compose build` e `docker compose up` serão executados.


## Projetos Relacionados

Outros aplicativos úteis para self-hosting com a ajuda do MQTT:

- [psmqtt](https://github.com/eschava/psmqtt) - Reportar saúde do sistema e métricas via MQTT

Encontre mais em [awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt)

Para um gerenciador de atualizações mais poderoso focado em Docker, experimente [What's Up Docker](https://getwud.github.io/wud/)

## Desenvolvimento

Este componente depende de vários pacotes de código aberto:

- [docker-py](https://docker-py.readthedocs.io/en/stable/) SDK Python para acesso às APIs Docker
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) cliente MQTT
- [OmegaConf](https://omegaconf.readthedocs.io) para configuração e validação
- [structlog](https://www.structlog.org/en/stable/) para logging estruturado e [rich](https://rich.readthedocs.io/en/stable/) para melhor relatório de exceções
- [hishel](https://hishel.com/) para cache de metadados
- [httpx](https://www.python-httpx.org) para recuperar metadados
- As ferramentas Astral [uv](https://docs.astral.sh/uv/) e [ruff](https://docs.astral.sh/ruff/) para desenvolvimento e build
- [pytest](https://docs.pytest.org/en/stable/) e add-ins de suporte para testes automatizados
- [usingversion](https://pypi.org/project/usingversion/) para registrar informações da versão atual

## Rhizomatics Open Source para Home Assistant

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - Armar e desarmar automaticamente painéis de controle de alarme do Home Assistant usando botões físicos, presença, calendários, sol e muito mais
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - Captura de eventos OpenTelemetry (OTLP) e Syslog para Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Notificação unificada para mensagens multicanais fáceis, incluindo poderosa integração de campainha e câmera de segurança.


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - Integração com câmeras ANPR/ALPR de placas de veículos via sistema de arquivos (NAS/FTP) para MQTT com análise de imagens opcional e integração com a DVLA do Reino Unido.
