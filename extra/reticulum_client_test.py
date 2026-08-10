#reticulum_client_test.py
import os
import time
import RNS
import LXMF

# Must match rnsd's own configdir (config.reticulum.reticulum_config_dir in
# local.yaml, "data/reticulum/rns_config" under /opt/meshpoint by default)
# for two reasons, not just one:
#  1. With no configdir at all, RNS falls back to ~/.reticulum, resolved
#     against $HOME -- if this runs as the `meshpoint` system user (e.g.
#     `sudo -u meshpoint ...`), that's /home/meshpoint, which doesn't
#     exist (meshpoint is a --no-create-home service account) and isn't
#     writable -- the exact PermissionError meshpoint's own service hit
#     before it got its own explicit configdir.
#  2. Even running as a different user with a real writable $HOME, the
#     shared-instance RPC channel to rnsd authenticates *per-configdir* --
#     a client using any other configdir won't reliably exchange messages
#     with a peer attached through this same rnsd, even though outbound
#     sends may appear to work.
CONFIG_DIR = os.environ.get("RETICULUM_CONFIG_DIR", "/opt/meshpoint/data/reticulum/rns_config")
reticulum = RNS.Reticulum(configdir=CONFIG_DIR, loglevel=RNS.LOG_VERBOSE)

# Anchored to /tmp explicitly, not a relative "./" path -- this script is
# meant to be copied to and run from /tmp (world-writable) as the
# `meshpoint` user, but the *current directory* at invocation time can be
# anything (e.g. a pi-owned checkout), which meshpoint can't write into.
IDENTITY_PATH = os.environ.get("RETICULUM_TEST_IDENTITY", "/tmp/reticulum_client_test_identity")
if os.path.exists(IDENTITY_PATH):
    identity = RNS.Identity.from_file(IDENTITY_PATH)
    print(f"Loaded existing identity from {IDENTITY_PATH}")
else:
    identity = RNS.Identity()
    identity.to_file(IDENTITY_PATH)
    print(f"Generated new identity, saved to {IDENTITY_PATH}")

router = LXMF.LXMRouter(storagepath=os.environ.get("RETICULUM_TEST_STORAGE", "/tmp/lxmf_test_storage"))
source = router.register_delivery_identity(identity, display_name="MeshpointTest")

def message_received(message):
    print(f"\n>>> Received from {RNS.prettyhexrep(message.source_hash)}: "
          f"{message.content.decode('utf-8', errors='replace')}\n")

router.register_delivery_callback(message_received)
source.announce()

# Same aspects meshpoint's own LxmfService listens for
# (src/reticulum/lxmf_service.py's _ANNOUNCE_ASPECTS) -- lxmf.delivery is
# what a real messaging peer (like meshpoint itself) announces under.
_ANNOUNCE_ASPECTS = ("lxmf.delivery", "lxmf.propagation", "nomadnetwork.node")
_announces = {}  # dest_hash_hex -> {display_name, aspect, first_seen, last_seen, count}

class _AnnounceHandler:
    def __init__(self, aspect_filter):
        self.aspect_filter = aspect_filter

    # RNS calls this with keyword args (destination_hash=, announced_identity=,
    # app_data=) -- the parameter name is part of the actual call contract,
    # not just cosmetic, so it can't be underscore-prefixed to silence the
    # unused-arg lint hint the way a positional-only callback could.
    def received_announce(self, destination_hash, announced_identity, app_data):
        dest_hex = RNS.hexrep(destination_hash, delimit=False)
        display_name = ""
        if app_data:
            try:
                display_name = LXMF.display_name_from_app_data(app_data) or ""
            except Exception:
                display_name = ""
        now = time.time()
        entry = _announces.get(dest_hex)
        if entry is None:
            entry = {"first_seen": now, "count": 0}
            _announces[dest_hex] = entry
        entry["display_name"] = display_name
        entry["aspect"] = self.aspect_filter
        entry["last_seen"] = now
        entry["count"] += 1
        # Live line the moment it arrives -- don't wait for "showannounce"
        # to notice meshpoint (or anyone else) actually announced.
        name = display_name or "(no display name)"
        print(f"\n[announce] {self.aspect_filter} {dest_hex} {name}\n> ", end="", flush=True)

for aspect in _ANNOUNCE_ASPECTS:
    RNS.Transport.register_announce_handler(_AnnounceHandler(aspect))

def show_announces():
    if not _announces:
        print("No announces received yet.")
        return
    rows = sorted(_announces.items(), key=lambda kv: kv[1]["last_seen"], reverse=True)
    print(f"{len(rows)} known announce(s), most recent first:")
    for dest_hex, entry in rows:
        age_s = int(time.time() - entry["last_seen"])
        name = entry["display_name"] or "(no display name)"
        print(f"  {dest_hex}  {entry['aspect']:<18}  {name!r:<24}  "
              f"seen {entry['count']}x, last {age_s}s ago")

def send_message(dest_hash_hex, text):
    dest_hash = bytes.fromhex(dest_hash_hex.strip("<>"))
    dest_identity = RNS.Identity.recall(dest_hash)
    if dest_identity is None:
        print(f"Unknown destination {dest_hash_hex} -- no announce received from it yet")
        return
    destination = RNS.Destination(
        dest_identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery",
    )
    lxm = LXMF.LXMessage(destination, source, text, desired_method=LXMF.LXMessage.DIRECT)
    router.handle_outbound(lxm)
    print(f"Sent to {dest_hash_hex}: {text}")

print(f"My test LXMF address: {RNS.prettyhexrep(source.hash)}")
print("Announced. Type '<destination_hash> <message>' and press Enter to send, "
      "'showannounce' to list every announce seen so far, or Ctrl+C to quit.")

try:
    while True:
        line = input("> ").strip()
        if not line:
            continue
        if line == "showannounce":
            show_announces()
            continue
        dest, _, text = line.partition(" ")
        if not text:
            print("Format: <destination_hash> <message text>")
            continue
        send_message(dest, text)
except KeyboardInterrupt:
    pass
