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


## सारांश

Home Assistant को आपके कंटेनरों के लिए Docker इमेज के नए अपडेट के बारे में सूचित करने दें।

![Home Assistant अपडेट पृष्ठ का उदाहरण](../images/ha_update_detail.png "Home Assistant Updates")![Home Assistant रिलीज़ नोट्स का उदाहरण](../images/ha_release_notes.png "Home Assistant Release Notes"){width=300}

रिलीज़ नोट्स पढ़ें, और वैकल्पिक रूप से Docker *pull* (या वैकल्पिक रूप से *build*) और *अपडेट* ट्रिगर करने के लिए *अपडेट* पर क्लिक करें।

![Home Assistant अपडेट डायलॉग का उदाहरण](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## विवरण

Updates2MQTT समय-समय पर उपलब्ध घटकों के नए संस्करणों की जांच करता है, और नई संस्करण जानकारी MQTT पर प्रकाशित करता है। HomeAssistant ऑटो डिस्कवरी समर्थित है, इसलिए सभी अपडेट Home Assistant के अपने घटकों और ऐड-इन्स के समान स्थान पर देखे जा सकते हैं।

वर्तमान में केवल Docker कंटेनर समर्थित हैं, या तो इमेज रजिस्ट्री जांच (v1 Docker APIs या OCI v2 API का उपयोग करके), या स्रोत के लिए एक git रेपो (देखें [स्थानीय बिल्ड](local_builds.md)) के माध्यम से, Docker, Github Container Registry, Gitlab, Codeberg, Microsoft Container Registry, Quay और LinuxServer Registry के लिए विशिष्ट हैंडलिंग के साथ, अधिकांश अन्य के लिए अनुकूली व्यवहार के साथ। डिज़ाइन मॉड्यूलर है, इसलिए अन्य अपडेट स्रोत जोड़े जा सकते हैं, कम से कम अधिसूचना के लिए। अगला अपेक्षित Debian आधारित सिस्टम के लिए **apt** है।

घटकों को भी अपडेट किया जा सकता है, या तो स्वचालित रूप से या MQTT के माध्यम से ट्रिगर किया जाकर, उदाहरण के लिए HomeAssistant अपडेट डायलॉग में *इंस्टॉल* बटन दबाकर। बेहतर HA अनुभव के लिए आइकन और रिलीज़ नोट्स निर्दिष्ट किए जा सकते हैं। विवरण के लिए [Home Assistant एकीकरण](home_assistant.md) देखें।

शुरू करने के लिए, [इंस्टॉलेशन](installation.md) और [कॉन्फ़िगरेशन](configuration/index.md) पृष्ठ पढ़ें।

त्वरित परीक्षण के लिए, यह आज़माएं:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

या Docker के बिना, [uv](https://docs.astral.sh/uv/) का उपयोग करके

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

इसमें एक बेसिक कमांड लाइन टूल भी है जो एकल चलते कंटेनर के लिए विश्लेषण करेगा, या रिमोट रजिस्ट्री से मैनिफेस्ट, JSON ब्लॉब और टैग की सूचियां प्राप्त करेगा (GitHub, GitLab, Codeberg, Quay, LSCR और Microsoft MCR के साथ काम करने के लिए जाना जाता है)।

## रिलीज़ समर्थन

वर्तमान में केवल Docker कंटेनर समर्थित हैं, हालांकि अन्य की योजना है, संभवतः `apt` को प्राथमिकता के साथ।

| इकोसिस्टम | समर्थन        | टिप्पणियां                                                                                                         |
|-----------|---------------|--------------------------------------------------------------------------------------------------------------------|
| Docker    | Scan, Fetch   | Fetch केवल ``docker pull`` है। केवल ``docker-compose`` इमेज आधारित कंटेनरों के लिए पुनरारंभ समर्थन।            |

## हार्टबीट

एक हार्टबीट JSON पेलोड वैकल्पिक रूप से एक कॉन्फ़िगर करने योग्य MQTT टॉपिक पर समय-समय पर प्रकाशित किया जाता है, जो डिफ़ॉल्ट रूप से `healthcheck/{node_name}/updates2mqtt` है। इसमें Updates2MQTT का वर्तमान संस्करण, नोड नाम, एक टाइमस्टैम्प और कुछ बुनियादी आंकड़े हैं।

## हेल्थचेक

एक `healthcheck.sh` स्क्रिप्ट Docker इमेज में शामिल है, और इसे Docker हेल्थचेक के रूप में उपयोग किया जा सकता है, यदि कंटेनर पर्यावरण चर `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` और `MQTT_PASS` सेट हैं। यह `mosquitto-clients` Linux पैकेज का उपयोग करता है जो टॉपिक की सदस्यता लेने के लिए `mosquitto_sub` कमांड प्रदान करता है।

!!! tip

    `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` का उपयोग करके जांचें कि हेल्थचेक काम कर रहा है (यदि आपके पास jsonquery इंस्टॉल नहीं है तो `| jq` छोड़ सकते हैं, लेकिन इसके साथ पढ़ना बहुत आसान है)

एक और तरीका है Docker Compose में सीधे एक रिस्टार्टर सेवा का उपयोग करना जो पुनरारंभ को बाध्य करे, इस मामले में दिन में एक बार:

```yaml title="उदाहरण Compose सेवा"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## लक्ष्य कंटेनर

जबकि `updates2mqtt` Docker डेमॉन के तहत चल रहे सभी कंटेनरों की खोज और निगरानी करेगा, उन कंटेनरों के लिए इसके काम करने के तरीके को ट्यून करने के कुछ विकल्प हैं।

ये कंटेनरों में पर्यावरण चर या Docker लेबल जोड़कर होते हैं, आमतौर पर एक `.env` फ़ाइल के अंदर, या `docker-compose.yaml` के अंदर `environment` विकल्पों के रूप में।

### स्वचालित अपडेट

यदि Docker कंटेनरों को किसी पुष्टि या ट्रिगर के बिना तुरंत अपडेट किया जाना चाहिए, जैसे कि HomeAssistant अपडेट डायलॉग से, तो लक्ष्य कंटेनर में पर्यावरण चर `UPD2MQTT_UPDATE` को `Auto` पर सेट करें (यह डिफ़ॉल्ट रूप से `Passive` है)। यदि आप MQTT पर प्रकाशित किए बिना और Home Assistant को दिखाई दिए बिना अपडेट करना चाहते हैं, तो `Silent` का उपयोग करें।

```yaml title="उदाहरण Compose स्निपेट"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

स्वचालित अपडेट स्थानीय बिल्ड पर भी लागू हो सकते हैं, जहां एक `git_repo_path` परिभाषित किया गया है - यदि pull करने के लिए रिमोट कमिट उपलब्ध हैं, तो `git pull`, `docker compose build` और `docker compose up` निष्पादित किए जाएंगे।


## संबंधित प्रोजेक्ट

MQTT की मदद से सेल्फ-होस्टिंग के लिए अन्य उपयोगी ऐप्स:

- [psmqtt](https://github.com/eschava/psmqtt) - MQTT के माध्यम से सिस्टम स्वास्थ्य और मेट्रिक्स रिपोर्ट करें

[awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt) पर और खोजें

अधिक शक्तिशाली Docker-केंद्रित अपडेट मैनेजर के लिए, [What's Up Docker](https://getwud.github.io/wud/) आज़माएं

## विकास

यह घटक कई ओपन सोर्स पैकेज पर निर्भर करता है:

- [docker-py](https://docker-py.readthedocs.io/en/stable/) Docker APIs तक पहुंच के लिए Python SDK
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) MQTT क्लाइंट
- [OmegaConf](https://omegaconf.readthedocs.io) कॉन्फ़िगरेशन और सत्यापन के लिए
- [structlog](https://www.structlog.org/en/stable/) संरचित लॉगिंग के लिए और [rich](https://rich.readthedocs.io/en/stable/) बेहतर अपवाद रिपोर्टिंग के लिए
- [hishel](https://hishel.com/) मेटाडेटा कैशिंग के लिए
- [httpx](https://www.python-httpx.org) मेटाडेटा प्राप्त करने के लिए
- Astral [uv](https://docs.astral.sh/uv/) और [ruff](https://docs.astral.sh/ruff/) टूल्स विकास और बिल्ड के लिए
- [pytest](https://docs.pytest.org/en/stable/) और स्वचालित परीक्षण के लिए सहायक ऐड-इन
- [usingversion](https://pypi.org/project/usingversion/) वर्तमान संस्करण जानकारी लॉग करने के लिए

## Home Assistant के लिए Rhizomatics Open Source

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - भौतिक बटन, उपस्थिति, कैलेंडर, सूर्य और अधिक का उपयोग करके Home Assistant अलार्म नियंत्रण पैनल को स्वचालित रूप से सशस्त्र और निरस्त्र करें
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - Home Assistant के लिए OpenTelemetry (OTLP) और Syslog इवेंट कैप्चर
- [Supernotify](https://supernotify.rhizomatics.org.uk) - शक्तिशाली चाइम और सुरक्षा कैमरा एकीकरण सहित आसान मल्टी-चैनल मैसेजिंग के लिए एकीकृत अधिसूचना।


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - वैकल्पिक इमेज विश्लेषण और UK DVLA एकीकरण के साथ फ़ाइल सिस्टम (NAS/FTP) से MQTT तक ANPR/ALPR लाइसेंस प्लेट कैमरों के साथ एकीकरण।
