#!/usr/bin/env python3
"""Assemble nodered/flows.json from nodered/functions/*.js so the logic stays reviewable code."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "nodered"
src = lambda n: (root / "functions" / f"{n}.js").read_text()
common = src("common")
TAB = "skylink_tab"


def fn(id, name, body, outputs, wires, x, y, with_common=False):
    return {"id": id, "type": "function", "z": TAB, "name": name, "func": (common + "\n" if with_common else "") + body,
            "outputs": outputs, "timeout": 0, "noerr": 0, "initialize": "", "finalize": "", "libs": [],
            "x": x, "y": y, "wires": wires}


def http_in(id, method, url, wires, y):
    return {"id": id, "type": "http in", "z": TAB, "name": f"{method.upper()} {url}", "url": url, "method": method,
            "upload": False, "swaggerDoc": "", "x": 130, "y": y, "wires": [wires]}


def http_out(id, y, status=""):
    return {"id": id, "type": "http response", "z": TAB, "name": "", "statusCode": status, "headers": {},
            "x": 950, "y": y, "wires": []}


def request(id, name, url, y, x=700):
    return {"id": id, "type": "http request", "z": TAB, "name": name, "method": "use", "ret": "obj" if name.startswith(("edge", "after")) else "txt", "paytoqs": "ignore", "url": url, "tls": "", "persist": False,
            "proxy": "", "insecureHTTPParser": False, "authType": "", "senderr": False, "headers": [],
            "x": x, "y": y, "wires": [[]]}


def delay(id, name, y, wires):
    return {"id": id, "type": "delay", "z": TAB, "name": name, "pauseType": "rate", "timeout": "5",
            "timeoutUnits": "seconds", "rate": "20", "nbRateUnits": "1", "rateUnits": "second",
            "randomFirst": "1", "randomLast": "5", "randomUnits": "seconds", "drop": False, "allowrate": False,
            "outputs": 1, "x": 480, "y": y, "wires": [wires]}


nodes = [
    {"id": TAB, "type": "tab", "label": "Skylink edge", "disabled": False, "info": "Ingest, Skylink outage model, store-and-forward, backfill."},
    http_in("in_ingest", "post", "/ingest", ["gate"], 100),
    fn("gate", "skylink gate", src("gate"), 5,
       [["req_edge"], ["to_lp"], [], ["delay_influx"], ["hold_base"]], 300, 100, True),
    request("req_edge", "edge tap -> river", "", 40),
    fn("base_live", "ordered live msgs to base arms", src("base_live"), 2, [["req_base_live"], ["resp_ingest"]], 500, 40),
    request("req_base_live", "base live (ordered)", "", 40, 780),
    http_out("resp_ingest", 40, "202"),
    request("req_base", "after Skylink -> river base", "", 180, 700),
    delay("delay_influx", "backfill rate limit (influx)", 240, ["to_lp"]),
    {"id": "hold_base", "type": "delay", "z": TAB, "name": "let the replay notice land first", "pauseType": "delay",
     "timeout": "300", "timeoutUnits": "milliseconds", "rate": "1", "nbRateUnits": "1", "rateUnits": "second",
     "randomFirst": "1", "randomLast": "5", "randomUnits": "seconds", "drop": False, "allowrate": False,
     "outputs": 1, "x": 300, "y": 300, "wires": [["delay_base"]]},
    delay("delay_base", "backfill rate limit (base)", 300, ["req_base"]),
    fn("to_lp", "build influx write", src("to_lp"), 1, [["req_influx"]], 500, 380, True),
    request("req_influx", "influx raw", "", 380, 740),
    fn("check_write", "check write", src("check_write"), 1, [[]], 940, 380),
    http_in("in_config", "post", "/config", ["cfg_fn"], 500),
    fn("cfg_fn", "configure run", src("config"), 2, [["resp_config"], ["to_lp"]], 330, 500, True),
    http_out("resp_config", 500),
    http_in("in_state", "get", "/state", ["state_fn"], 580),
    fn("state_fn", "link state", src("state"), 1, [["resp_state"]], 330, 580),
    http_out("resp_state", 580),
]
by = {n["id"]: n for n in nodes}
by["req_edge"]["wires"] = [["base_live"]]
by["req_base_live"]["wires"] = [["resp_ingest"]]
by["req_influx"]["wires"] = [["check_write"]]
by["req_influx"]["name"] = "influx raw (url from msg)"
(root / "flows.json").write_text(json.dumps(nodes, indent=1) + "\n")
print(f"wrote {len(nodes)} nodes")
