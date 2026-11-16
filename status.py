"""Read-only: the state of one OVH order and of the account's payment methods. Prints no card data, address or link."""
import os
import sys

import ovh


def main() -> int:
    client = ovh.Client(
        endpoint="ovh-eu",
        application_key=os.environ["OVH_APP_KEY"],
        application_secret=os.environ["OVH_APP_SECRET"],
        consumer_key=os.environ["OVH_CONSUMER_KEY"],
    )
    order = sys.argv[1]
    for label, call in (
        ("order status", lambda: client.get(f"/me/order/{order}/status")),
        ("order", lambda: {k: v for k, v in client.get(f"/me/order/{order}").items() if k in ("date", "expirationDate", "retractionDate")}),
        ("payment methods", lambda: [{k: m.get(k) for k in ("paymentType", "status", "default")} for m in (client.get(f"/me/payment/method/{i}") for i in client.get("/me/payment/method"))]),
        ("vps count", lambda: len(client.get("/vps"))),
    ):
        try:
            print(f"{label}: {call()}")
        except Exception as e:  # noqa: BLE001 - a missing API right for one call must not hide the others
            print(f"{label}: ERROR {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
