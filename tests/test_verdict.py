from skylink import verdict as V

STREAMS = ["temp", "pressure", "wind", "vibration", "solar"]


def _run(name, skill_by_stream, hash_="h1", raw_off=0, seed=1):
    hours = []
    for st, sk in skill_by_stream.items():
        for hr in range(0, 10 * 3600, 3600):
            noise = 0.02 if hr % 7200 else -0.02
            for model, s in (("lin_lag", sk + noise), ("persistence", 0.0)):
                hours.append([st, "river", model, 60, "normal", "1", hr, 100, 100 * (1 - s), 100.0])
                hours.append([st, "base-sorted", model, 60, "normal", "1", hr, 100, 105 * (1 - s), 100.0])
    c3 = {"river": [{"stream": "pressure", "model": "lin_lag", "horizon": 60, "kind": "front", "events": 2, "censored": 0,
                     "median_s": 120.0, "times_s": [100.0, 140.0]},
                    {"stream": "pressure", "model": "persistence", "horizon": 60, "kind": "front", "events": 2, "censored": 0,
                     "median_s": 10.0, "times_s": [10.0, 10.0]},
                    {"stream": "temp", "model": "lin_lag", "horizon": 60, "kind": "outage_end", "events": 2, "censored": 0,
                     "median_s": 60.0, "times_s": [60.0, 60.0]}],
          "base-sorted": [{"stream": "temp", "model": "lin_lag", "horizon": 60, "kind": "outage_end", "events": 2, "censored": 1,
                           "median_s": float("inf"), "times_s": [1200.0, None]}]}
    c4 = [{"stream": st, "model": "lin_lag", "horizon": 60, "kind": k, "ref": "lin_lag_static", "events": 2,
           "mae_online": mo, "mae_static": 1.0} for st in ("temp", "pressure", "wind") for k, mo in (("step", 0.8), ("stationary", 1.0))]
    return {"run": name, "seed": seed, "speed": 60, "hash": hash_, "emitted": {s: 1000 for s in STREAMS},
            "raw_points": {s: 1000 + (raw_off if s == "wind" else 0) for s in STREAMS}, "warm_until": 0,
            "hours": hours, "c3": c3, "c4": c4}


def test_c1_counts_streams_and_ignores_baselines():
    runs = [_run("a", {"temp": 0.3, "pressure": 0.3, "wind": 0.3, "vibration": 0.05, "solar": -0.1}),
            _run("b", {"temp": 0.3, "pressure": 0.3, "wind": 0.3, "vibration": 0.05, "solar": -0.1}, seed=2)]
    c = V.c1(runs)
    assert c["holds"] and [s for s, v in c["streams"].items() if v["pass"]] == ["pressure", "temp", "wind"]
    assert all(r["model"] != "persistence" for r in c["rows"])
    assert abs(c["streams"]["temp"]["best"]["seed_mean"] - 0.3) < 0.01


def test_c8_voids_a_run_and_decide_skips_it():
    good, bad = _run("a", {s: 0.3 for s in STREAMS}), _run("b", {s: 0.3 for s in STREAMS}, raw_off=-5)
    res = V.decide([good, bad])
    assert res["void"] == ["b"] and res["C8"][1]["diffs"]["wind"] == -5


def test_c3_pools_events_takes_best_river_model_and_censors():
    c = V.c3([_run("a", {"temp": 0.3}), _run("b", {"temp": 0.3})])
    front = c["pairs"]["pressure/front"]
    assert front["events"] == 4 and front["best_median_s"] == 120.0      # persistence (10 s) is not eligible
    assert c["best_base_arm"] == "base-sorted" and not c["pairs"]["temp/outage_end"]["pass"]   # median of 1200, 1200, inf, inf
    assert len(c["edge_control_at_link_ups"]) == 1 and not c["holds"]


def test_c4_c6_c7_and_verdict_lines():
    runs = [_run("a", {s: 0.3 for s in STREAMS}), _run("b", {s: 0.3 for s in STREAMS}, seed=2)]
    assert V.c4(runs)["holds"]                                   # 20 % reduction on three streams, no stationary loss
    c6 = V.c6(runs)
    assert c6["median_ratio"]["base-sorted/normal"] == 1.05 and c6["soft_target_met"]
    rep = V.c7([(runs[0], _run("a2", {s: 0.3 for s in STREAMS}))])
    assert rep["holds"] and rep["pairs"][0]["max_mae_change"] == 0.0
    assert not V.c7([(runs[0], _run("a3", {s: 0.3 for s in STREAMS}, hash_="h2"))])["holds"]
    res = V.decide(runs, resource=[{"cpu_pct": 30, "rss_mb": 200, "step_ms_p99": 5}] * 10)
    assert res["C2"]["holds"] and not res["C3"]["holds"]
    assert res["verdict"] == {"Edge forecasting is valuable": False, "Online learning is justified": True,
                              "The agent layer is justified": False}
    md = V.report_md(res, "test")
    assert "## C1 accuracy" in md and "C5A: not run" in md


def test_c5_from_triage_and_bench():
    triage = {"results": {"rules": {"macro_f1": 0.63}, "constant_real_event": {"macro_f1": 0.17},
                          "gptoss": {"macro_f1": 0.82}, "q14": {"macro_f1": 0.79}}}
    rows = [{"stream": "temp", "h": 60, "arm": a, "ratio_vs_fixed": r} for a, r in (("fixed", 1.0), ("rules", 0.98), ("q8b", 0.95))]
    c = V.c5(triage, {"rows": rows, "stats": {"q8b/propose": {}}})
    assert c["c5a"]["holds"] and c["c5a"]["best"] == "gptoss"
    assert c["c5b"]["holds"] and c["c5c"]["holds"] and c["layer_justified"]
    assert not V.c5(None, None)["layer_justified"]
