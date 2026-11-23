"""The trigger-gate corpus came from a real inbox: no address, host or IP in it may be a real one."""

import ipaddress
from pathlib import Path
import re

import pytest
from scripts.evals.suites.trigger_gate import DATA_DIR

RESERVED_DOMAINS = ("example", "example.com", "example.net", "example.org")
DOCUMENTATION_NETS = tuple(
    ipaddress.ip_network(net) for net in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
)
ADDRESS = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
URL_HOST = re.compile(r"https?://([^/\s\"'<>\])?:#]+)")
IPV4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")
FILES = sorted(p for p in DATA_DIR.rglob("*") if p.suffix in {".yaml", ".jsonl"})


def _reserved(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith(f".{d}") for d in RESERVED_DOMAINS)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_email_address_and_link_is_on_a_reserved_domain(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    hosts = ADDRESS.findall(text) + URL_HOST.findall(text)
    assert sorted({h for h in hosts if not _reserved(h)}) == []


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_ip_address_is_a_documentation_address(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    real = []
    for dotted in IPV4.findall(text):
        try:
            ip = ipaddress.ip_address(dotted)
        except ValueError:
            real.append(dotted)
            continue
        if not any(ip in net for net in DOCUMENTATION_NETS):
            real.append(dotted)
    assert real == []
