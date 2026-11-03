"""Buy one OVH VPS in Germany (DE, Limburg) the moment it is in stock.

Owner consent 2026-11-03: „Vps2 w pierwszej kolejności vps3 tez bedzie ok, kupuj”; then „Obecny vps jest w niemczech
wiec wszystko sie zgadza, pasuje mi taki uklad”: upgrade the current VPS in place first (same server, IP and data), buy a new
one only when the upgrade is refused.
Monthly billing without commitment, Ubuntu 24.04, paid with the account's preferred payment method.
Buys at most once: an issue labelled `vps-bought` (open or closed) is the lock.
"""
import json
import os
import subprocess
import sys

import ovh

REPO = os.environ["REPO"]
DRY_RUN = os.environ.get("DRY_RUN") == "1"
# Net PLN per month; the catalogue on 2026-11-03 said 36.20 and 52.20 without commitment.
PLANS = [("vps-2027-model2", "VPS-2", 37.0), ("vps-2027-model3", "VPS-3", 53.0)]
OS = "Ubuntu 24.04"
DATACENTER = "DE"


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def issue(label: str, title: str, body: str) -> None:
    subprocess.run(["gh", "label", "create", label, "-R", REPO, "--color", "B60205"], capture_output=True)
    gh("issue", "create", "-R", REPO, "--label", label, "--assignee", "Piotrb029", "--title", title, "--body", body)


def already_bought() -> bool:
    out = gh("issue", "list", "-R", REPO, "--label", "vps-bought", "--state", "all", "--json", "number")
    return len(json.loads(out)) > 0


def buy(client: ovh.Client, plan: str, cap: float) -> dict:
    cart = client.post("/order/cart", ovhSubsidiary="PL", description="auto-buy VPS DE")
    cart_id = cart["cartId"]
    client.post(f"/order/cart/{cart_id}/assign")
    item = client.post(f"/order/cart/{cart_id}/vps", planCode=plan, duration="P1M", pricingMode="default", quantity=1)
    item_id = item["itemId"]
    # Mandatory addons of the 2027 range: Linux, local storage, daily backup with one day kept (the included ones).
    picks = {"os": "option-linux", "storage": "option-storage-local-", "automatedBackup": "option-auto-backup-2027-1-"}
    options = client.get(f"/order/cart/{cart_id}/vps/options", planCode=plan)
    for family, prefix in picks.items():
        match = [o["planCode"] for o in options if o.get("family") == family and o["planCode"].startswith(prefix)]
        if not match:
            raise RuntimeError(f"no {family} option starting with {prefix} for {plan}")
        client.post(f"/order/cart/{cart_id}/vps/options", itemId=item_id, planCode=match[0], duration="P1M", pricingMode="default", quantity=1)
    wanted = {"vps_datacenter": DATACENTER, "vps_os": OS, "region": "europe"}
    done = set()
    for req in client.get(f"/order/cart/{cart_id}/item/{item_id}/requiredConfiguration"):
        label = req["label"]
        if label in wanted:
            client.post(f"/order/cart/{cart_id}/item/{item_id}/configuration", label=label, value=wanted[label])
            done.add(label)
        elif req.get("required"):
            raise RuntimeError(f"unknown required configuration {label}")
    # The OS is optional in the catalogue, so it may not be listed as required; set it anyway.
    if "vps_os" not in done:
        client.post(f"/order/cart/{cart_id}/item/{item_id}/configuration", label="vps_os", value=OS)
    preview = client.get(f"/order/cart/{cart_id}/checkout")
    net = float(preview["prices"]["withoutTax"]["value"])
    if net > cap:
        client.delete(f"/order/cart/{cart_id}")
        raise RuntimeError(f"{plan}: price {net} PLN net is over the cap {cap}")
    if DRY_RUN:
        client.delete(f"/order/cart/{cart_id}")
        return {"dryRun": True, "net": net, "plan": plan}
    order = client.post(f"/order/cart/{cart_id}/checkout", autoPayWithPreferredPaymentMethod=True, waiveRetractationPeriod=False)
    return {"orderId": order.get("orderId"), "url": order.get("url"), "net": net, "plan": plan}


