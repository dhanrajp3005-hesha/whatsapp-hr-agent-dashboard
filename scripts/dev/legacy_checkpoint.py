import json
import os

CHECKPOINT_FILE = "checkpoint.json"


def load_checkpoint():

    if not os.path.exists(CHECKPOINT_FILE):
        return None

    try:
        with open(CHECKPOINT_FILE, "r") as f:
            data = json.load(f)
            return data

    except Exception:
        return None


def save_checkpoint(header, email):

    data = {
        "last_header": header,
        "last_email": email
    }

    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f, indent=4)

    print("=" * 80)
    print("Checkpoint Saved")
    print(data)
    print("=" * 80)
