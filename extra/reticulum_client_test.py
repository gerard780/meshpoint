#reticulum_client_test.py 
import os
import RNS
import LXMF
import time

reticulum = RNS.Reticulum(loglevel=RNS.LOG_VERBOSE)

IDENTITY_PATH = "./reticulum_client_test_identity"
if os.path.exists(IDENTITY_PATH):
    identity = RNS.Identity.from_file(IDENTITY_PATH)
    print(f"Loaded existing identity from {IDENTITY_PATH}")
else:
    identity = RNS.Identity()
    identity.to_file(IDENTITY_PATH)
    print(f"Generated new identity, saved to {IDENTITY_PATH}")

router = LXMF.LXMRouter(storagepath="./lxmf_test_storage")
source = router.register_delivery_identity(identity, display_name="MeshpointTest")

def message_received(message):
    print(f"\n>>> Received from {RNS.prettyhexrep(message.source_hash)}: "
          f"{message.content.decode('utf-8', errors='replace')}\n")

router.register_delivery_callback(message_received)
source.announce()

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
print("Announced. Type '<destination_hash> <message>' and press Enter to send, or Ctrl+C to quit.")

try:
    while True:
        line = input("> ").strip()
        if not line:
            continue
        dest, _, text = line.partition(" ")
        if not text:
            print("Format: <destination_hash> <message text>")
            continue
        send_message(dest, text)
except KeyboardInterrupt:
    pass

