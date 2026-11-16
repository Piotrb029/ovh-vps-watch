# OVH VPS watch
Watches OVH VPS-3 (Linux) in Europe (DE, WAW, GRA, SBG, RBX, MIL, UK) and gets one the moment it is in stock: first an in-place upgrade of
the VPS-2 that runs the project's checks, then, when OVH refuses, a new server. Monthly billing, Ubuntu 24.04, at most 80 PLN a month
with tax (owner 2026-11-16). It buys once: an issue labelled `vps3-bought` is the lock; close nothing, delete that issue to buy again.
Fallback of the same night („Lepszy rydz jak nic”): a second VPS-2 (new server, at most 50 PLN with tax, lock `vps2-second-bought`) when
VPS-2 has stock and the VPS-3 is not bought yet; it never blocks the VPS-3.

- `watch.yml` runs on GitHub's schedule (every 15 min on paper, in practice hours apart) and by hand; the stock check is the public OVH API.
- A cron job on the owner's dev server asks the same public API every minute and starts this workflow the moment stock appears, so the
  OVH keys stay in this repository's secrets and nowhere else.
- Dry run (no payment, the cart is deleted): Actions → OVH VPS watch → Run workflow → `dry_run`, `force_found` = `vps-2027-model3@DE`.
