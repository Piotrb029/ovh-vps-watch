"""Get one OVH VPS-3 in Europe the moment it is in stock.

Owner 2026-11-16: „sprawdzał czy oferta VPS-3 z serwerem w Europie jest dostępna a jak się pojawi to ma ją kupić z systemem Linux”;
„Rozliczenie miesięczne, lokalizacja dowolna oby Europa, cena maks 100zl, tak ubuntu”; then „1. Zgoda, 2. Londyn też, 3. Dajmy 80zl”
(the upgrade first, London counts, the cap is 80). The VPS-2 this bot bought on 2026-11-04 runs
the project's checks, so the first try is to upgrade that server in place (same address, same setup); a new VPS-3 only when OVH
refuses the upgrade. The cap is taken on the price WITH tax. Lock of this round: an issue labelled `vps3-bought`.

Earlier round (kept for the record):

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
# PLN per month WITH tax (owner 2026-11-16: „cena maks 100zl”, then „Dajmy 80zl”); the dry run of that night gave 52.20 net, 64.21 with tax.
# Then (same night): „To zrób zeby mógł kupić też vps-2 drugi. Lepszy rydz jak nic”, „drugi vps-2 ma nie wykluczyć Update lub zakupu
# vps-3”: a second VPS-2 is a fallback with its own lock; it never stops the VPS-3, and it is not bought once the VPS-3 is.
# (plan, name, cap with tax, lock label, try the in-place upgrade first). VPS-2 was 36.20 net (44.53 with tax) on 2026-11-03.
PLANS = [("vps-2027-model3", "VPS-3", 80.0, "vps3-bought", True), ("vps-2027-model2", "VPS-2", 50.0, "vps2-second-bought", False)]
OS = "Ubuntu 24.04"
# „Lokalizacja dowolna oby Europa”, in the order tried when several have stock.
EUROPE = ["DE", "WAW", "GRA", "SBG", "EU-WEST-RBX", "EU-SOUTH-MIL", "UK"]
# The server to upgrade in place: the VPS-2 with the project's check runners (its host name on the box).
UPGRADE_SERVICE = "vps-9d39ebe7"


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def issue(label: str, title: str, body: str) -> None:
    subprocess.run(["gh", "label", "create", label, "-R", REPO, "--color", "B60205"], capture_output=True)
    gh("issue", "create", "-R", REPO, "--label", label, "--assignee", "Piotrb029", "--title", title, "--body", body)


def already_bought(label: str) -> bool:
    out = gh("issue", "list", "-R", REPO, "--label", label, "--state", "all", "--json", "number")
    return len(json.loads(out)) > 0


def buy(client: ovh.Client, plan: str, cap: float, datacenter: str) -> dict:
    cart = client.post("/order/cart", ovhSubsidiary="PL", description=f"auto-buy {plan} {datacenter}")
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
    wanted = {"vps_datacenter": datacenter, "vps_os": OS, "region": "europe"}
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
    gross = float(preview["prices"]["withTax"]["value"])
    if gross > cap:
        client.delete(f"/order/cart/{cart_id}")
        raise RuntimeError(f"{plan} in {datacenter}: price {gross} PLN with tax is over the cap {cap}")
    if DRY_RUN:
        client.delete(f"/order/cart/{cart_id}")
        return {"dryRun": True, "net": net, "gross": gross, "plan": plan, "where": datacenter}
    order = client.post(f"/order/cart/{cart_id}/checkout", autoPayWithPreferredPaymentMethod=True, waiveRetractationPeriod=False)
    return {"orderId": order.get("orderId"), "url": order.get("url"), "net": net, "gross": gross, "plan": plan, "where": datacenter}


def upgrade(client: ovh.Client, plan: str, cap: float, datacenter: str) -> dict:
    # The account holds more than one VPS now; only the one with the check runners is upgraded, never the panel's server.
    services = [s for s in client.get("/order/upgrade/vps") if s.startswith(UPGRADE_SERVICE)]
    if len(services) != 1:
        raise RuntimeError(f"upgrade: no single VPS named {UPGRADE_SERVICE}* among the upgradable ones")
    service = services[0]
    offers = [o.get("planCode") for o in client.get(f"/order/upgrade/vps/{service}")]
    if plan not in offers:
        raise RuntimeError(f"upgrade: {plan} not offered for {service} (offers: {offers})")
    preview = client.get(f"/order/upgrade/vps/{service}/{plan}", quantity=1)
    net = float(preview["order"]["prices"]["withoutTax"]["value"])
    gross = float(preview["order"]["prices"]["withTax"]["value"])
    if gross > cap:
        raise RuntimeError(f"upgrade {plan}: price {gross} PLN with tax is over the cap {cap}")
    if DRY_RUN:
        return {"dryRun": True, "net": net, "gross": gross, "plan": plan, "service": service, "where": service}
    order = client.post(f"/order/upgrade/vps/{service}/{plan}", quantity=1, autoPayWithPreferredPaymentMethod=True)
    return {"orderId": order["order"].get("orderId"), "url": order["order"].get("url"), "net": net, "gross": gross, "plan": plan, "service": service, "where": service}


def main() -> int:
    # Arguments: „plan@datacenter” for every place the watch saw stock in.
    seen = [a.split("@", 1) for a in sys.argv[1:] if "@" in a]
    if not seen:
        return 0
    if not all(os.environ.get(k) for k in ("OVH_APP_KEY", "OVH_APP_SECRET", "OVH_CONSUMER_KEY")):
        print("no OVH API keys: notify only")
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
    got_vps3 = already_bought("vps3-bought")
    for plan, name, cap, lock, upgrade_first in PLANS:
        places = [dc for dc in EUROPE if [plan, dc] in seen]
        if not places:
            continue
        if already_bought(lock) or (plan != "vps-2027-model3" and got_vps3):
            print(f"{name}: not needed any more ({lock} or vps3-bought exists)")
            continue
        # The upgrade once (VPS-3 only), then a new server in each place that has stock.
        ways = ([("upgrade", upgrade, places[0])] if upgrade_first else []) + [("new", buy, dc) for dc in places]
        for how, action, where in ways:
            try:
                result = action(client, plan, cap, where)
            except Exception as e:  # noqa: BLE001 - the next way or place may still go through; every error is reported
                errors.append(f"{name} ({how}, {where}): {e}")
                continue
            if result.get("dryRun"):
                # A dry run shows every way, so the owner sees the prices before the bot is armed.
                print(f"DRY RUN ok: {name} via {how} ({result['where']}), {result['net']} PLN net, {result['gross']} PLN with tax, nothing ordered")
                continue
            what = f"ulepszenie obecnego VPS {result['service']} do {name}" if how == "upgrade" else f"nowy {name} ({where}, {OS})"
            issue(
                lock,
                f"OVH: zamówione {name}" + (" (ulepszenie)" if how == "upgrade" else ""),
                f"Bot zamówił: {what}, płatność miesięczna, {result['net']} zł netto ({result['gross']} zł z podatkiem) teraz.\n"
                f"Zamówienie: {result['orderId']}\n{result['url']}\n\n"
                f"Bot nie zamówi drugi raz {name}, dopóki to zgłoszenie istnieje. Sprawdź płatność w panelu OVH.",
            )
            print(f"ordered {name} via {how}: order {result['orderId']}")
            if plan == "vps-2027-model3":
                got_vps3 = True
            break
    if errors:
        print("\n".join(errors))
        if not DRY_RUN:
            issue("vps-buy-failed", "OVH: automatyczne zamówienie nie wyszło", "Bot widział VPS w Europie, ale zamówienie się nie udało:\n\n" + "\n".join(f"- {e}" for e in errors) + "\n\nZamów ręcznie w panelu OVH albo popraw bota.")
        return 1 if not DRY_RUN else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
