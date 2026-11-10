#!/usr/bin/env python3
"""Check the required Android device/AVD gate, then inventory VPN and proxy capabilities."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import urllib.parse
import urllib.request

from apk_utils import find_tool, public_url, sdk_roots, write_json
from progress import emit


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return {"returncode": r.returncode, "stdout": r.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": type(exc).__name__}


def properties(path):
    if not path.is_file():
        return {}
    return dict(line.strip().split("=", 1) for line in path.read_text().splitlines()
                if "=" in line and not line.lstrip().startswith("#"))


def avd_inventory(names, sdk=None):
    homes = [os.environ.get("ANDROID_AVD_HOME")]
    if os.environ.get("ANDROID_EMULATOR_HOME"):
        homes.append(str(Path(os.environ["ANDROID_EMULATOR_HOME"]) / "avd"))
    if os.environ.get("ANDROID_USER_HOME"):
        homes.append(str(Path(os.environ["ANDROID_USER_HOME"]) / "avd"))
    if os.environ.get("ANDROID_SDK_HOME"):
        homes.append(str(Path(os.environ["ANDROID_SDK_HOME"]) / ".android/avd"))
    homes.append(str(Path.home() / ".android/avd"))
    roots = list(dict.fromkeys(Path(p).expanduser() for p in homes if p))
    results = []
    for name in names:
        item = {"name": name, "configured": False, "boot_verified": False}
        for home in roots:
            meta = properties(home / (name + ".ini"))
            directory = Path(meta["path"]).expanduser() if meta.get("path") else home / (name + ".avd")
            cfg = properties(directory / "config.ini")
            if not cfg:
                continue
            item.update(config=str(directory / "config.ini"), abi=cfg.get("abi.type"),
                        google_play=cfg.get("PlayStore.enabled", "false").lower() == "true")
            image = cfg.get("image.sysdir.1")
            image_dirs = ([Path(image).expanduser()] if image and Path(image).is_absolute() else
                          [root / image for root in sdk_roots(sdk)] if image else [])
            for image_dir in image_dirs:
                missing = [n for n in ("system.img", "ramdisk.img") if not (image_dir / n).is_file()]
                if not any((image_dir / n).is_file() for n in ("kernel-ranchu", "kernel-qemu")):
                    missing.append("kernel-ranchu or kernel-qemu")
                item.update(image_directory=str(image_dir), missing_image_files=missing)
                if not missing:
                    item["configured"] = True
                    break
            if not image_dirs:
                item["reason"] = "system_image_not_found"
            break
        if "config" not in item:
            item["reason"] = "avd_configuration_not_found"
        results.append(item)
    return results


def device_check(tools, sdk=None):
    result = {"connected_devices": [], "avds": [], "device_gate": {"status": "failed", "errors": []}}
    gate = result["device_gate"]
    if tools["adb"]:
        listing = run([tools["adb"], "devices", "-l"])
        result["adb_devices"] = listing
        if listing.get("returncode") != 0:
            gate["errors"].append({"code": "ADB_CHECK_FAILED", "message": "ADB 设备检测失败；修复 ADB 后重新检查。"})
        else:
            for line in listing.get("stdout", "").splitlines():
                fields = line.split()
                if len(fields) < 2 or fields[0] in ("List", "*"):
                    continue
                serial, state = fields[:2]
                item = {"serial": serial, "state": state, "operational": False}
                if state == "device":
                    probe = run([tools["adb"], "-s", serial, "shell", "getprop", "ro.build.version.sdk"])
                    item["operational"] = probe.get("returncode") == 0 and probe.get("stdout", "").isdigit()
                    if item["operational"]:
                        qemu = run([tools["adb"], "-s", serial, "shell", "getprop", "ro.kernel.qemu"])
                        item.update(android_sdk=int(probe["stdout"]), kind=("emulator" if serial.startswith("emulator-")
                                    or qemu.get("stdout") == "1" else "physical_or_remote"))
                result["connected_devices"].append(item)
    else:
        gate["errors"].append({"code": "ADB_MISSING", "message": "未找到 adb；无法确认真机或模拟器可用，先修复现有 SDK/platform-tools。"})
    if tools["emulator"]:
        listing = run([tools["emulator"], "-list-avds"])
        result["available_avds"] = listing
        if listing.get("returncode") == 0:
            result["avds"] = avd_inventory([s.strip() for s in listing.get("stdout", "").splitlines() if s.strip()], sdk)
    online = [d for d in result["connected_devices"] if d["operational"]]
    configured = [d for d in result["avds"] if d["configured"]]
    if not online and not configured:
        gate["errors"].append({"code": "NO_ANDROID_DEVICE", "message": "未发现可响应的已授权 Android 设备，也没有配置和系统镜像完整的 AVD；调研已中断。"})
        if any(d["state"] == "unauthorized" for d in result["connected_devices"]):
            gate["errors"].append({"code": "DEVICE_UNAUTHORIZED", "message": "检测到未授权真机；请在设备上批准 USB 调试后重新运行环境检查。"})
    if not gate["errors"]:
        gate.update(status="passed", online_device_count=len(online), configured_avd_count=len(configured),
                    requires_emulator_start=not bool(online))
    return result


def require_device_environment(sdk=None):
    """Enforce the gate before any downloader makes external requests or creates an attempt."""
    tools = {n: find_tool(n, sdk) for n in ("adb", "emulator")}
    result = device_check(tools, sdk)
    if result["device_gate"]["status"] != "passed":
        raise ValueError("；".join(e["message"] for e in result["device_gate"]["errors"]))
    return result["device_gate"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sdk")
    p.add_argument("--country", help="Used only to match node names; not a verified exit location")
    p.add_argument("--controller", help="Known loopback Clash/Mihomo HTTP controller URL")
    p.add_argument("--secret-env", help="Environment variable holding the controller secret; never printed")
    p.add_argument("--report", help="Save the environment result as JSON in the task output directory")
    args = p.parse_args()
    emit("环境检查 · 工具", "running", "检查 Android SDK、ADB、模拟器与校验工具。")
    tools = {n: find_tool(n, args.sdk) for n in ["adb", "emulator", "aapt", "apksigner", "java", "apkeep"]}
    result = {"os": platform.system(), "sdk_roots": [str(x) for x in sdk_roots(args.sdk)], "tools": tools,
              "proxy_environment": {k: public_url(v) for k, v in os.environ.items()
                                    if k.lower() in ("http_proxy", "https_proxy", "all_proxy") and v},
              "network_changed": False, "exit_country": "unknown", "vpn_node_inventory_status": "not_checked"}
    result["research_tools"] = {n: find_tool(n, args.sdk) for n in ("jadx", "apktool", "node", "frida", "cmake", "clang")}
    result["research_tools_are_route_specific"] = True
    emit("环境检查 · 设备", "running", "检测已连接真机/模拟器，并核查已有 AVD 配置与系统镜像。")
    result.update(device_check(tools, args.sdk))
    if result["device_gate"]["status"] != "passed":
        result["status"] = "failed"
        result["downstream_allowed"] = False
        result["skipped_checks"] = ["vpn_and_proxy"]
        if args.report:
            write_json(args.report, result)
        for error in result["device_gate"]["errors"]:
            emit("环境检查", "failed", error["code"] + "：" + error["message"])
        emit("调研执行", "skipped", "设备硬门槛未通过，不查询下载渠道、不取包。")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 4
    gate = result["device_gate"]
    emit("环境检查 · 设备", "succeeded", f"{gate['online_device_count']} 台在线可响应设备，{gate['configured_avd_count']} 个配置完整的 AVD。")
    emit("环境检查 · VPN/代理", "running", "只读盘点现有代理和 VPN 能力，不切换节点。")
    if platform.system() == "Darwin":
        sc = run(["/usr/sbin/scutil", "--proxy"])
        result["system_proxy"] = [s.strip() for s in sc.get("stdout", "").splitlines()
                                  if re.search(r"(?:HTTP|HTTPS|SOCKS|ProxyAutoConfig).*(?:Enable|Port|Proxy)\s*:", s)]
        apps = []
        for root in [Path("/Applications"), Path.home() / "Applications"]:
            if root.is_dir():
                apps += [x.name for x in root.iterdir() if re.search(r"鹿语|clash|surge|shadowrocket|v2ray|quantumult|sing.box", x.name, re.I)]
        result["vpn_client_candidates"] = apps
        result["vpn_process_names"] = run(["pgrep", "-il", "clash|mihomo|surge|sing-box|v2ray"]).get("stdout", "").splitlines()
    if args.controller:
        u = urllib.parse.urlsplit(args.controller)
        if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost", "::1") or u.username or u.password or u.path not in ("", "/") or u.query:
            p.error("Controller must be a known loopback HTTP origin without credentials or a path")
        headers = {}
        if args.secret_env:
            secret = os.environ.get(args.secret_env)
            if not secret:
                p.error("Controller secret environment variable is unset")
            headers["Authorization"] = "Bearer " + secret
        try:
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with op.open(urllib.request.Request(args.controller.rstrip("/") + "/proxies", headers=headers), timeout=10) as r:
                proxies = json.load(r).get("proxies", {})
            aliases = {"PH": ["菲律宾", "philippines", "manila", "🇵🇭"], "MX": ["墨西哥", "mexico", "🇲🇽"],
                       "VN": ["越南", "vietnam", "hanoi", "🇻🇳"], "TH": ["泰国", "thailand", "bangkok", "🇹🇭"]}
            terms = aliases.get((args.country or "").upper(), [])
            result["vpn_nodes"] = [{"name": name, "type": meta.get("type"), "current": meta.get("now"),
                                    "choices": meta.get("all"),
                                    "matches_country_name": any(s in name.lower() for s in terms)}
                                   for name, meta in proxies.items()]
            result["country_match_is_exit_verification"] = False
            result["vpn_node_inventory_status"] = "read_from_controller"
        except Exception as exc:
            result["controller_error"] = {"type": type(exc).__name__, "http_status": getattr(exc, "code", None)}
            result["vpn_node_inventory_status"] = "controller_unavailable"
    result["status"] = "passed"
    result["downstream_allowed"] = True
    result["missing_optional_tools"] = [n for n in ("aapt", "apksigner", "java", "apkeep") if not tools[n]]
    emit("环境检查 · VPN/代理", "succeeded", "盘点完成；未验证的出口地区和节点保持未知，VPN 不是全局必需项。")
    if args.report:
        write_json(args.report, result)
    emit("环境检查", "succeeded", "设备硬门槛通过，可以进入目标识别与信息补齐。")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
