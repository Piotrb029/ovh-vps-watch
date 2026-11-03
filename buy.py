"""Buy one OVH VPS in Germany (DE, Limburg) the moment it is in stock.

Owner consent 2026-11-03: „Vps2 w pierwszej kolejności vps3 tez bedzie ok, kupuj”.
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
    wanted = {"vps_datacenter": DATACENTER, "vps_os": OS, "region": "europe"}
    for req in client.get(f"/order/cart/{cart_id}/item/{item_id}/requiredConfiguration"):
        label = req["label"]
        if label in wanted:
            client.post(f"/order/cart/{cart_id}/item/{item_id}/configuration", label=label, value=wanted[label])
        elif req.get("required"):
            raise RuntimeError(f"unknown required configuration {label}")
    for label in ("vps_os",):
        configured = [c["label"] for c in client.get(f"/order/cart/{cart_id}/item/{item_id}/configuration")]
        if label not in configured:
            client.post(f"/order/cart/{cart_id}/item/{item_id}/configuration", label=label, value=wanted[label])
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
        try:
            result = buy(client, plan, cap)
        except Exception as e:  # noqa: BLE001 - the next plan may still go through; every error is reported
            errors.append(f"{name}: {e}")
            continue
        if result.get("dryRun"):
            print(f"DRY RUN ok: {name}, {result['net']} PLN net, cart deleted")
            return 0
        issue(
            "vps-bought",
            f"OVH: kupiony {name} w Niemczech",
            f"Bot kupił {name} (DE Limburg, {OS}, płatność miesięczna bez zobowiązania), {result['net']} zł netto.\n"
            f"Zamówienie: {result['orderId']}\n{result['url']}\n\n"
            "Bot więcej nie kupi, dopóki to zgłoszenie istnieje. Sprawdź płatność w panelu OVH.",
        )
        print(f"bought {name}: order {result['orderId']}")
        return 0
    if errors:
        issue("vps-buy-failed", "OVH: automatyczny zakup nie wyszedł", "Bot widział VPS w DE, ale zakup się nie udał:\n\n" + "\n".join(f"- {e}" for e in errors) + "\n\nZamów ręcznie: https://www.ovhcloud.com/pl/vps/")
        print("\n".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