def upgrade(client: ovh.Client, plan: str, cap: float) -> dict:
    services = client.get("/order/upgrade/vps")
    if len(services) != 1:
        raise RuntimeError(f"upgrade: expected one VPS, found {services}")
    service = services[0]
    offers = [o.get("planCode") for o in client.get(f"/order/upgrade/vps/{service}")]
    if plan not in offers:
        raise RuntimeError(f"upgrade: {plan} not offered for {service} (offers: {offers})")
    preview = client.get(f"/order/upgrade/vps/{service}/{plan}", quantity=1)
    net = float(preview["order"]["prices"]["withoutTax"]["value"])
    if net > cap:
        raise RuntimeError(f"upgrade {plan}: price {net} PLN net is over the cap {cap}")
    if DRY_RUN:
        return {"dryRun": True, "net": net, "plan": plan, "service": service}
    order = client.post(f"/order/upgrade/vps/{service}/{plan}", quantity=1, autoPayWithPreferredPaymentMethod=True)
    return {"orderId": order["order"].get("orderId"), "url": order["order"].get("url"), "net": net, "plan": plan, "service": service}


def main() -> int:
    found = sys.argv[1:]
    if not found:
        return 0
    if not all(os.environ.get(k) for k in ("OVH_APP_KEY", "OVH_APP_SECRET", "OVH_CONSUMER_KEY")):
        print("no OVH API keys: notify only")
        return 0
    if already_bought():
        print("already bought (vps-bought issue exists): notify only")
        return 0
    client = ovh.Client(
        endpoint="ovh-eu",
        application_key=os.environ["OVH_APP_KEY"],
        application_secret=os.environ["OVH_APP_SECRET"],
        consumer_key=os.environ["OVH_CONSUMER_KEY"],
    )
    if DRY_RUN:
        cred = client.get("/auth/currentCredential")
        print("credential status:", cred.get("status"), "rules:", [f"{r['method']} {r['path']}" for r in cred.get("rules", [])])
    errors = []
    for plan, name, cap in PLANS:
        if plan not in found:
            continue
        for how, action in (("upgrade", upgrade), ("new", buy)):
            try:
                result = action(client, plan, cap)
            except Exception as e:  # noqa: BLE001 - the next way or plan may still go through; every error is reported
                errors.append(f"{name} ({how}): {e}")
                continue
            if result.get("dryRun"):
                print(f"DRY RUN ok: {name} via {how}, {result['net']} PLN net, nothing ordered")
                return 0
            what = f"ulepszenie obecnego VPS {result['service']} do {name}" if how == "upgrade" else f"nowy {name} (DE Limburg, {OS})"
            issue(
                "vps-bought",
                f"OVH: zamówione {name}" + (" (ulepszenie)" if how == "upgrade" else ""),
                f"Bot zamówił: {what}, płatność miesięczna, {result['net']} zł netto teraz.\n"
                f"Zamówienie: {result['orderId']}\n{result['url']}\n\n"
                "Bot więcej nie zamówi, dopóki to zgłoszenie istnieje. Sprawdź płatność w panelu OVH.",
            )
            print(f"ordered {name} via {how}: order {result['orderId']}")
            return 0
    if errors:
        print("\n".join(errors))
        if not DRY_RUN:
            issue("vps-buy-failed", "OVH: automatyczne zamówienie nie wyszło", "Bot widział VPS w DE, ale zamówienie się nie udało:\n\n" + "\n".join(f"- {e}" for e in errors) + "\n\nZamów ręcznie w panelu OVH (VPS → zmień model) albo https://www.ovhcloud.com/pl/vps/")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
